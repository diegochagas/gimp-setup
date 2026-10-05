# GIMP side of the "PSD with editable text" plug-in (psd-text.py).
#
# Vendored from comic-skills/psd-xcf-convert/scripts/gimp_convert_job.py
# (https://github.com/diegochagas/comic-skills), see PATCHES.md here:
# the batch-job wrapper was removed so psd-text.py can import the two
# halves directly:
#
#   apply_psd_text(image, info, fonts, notes)
#       after GIMP's own PSD loader: every rasterized Type layer listed in
#       the ag-psd info JSON (psd_text_info.mjs) is REPLACED, at the same
#       place in the stack, by a native GIMP text layer, and every Layer
#       Style stroke / drop shadow becomes a "Text Styling" filter.
#   describe_image(image, notes)
#       before GIMP's own PSD export: describes every text layer and
#       Text Styling filter for write_psd_text.mjs, which turns the
#       rasterized text of the export back into Photoshop Type layers.
#
# A layer parasite "psd-xcf-convert" carries what GIMP cannot store
# (rotation angle, the Photoshop name of a substituted font), so a PSD
# opened and exported again keeps its own fonts and angles.

import json
import math
import os
import re
import traceback
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
gi.require_version('Babl', '0.1')
from gi.repository import Gimp, Gegl, Gio, Babl

try:
    # the Layer Style plug-in's renderer (installed next to this file):
    # Photoshop effects become editable Layer Styles (Layer > Layer Style)
    import layer_style_engine as LS
except ImportError:
    LS = None

PARASITE = "psd-xcf-convert"
STYLE_OPS = ("gegl:styles", "gegl:dropshadow")


def color_hex(c):
    b = c.get_bytes(Babl.format("R'G'B'A u8")).get_data()
    return "#%02x%02x%02x" % (b[0], b[1], b[2])


def walk(layers, prefix=()):
    """(path, layer) for every layer, top first, groups before their children."""
    for i, l in enumerate(layers):
        path = prefix + (i,)
        yield path, l
        if l.is_group():
            yield from walk(l.get_children(), path)


def parasite_text(layer, name):
    """Parasite payload as str ('' if absent). get_data() hands the bytes back
    SIGNED, so any accented letter would break a plain bytes()."""
    try:
        if name not in layer.get_parasite_list():
            return ""
        return bytes(b & 0xFF for b in layer.get_parasite(name).get_data()).decode("utf8", "replace")
    except Exception:
        return ""


def get_parasite_json(layer):
    try:
        return json.loads(parasite_text(layer, PARASITE) or "{}")
    except ValueError:
        return {}


def set_parasite_json(layer, data):
    layer.attach_parasite(Gimp.Parasite.new(PARASITE, 1, list(json.dumps(data).encode("utf8"))))


def line_height(font, size):
    ok, _w, h1, asc, _d = Gimp.text_get_extents_font("Hg", size, font)
    ok, _w, h2, _a, _d = Gimp.text_get_extents_font("Hg\nHg", size, font)
    return h2 - h1, asc


# Adobe text engine language codes <-> GIMP text language tags (only the
# ones known for sure; anything else is left to each program's default).
ADOBE_TO_GIMP_LANGUAGE = {0: "en-us", 10: "pt", 11: "pt-br"}
GIMP_TO_ADOBE_LANGUAGE = {"en-us": 0, "en": 0, "pt": 10, "pt-pt": 10, "pt-br": 11}


def adobe_language(layer, default):
    tag = (layer.get_language() or "").lower().replace("_", "-")
    return GIMP_TO_ADOBE_LANGUAGE.get(tag, default)


JUSTIFY = {"left": Gimp.TextJustification.LEFT, "right": Gimp.TextJustification.RIGHT,
           "center": Gimp.TextJustification.CENTER}
JUSTIFY_BACK = {int(Gimp.TextJustification.LEFT): "left", int(Gimp.TextJustification.RIGHT): "right",
                int(Gimp.TextJustification.CENTER): "center", int(Gimp.TextJustification.FILL): "justify-left"}


# --------------------------------------------------------------- PSD -> XCF

def find_font(fonts, psname, notes):
    """GIMP font for a Photoshop PostScript name, through the candidates
    psd_text_fonts.py resolved with fontconfig. Returns (font, gimp_name)."""
    entry = (fonts or {}).get(psname) or {}
    for cand in entry.get("gimp", []) + [psname]:
        try:
            f = Gimp.Font.get_by_name(cand)
        except Exception:
            f = None
        if f is not None:
            if entry.get("substitute"):
                notes.add(f'font "{psname}" is not installed: using "{cand}"')
            return f, cand
    f = Gimp.context_get_font()
    notes.add(f'font "{psname}" is not installed: using GIMP\'s current font "{f.get_name()}"')
    return f, f.get_name()


def run_text(run):
    return run["text"].upper() if run.get("caps") else run["text"]


def build_markup(runs, base, fonts, yres):
    parts = []
    for r in runs:
        s = escape(run_text(r))
        attrs = []
        if r["font"] != base["font"]:
            attrs.append('font="%s"' % escape(fonts[r["font"]], {'"': "&quot;"}))
        if abs(r["size"] - base["size"]) > 0.01:
            # pango span sizes are 1024ths of a POINT at the image resolution
            attrs.append('size="%d"' % round(r["size"] * 72.0 / yres * 1024))
        if r["color"] != base["color"]:
            attrs.append('foreground="%s"' % r["color"])
        if r.get("tracking") != base.get("tracking"):
            attrs.append('letter_spacing="%d"' % round(r.get("tracking", 0) / 1000.0 * r["size"] * 72.0 / yres * 1024))
        if attrs:
            s = "<span %s>%s</span>" % (" ".join(attrs), s)
        for flag, tag in (("bold", "b"), ("italic", "i"), ("underline", "u"), ("strike", "s")):
            if r.get(flag):
                s = "<%s>%s</%s>" % (tag, s, tag)
        parts.append(s)
    return "<markup>%s</markup>" % "".join(parts)


def ink_bounds(image, layer):
    """Bounds of the layer's opaque pixels, relative to the layer. Selections
    are clipped to the canvas, so the layer is parked at the origin first."""
    layer.set_offsets(0, 0)
    image.select_item(Gimp.ChannelOps.REPLACE, layer)
    try:
        r = Gimp.Selection.bounds(image)
        return (r.x1, r.y1, r.x2, r.y2) if r.non_empty else None
    finally:
        Gimp.Selection.none(image)


def rotate_layer(layer, angle):
    """Rotate about the layer's own centre; multiples of 90 are lossless.
    GIMP keeps the layer a text layer either way, flagged as modified."""
    a = round(angle) % 360
    if abs(angle - round(angle)) < 0.5 and a % 90 == 0:
        if a == 0:
            return layer
        kind = {90: Gimp.RotationType.DEGREES90, 180: Gimp.RotationType.DEGREES180,
                270: Gimp.RotationType.DEGREES270}[a]
        return layer.transform_rotate_simple(kind, True, 0, 0)
    return layer.transform_rotate(math.radians(angle), True, 0, 0)


def is_quarter(angle, target=90):
    return abs(angle - target) < 0.5


def make_text_layer(image, fonts_map, entry, raster, notes, keep_raster=False, contents_dir=None):
    t = entry["text"]
    runs = [r for r in t["runs"] if r["text"]] or t["runs"][:1]
    base = max(runs, key=lambda r: len(r["text"]))
    yres = image.get_resolution().yresolution or 72.0
    fonts, gimp_fonts = {}, {}
    for r in runs:
        if r["font"] not in fonts:
            f, name = find_font(fonts_map, r["font"], notes)
            fonts[r["font"]], gimp_fonts[r["font"]] = name, f
    font = gimp_fonts[base["font"]]
    size = max(1.0, float(base["size"]))
    text = "".join(run_text(r) for r in runs)
    if t.get("orientation") == "vertical":
        notes.add(f'"{entry["name"]}": vertical text became horizontal (set the direction in GIMP\'s text tool)')

    layer = Gimp.TextLayer.new(image, text, font, size, Gimp.Unit.pixel())
    if layer is None:
        raise RuntimeError("TextLayer.new returned NULL (GIMP started without fonts?)")
    image.insert_layer(layer, raster.get_parent(), image.get_item_position(raster))
    layer.set_color(Gegl.Color.new(base["color"]))
    layer.set_antialias(True)
    just = t.get("justification", "left")
    layer.set_justification(Gimp.TextJustification.FILL if just.startswith("justify") else JUSTIFY.get(just, Gimp.TextJustification.LEFT))
    layer.set_letter_spacing(base.get("tracking", 0) / 1000.0 * size)
    natural, _asc = line_height(font, size)
    leading = base["leading"] if base.get("leading") else size * float(t.get("autoLeading") or 1.2)
    if t["shape"] == "box" or "\n" in text:
        layer.set_line_spacing(round(leading - natural, 2))
    if t.get("indent"):
        layer.set_indent(t["indent"])
    lang = ADOBE_TO_GIMP_LANGUAGE.get(base.get("language"))
    if lang:
        layer.set_language(lang)

    def style_key(r):
        return (r["font"], round(r["size"], 2), r["color"], r.get("bold"), r.get("italic"),
                r.get("underline"), r.get("strike"), r.get("tracking"))
    if len({style_key(r) for r in runs}) > 1 or any(base.get(k) for k in ("bold", "italic", "underline", "strike")):
        layer.set_markup(build_markup(runs, base, fonts, yres))

    angle = float(t.get("angle") or 0)
    hscale = float(t.get("hscale") or 1)
    shift = [0, 0]
    # GIMP renders no rotated text layer (a rotated one is flagged as
    # rasterized, and editing it drops the rotation). So:
    #   90 deg clockwise -> GIMP's own vertical text (top to bottom, lines
    #                       right to left): the same picture, still text;
    #   any other angle  -> a straight text layer in an XCF of its own, shown
    #                       by a link layer that is rotated (non-destructive;
    #                       Layer > Smart Object > Edit Contents edits it).
    #   squeezed / stretched (Free Transform with different widths and
    #   heights) -> the same smart object, the link layer scaled: scaling a
    #   text layer would flag it as rasterized too.
    squeeze = abs(hscale - 1) >= 0.02
    vertical = is_quarter(angle, 90) and not squeeze
    tilted = (abs(angle) >= 0.5 and not vertical) or squeeze
    if tilted and not contents_dir:
        notes.add(f'"{entry["name"]}": transformed in Photoshop - kept straight (no folder for its smart object)')
        tilted = False
    layout_angle = 0.0 if (vertical or tilted) else angle

    def squeezed(layer):
        # Photoshop's non-uniform Free Transform: the text was laid out at full
        # height in a wider box, the finished layer is squeezed to its real
        # width. Like a rotation, GIMP keeps it a text layer flagged as modified.
        if abs(hscale - 1) < 0.02 or tilted:
            return layer                                     # tilted: the link layer is scaled
        notes.add(f'"{entry["name"]}": width scaled to {hscale * 100:.0f}% like in Photoshop - editing the text in GIMP '
                  f're-renders it at full width (Scale tool, width x{hscale:.2f}, to redo it)')
        layer.scale(max(1, round(layer.get_width() * hscale)), layer.get_height(), True)
        return layer

    if t["shape"] == "box":
        w, h = max(1, round(t["box"]["w"])), max(1, round(t["box"]["h"]))
        bw = max(1, round(w / hscale))
        layer.resize(bw, h)                                  # = fixed box: GIMP wraps the text inside it
        # GIMP clips what does not fit the box, and it can need a line more than
        # Photoshop did (no hyphenation, other metrics): measure the text in a
        # much taller box and, if it runs past the bottom, keep a box that fits.
        # Only for a box Photoshop really rendered (its layer has pixels) and only
        # for a line or two: a placeholder that overflows its balloon-sized box
        # overflows in Photoshop as well, and that box is the balloon - keep it.
        rendered = entry["bbox"][2] > entry["bbox"][0] and entry["bbox"][3] > entry["bbox"][1]
        if abs(layout_angle) < 0.5 and rendered:
            tall = min(max(h * 4, h + 8 * round(size)), max(h, image.get_height()))
            layer.resize(bw, tall)
            ink = ink_bounds(image, layer)
            need = (ink[3] + round(size * 0.25)) if ink else 0
            if h < need <= h + 2.5 * max(natural, leading) + size * 0.25:
                notes.add(f'"{entry["name"]}": the text needs more room in GIMP than in Photoshop - '
                          f'box made {need - h}px taller so the last line is not clipped')
                layer.resize(bw, need)
            else:
                layer.resize(bw, h)
        layer = squeezed(layer)
        if vertical:
            # the box turns with the text: Photoshop's w x h box is h x w on the page
            layer.set_base_direction(Gimp.TextDirection.TTB_RTL)
            layer.resize(layer.get_height(), layer.get_width())
            w, h = h, w
        # centred on the box: a squeezed box is still full width here when the
        # squeeze goes to its smart object (tilted), not to this layer
        layer.set_offsets(round(t["box"]["cx"] - layer.get_width() / 2), round(t["box"]["cy"] - h / 2))
        layer = rotate_layer(layer, layout_angle)
        # Same box, but GIMP starts the first line lower than Photoshop (the two
        # read a font's ascent differently, 5-15 px on comic fonts): nudge the box
        # so the INK sits where Photoshop drew it. Only when both renderings are
        # clearly the same lines (similar ink size) or, unrotated, by the top edge;
        # the nudge is remembered so the way back to PSD restores the real box.
        l, tp, r, b = entry["bbox"]
        ox, oy = layer.get_offsets()[1:]
        ink = ink_bounds(image, layer)                       # parks the layer at 0,0
        if ink and r > l and b > tp:
            iw, ih = ink[2] - ink[0], ink[3] - ink[1]
            same_w, same_h = abs(iw - (r - l)) <= 0.12 * (r - l), abs(ih - (b - tp)) <= 0.12 * (b - tp)
            dx = (l + r) / 2 - (ox + (ink[0] + ink[2]) / 2) if same_w else 0
            if same_h:
                dy = (tp + b) / 2 - (oy + (ink[1] + ink[3]) / 2)
            else:
                dy = tp - (oy + ink[1]) if abs(layout_angle) < 0.5 else 0
            limit = 0.6 * size
            if abs(dx) <= limit and abs(dy) <= limit:
                shift = [round(dx), round(dy)]
        layer.set_offsets(ox + shift[0], oy + shift[1])
    else:
        layer = squeezed(layer)
        if vertical:
            layer.set_base_direction(Gimp.TextDirection.TTB_RTL)
        layer = rotate_layer(layer, layout_angle)
        # point text: GIMP and Photoshop measure lines differently, so put the
        # INK of the new layer where the ink of Photoshop's rendering is
        l, tp, r, b = entry["bbox"]
        ink = ink_bounds(image, layer)
        if ink and r > l and b > tp:
            layer.set_offsets(round((l + r) / 2 - (ink[0] + ink[2]) / 2),
                              round((tp + b) / 2 - (ink[1] + ink[3]) / 2))
        else:
            layer.set_offsets(l, tp)

    own = {"angle": angle if not tilted else 0.0, "hscale": hscale, "shift": shift, "shape": t["shape"],
           "justification": just, "fonts": {fonts[k]: k for k in fonts}}
    if vertical:
        own["angle"] = 0.0
        own["vertical"] = True
    if tilted:
        own["hscale"] = 1
        set_parasite_json(layer, own)
        layer = text_smart_object(image, layer, angle, hscale if squeeze else 1.0, entry, contents_dir, notes)
        own = {"text_contents": True, "angle": angle, "hscale": hscale if squeeze else 1.0, "shape": t["shape"]}

    name = raster.get_name()
    raster.set_name(name + " (Photoshop render)")
    layer.set_name(name)
    layer.set_opacity(raster.get_opacity())
    layer.set_mode(raster.get_mode())
    layer.set_visible(raster.get_visible())
    layer.set_color_tag(raster.get_color_tag())
    if raster.get_mask() is not None:
        notes.add(f'"{entry["name"]}": the layer mask of this text layer was not carried over')
    set_parasite_json(layer, own)
    if keep_raster:
        raster.set_visible(False)
    else:
        image.remove_layer(raster)
    return layer


def unique_contents_path(folder, name):
    base = os.path.join(folder, re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .")[:80] or "Text")
    path, n = base + ".xcf", 2
    while os.path.exists(path):
        path, n = "%s %d.xcf" % (base, n), n + 1
    return path


def text_smart_object(image, text_layer, angle, hscale, entry, folder, notes):
    """Move a straight text layer into an XCF of its own and put in its place
    a link layer showing that XCF, its width scaled by hscale and rotated by
    angle about the same centre. The text stays editable (Layer > Smart
    Object > Edit Contents) and the transform stays non-destructive."""
    _ok, ox, oy = text_layer.get_offsets()
    w, h = text_layer.get_width(), text_layer.get_height()
    cx, cy = ox + w / 2.0, oy + h / 2.0
    os.makedirs(folder, exist_ok=True)
    path = unique_contents_path(folder, entry["name"])
    contents = Gimp.Image.new_with_precision(w, h, image.get_base_type(), image.get_precision())
    try:
        res = image.get_resolution()
        contents.set_resolution(res.xresolution, res.yresolution)
        contents.undo_disable()
        copy = Gimp.Layer.new_from_drawable(text_layer, contents)
        contents.insert_layer(copy, None, 0)
        copy.set_offsets(0, 0)
        copy.set_name(entry["name"])
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, contents, Gio.File.new_for_path(path), None)
    finally:
        contents.delete()
    link = Gimp.LinkLayer.new(image, Gio.File.new_for_path(path))
    if link is None:
        raise RuntimeError("GIMP could not create a link layer for " + path)
    image.insert_layer(link, text_layer.get_parent(), image.get_item_position(text_layer))
    image.remove_layer(text_layer)
    link.set_offsets(round(cx - w / 2.0), round(cy - h / 2.0))
    if abs(hscale - 1) >= 0.02:
        link.scale(max(1, round(w * hscale)), h, True)
    if abs(angle) >= 0.5:
        link = link.transform_rotate(math.radians(angle), True, 0, 0)
    # keep the centre where the straight text had it
    _ok, nx, ny = link.get_offsets()
    link.set_offsets(round(cx - link.get_width() / 2.0), round(cy - link.get_height() / 2.0))
    how = " and ".join(x for x in (f"rotated {angle:g} deg" if abs(angle) >= 0.5 else "",
                                   f"width {hscale * 100:.0f}%" if abs(hscale - 1) >= 0.02 else "") if x)
    # "info:" notes are not shown in GIMP: nothing was lost
    notes.add(f'info: "{entry["name"]}": {how} in Photoshop - a smart object; edit its text with '
              f'Layer > Smart Object > Edit Contents, then save (Ctrl+S)')
    return link


def add_styles_filter(layer, fx, notes, name):
    f = Gimp.DrawableFilter.new(layer, "gegl:styles", "Text Styling")
    cfg = f.get_config()
    s = fx.get("stroke")
    if s:
        grow = s["size"] if s["position"] == "outside" else s["size"] / 2.0
        if s["position"] != "outside":
            notes.add(f'"{name}": stroke position "{s["position"]}" drawn as an outside outline of {grow:g}px')
        cfg.set_property("enableoutline", True)
        cfg.set_property("outline", float(grow))
        cfg.set_property("outline-color", Gegl.Color.new(s["color"]))
        cfg.set_property("outline-opacity", float(s.get("opacity", 1)))
    sh = fx.get("shadow")
    if sh:
        cfg.set_property("shadow-opacity", float(sh["opacity"]))
        cfg.set_property("shadow-x", float(sh["x"]))
        cfg.set_property("shadow-y", float(sh["y"]))
        cfg.set_property("shadow-color", Gegl.Color.new(sh["color"]))
        cfg.set_property("shadow-radius", float(sh["blur"]) / 2.0)       # Photoshop size ~ 2 x gaussian std-dev
        cfg.set_property("shadow-grow-radius", min(100.0, float(sh.get("grow", 0))))
    fill = fx.get("fill")
    if fill:
        cfg.set_property("color-fill", Gegl.Color.new(fill["color"]))
        cfg.set_property("color-policy", "multiply" if fill["blend"] == "multiply" else "solidcolor")
    f.update()
    layer.append_filter(f)


def apply_psd_text(image, info, fonts_map, notes, keep_raster=False, contents_dir=None):
    """Swap GIMP's rasterized Type layers for text layers and add the Text
    Styling filters. Returns (text layers made, filters added)."""
    by_path = dict(walk(image.get_layers()))
    by_name = {}
    for _p, l in by_path.items():
        by_name.setdefault(l.get_name().strip(), []).append(l)
    targets = []
    for e in info["layers"]:
        l = by_path.get(tuple(e["path"]))
        want = e["name"].strip()
        if l is None or (l.get_name().strip() != want and not l.get_name().startswith(want)):
            cands = by_name.get(want, [])
            l = cands[0] if len(cands) == 1 else None
        if l is None:
            notes.add(f'"{e["name"]}": layer not found in GIMP\'s copy of the PSD, left as loaded')
            continue
        targets.append((e, l))
    n_text = n_fx = 0
    for e, l in targets:
        try:
            if e.get("text") and not l.is_group():
                l = make_text_layer(image, fonts_map, e, l, notes, keep_raster, contents_dir)
                n_text += 1
            fx = e.get("effects") or {}
            for n in fx.get("notes", []):
                notes.add(f'"{e["name"]}": {n}')
            if LS is not None and fx.get("style"):
                LS.apply_style(l, fx["style"])
                n_fx += 1
            elif fx.get("stroke") or fx.get("shadow") or fx.get("fill"):
                add_styles_filter(l, fx, notes, e["name"])
                n_fx += 1
        except Exception:
            notes.add(f'"{e["name"]}": conversion failed, layer left as GIMP loaded it ({traceback.format_exc().splitlines()[-1]})')
    return n_text, n_fx


# --------------------------------------------------------------- XCF -> PSD

def text_parasite(layer):
    raw = parasite_text(layer, "gimp-text-layer")
    out = {}
    for key in ("box-mode", "box-width", "box-height", "psname", "fullname", "family", "style"):
        m = re.search(r'\(%s\s+"?([^")]*)"?\)' % re.escape(key), raw)
        if m:
            out[key] = m.group(1)
    return out


def parse_markup(markup, base):
    """GIMP/Pango markup -> flat runs; every run carries the full style."""
    runs = []

    def emit(text, st):
        if text:
            runs.append({**st, "text": text})

    def rec(node, st):
        st = dict(st)
        tag = node.tag
        if tag == "b":
            st["bold"] = True
        elif tag == "i":
            st["italic"] = True
        elif tag == "u":
            st["underline"] = True
        elif tag == "s":
            st["strike"] = True
        elif tag == "span":
            a = node.attrib
            if a.get("font") or a.get("font_desc") or a.get("face") or a.get("font_family"):
                st["gimp_font"] = a.get("font") or a.get("font_desc") or a.get("face") or a.get("font_family")
                st["psname"] = None
            if a.get("size") and a["size"].lstrip("-").isdigit():
                st["size"] = int(a["size"]) / 1024.0 * base["yres"] / 72.0
            for k in ("foreground", "color", "fgcolor"):
                if a.get(k, "").startswith("#") and len(a[k]) >= 7:
                    st["color"] = a[k][:7].lower()
            if a.get("letter_spacing", "").lstrip("-").isdigit():
                st["letter_spacing"] = int(a["letter_spacing"]) / 1024.0 * base["yres"] / 72.0
            if a.get("weight") in ("bold", "ultrabold", "heavy") or a.get("font_weight") == "bold":
                st["bold"] = True
            if a.get("style") in ("italic", "oblique") or a.get("font_style") in ("italic", "oblique"):
                st["italic"] = True
        emit(node.text, st)
        for child in node:
            rec(child, st)
            emit(child.tail, st)

    style = {k: v for k, v in base.items() if k != "yres"}
    try:
        rec(ET.fromstring(markup), style)
    except ET.ParseError:
        return None
    return runs


def overlap_area(image, a, b):
    """Pixels where both layers are opaque (mean of the intersected selection x area)."""
    image.select_item(Gimp.ChannelOps.REPLACE, a)
    image.select_item(Gimp.ChannelOps.INTERSECT, b)
    try:
        sel = image.get_selection()
        h = sel.histogram(Gimp.HistogramChannel.VALUE, 0.0, 1.0)
        return h.mean * h.pixels
    finally:
        Gimp.Selection.none(image)


def guess_rotation(image, layer, font, size, nat_w, nat_h):
    """A text layer rotated in GIMP does not remember its angle. Sizes tell a
    quarter turn from an untouched layer; which quarter is decided by
    rendering both and keeping the one that overlaps the real pixels."""
    w, h = layer.get_width(), layer.get_height()
    tol = max(4, 0.04 * max(nat_w, nat_h))
    if abs(w - nat_w) <= tol and abs(h - nat_h) <= tol:
        return 0
    if not (abs(w - nat_h) <= tol and abs(h - nat_w) <= tol):
        return None                                           # scaled / sheared / free rotation
    best = (-1, None)
    for angle, kind in ((90, Gimp.RotationType.DEGREES90), (-90, Gimp.RotationType.DEGREES270)):
        # render the same text again, turn THAT, lay it over the real layer
        fresh = Gimp.TextLayer.new(image, layer.get_text() or "x", font, size, Gimp.Unit.pixel())
        image.insert_layer(fresh, None, 0)
        try:
            if layer.get_markup():
                fresh.set_markup(layer.get_markup())
            fresh.set_justification(layer.get_justification())
            fresh.set_line_spacing(layer.get_line_spacing())
            fresh.set_letter_spacing(layer.get_letter_spacing())
            if abs(fresh.get_width() - h) > tol or abs(fresh.get_height() - w) > tol:
                fresh.resize(h, w)                            # fixed box: same box before the turn
            fresh = fresh.transform_rotate_simple(kind, True, 0, 0)
            fresh.set_offsets(*layer.get_offsets()[1:])
            score = overlap_area(image, layer, fresh)
        finally:
            image.remove_layer(fresh)
        if score > best[0]:
            best = (score, angle)
    return best[1]


def describe_text(image, layer, notes):
    name = layer.get_name()
    par = text_parasite(layer)
    ours = get_parasite_json(layer)
    yres = image.get_resolution().yresolution or 72.0
    font = layer.get_font()
    size, unit = layer.get_font_size()
    if unit.get_id() != Gimp.Unit.pixel().get_id() and unit.get_factor() > 0:
        size = size * yres / unit.get_factor()
    markup = layer.get_markup()
    text = layer.get_text()
    base = {"gimp_font": font.get_name(), "psname": par.get("psname") or None, "size": size,
            "color": color_hex(layer.get_color()), "bold": False, "italic": False, "underline": False,
            "strike": False, "letter_spacing": layer.get_letter_spacing(), "yres": yres}
    runs = parse_markup(markup, base) if markup else None
    if runs is None:
        if markup:
            text = re.sub(r"<[^>]+>", "", markup)
            notes.add(f'"{name}": markup could not be parsed, mixed styles dropped')
        b = {k: v for k, v in base.items() if k != "yres"}
        runs = [{**b, "text": text or ""}]
    plain = "".join(r["text"] for r in runs)

    ok, nat_w, nat_h, ascent, _d = Gimp.text_get_extents_font(plain or "x", size, font)
    natural, _a = line_height(font, size)
    fixed = par.get("box-mode") == "fixed"
    # GIMP writes the gimp-text-layer parasite only when the image is saved
    # and reloaded: a layer made in this session (by apply_psd_text, or a
    # box drawn with the Text tool) has none, so the box mode comes from
    # our own parasite or from a size that is not the text's natural one
    in_session = "box-mode" not in par
    if in_session and ours.get("shape") == "box":
        fixed = True
        nat_w, nat_h = layer.get_width(), layer.get_height()
        if is_quarter(abs(float(ours.get("angle") or 0)) % 180):
            nat_w, nat_h = nat_h, nat_w                          # a layer turned a quarter
        nat_w /= float(ours.get("hscale") or 1)
    elif fixed:
        nat_w, nat_h = float(par.get("box-width", layer.get_width())), float(par.get("box-height", layer.get_height()))
    else:
        # extents ignore markup and spacing: measure a real dynamic twin instead
        twin = Gimp.TextLayer.new(image, plain or "x", font, size, Gimp.Unit.pixel())
        image.insert_layer(twin, None, 0)
        if markup:
            twin.set_markup(markup)
        twin.set_line_spacing(layer.get_line_spacing())
        twin.set_letter_spacing(layer.get_letter_spacing())
        nat_w, nat_h = twin.get_width(), twin.get_height()
        image.remove_layer(twin)
        w, h = layer.get_width(), layer.get_height()
        tol = max(4, 0.04 * max(nat_w, nat_h))
        natural_size = abs(w - nat_w) <= tol and abs(h - nat_h) <= tol
        quarter_turned = abs(w - nat_h) <= tol and abs(h - nat_w) <= tol
        if in_session and "angle" not in ours and not natural_size and not quarter_turned:
            fixed, nat_w, nat_h = True, w, h                     # a Text tool box drawn in this session

    if "angle" in ours:
        angle = float(ours["angle"])
    else:
        angle = guess_rotation(image, layer, font, size, nat_w, nat_h)
        if angle is None:
            notes.add(f'"{name}": text layer was transformed in GIMP (scaled or freely rotated) - kept as pixels, not editable text')
            return None
    ox, oy = layer.get_offsets()[1:]
    w, h = layer.get_width(), layer.get_height()
    cx, cy = ox + w / 2.0, oy + h / 2.0
    if fixed and ours.get("shift"):
        cx, cy = cx - ours["shift"][0], cy - ours["shift"][1]    # the PSD->XCF ink nudge, see make_text_layer
    quarter = abs(round(angle)) % 180 == 90 and abs(angle - round(angle)) < 0.5
    if fixed or "angle" not in ours:
        bw, bh = (h, w) if quarter else (w, h)
        if "angle" in ours and not quarter and abs(angle) > 0.5:
            bw, bh = nat_w, nat_h                                # free rotation: layer bounds grew, box did not
    else:
        bw, bh = nat_w, nat_h
    hscale = float(ours.get("hscale") or 1)
    if abs(hscale - 1) >= 0.02:
        bw, bh = nat_w * hscale, nat_h                           # the text's own box, squeezed like the layer was

    info = {
        "hscale": hscale,
        "shape": "box" if fixed else "point",
        "angle": angle,
        "box": {"w": bw, "h": bh, "cx": cx, "cy": cy},           # unrotated size + page centre, both shapes
        "ascent": ascent * (max(r["size"] for r in runs) / size if size else 1),
        "justification": ours.get("justification") if ours.get("justification", "").startswith("justify")
        else JUSTIFY_BACK.get(int(layer.get_justification()), "left"),
        "baseSize": size,
        "leading": natural + layer.get_line_spacing(),
        "indent": layer.get_indent(),
        "runs": runs,
        "font_back": ours.get("fonts") or {},                    # GIMP name -> original Photoshop name
    }
    outline = layer.get_outline()
    if outline != Gimp.TextOutline.NONE:
        ow = layer.get_outline_width()                       # (width, unit) in GIMP 3.2, a float before
        if isinstance(ow, tuple):
            ow = ow[0] * (yres / ow[1].get_factor() if ow[1].get_factor() > 0 else 1)
        nick = getattr(layer.get_outline_direction(), "value_nick", "")
        info["outline"] = {"width": ow, "color": color_hex(layer.get_outline_color()),
                           "position": {"outer": "outside", "inner": "inside"}.get(nick, "center"),
                           "only": outline == Gimp.TextOutline.STROKE_ONLY}
    return info


def describe_filters(layer, notes):
    """gegl:styles / gegl:dropshadow -> Layer Style numbers. Returns (effects, filters to hide)."""
    fx, hide = {}, []
    name = layer.get_name()
    style = LS.read_style(layer) if LS is not None else {}
    if any(s.get("enabled") for s in style.values()):
        # a Layer Style: Photoshop gets the very settings it was made with
        fx["style"] = style
    for f in layer.get_filters():
        op = f.get_operation_name()
        if not f.get_visible():
            continue
        if LS is not None and f.get_name().startswith(LS.PREFIX):
            if fx.get("style"):
                hide.append(f)
            continue
        if op not in STYLE_OPS:
            notes.add(f'"{name}": filter {op} has no Layer Style equivalent, it was merged into the pixels')
            continue
        c = f.get_config()
        g = c.get_property
        used = False
        if op == "gegl:styles":
            if g("enableoutline") and "stroke" not in fx:
                fx["stroke"] = {"size": g("outline"), "color": color_hex(g("outline-color")),
                                "opacity": g("outline-opacity") * f.get_opacity(), "position": "outside"}
                used = True
                if abs(g("outline-x")) > 0.5 or abs(g("outline-y")) > 0.5:
                    notes.add(f'"{name}": outline offset ({g("outline-x"):g}, {g("outline-y"):g}) has no Layer Style equivalent, stroke is centred')
            if g("shadow-opacity") > 0 and "shadow" not in fx:
                fx["shadow"] = {"x": g("shadow-x"), "y": g("shadow-y"), "color": color_hex(g("shadow-color")),
                                "opacity": g("shadow-opacity") * f.get_opacity(), "blur": g("shadow-radius") * 2.0,
                                "grow": g("shadow-grow-radius")}
                used = True
            fill = color_hex(g("color-fill"))
            if g("color-policy") == "solidcolor" or (g("color-policy") == "multiply" and fill != "#ffffff"):
                fx["fill"] = {"color": fill, "blend": "multiply" if g("color-policy") == "multiply" else "normal"}
                used = True
            for flag, label in (("enablebevel", "bevel"), ("enableinnerglow", "inner glow"), ("enableimage", "image overlay")):
                if g(flag):
                    notes.add(f'"{name}": Text Styling {label} not converted')
        elif "shadow" not in fx:
            fx["shadow"] = {"x": g("x"), "y": g("y"), "color": color_hex(g("color")),
                            "opacity": min(1.0, g("opacity")) * f.get_opacity(), "blur": g("radius") * 2.0,
                            "grow": g("grow-radius")}
            used = True
        if used:
            hide.append(f)
    if fx.get("style"):
        # the Layer Style is what goes to Photoshop: any other outline/shadow
        # filter stays drawn into the pixels instead of being dropped
        for k in ("stroke", "shadow", "fill"):
            if fx.pop(k, None) is not None:
                notes.add(f'"{name}": a filter besides its Layer Style was merged into the pixels')
        hide = [f for f in hide if f.get_name().startswith(LS.PREFIX)]
    return fx, hide


def is_vertical(layer):
    return layer.get_base_direction() == Gimp.TextDirection.TTB_RTL


def describe_vertical(image, layer, notes):
    """A vertical (top to bottom, lines right to left) text layer is
    Photoshop's horizontal text turned 90 deg clockwise: describe a straight
    twin of it, turned a quarter, as such a Type layer."""
    ours = get_parasite_json(layer)
    par = text_parasite(layer)
    font = layer.get_font()
    size, unit = layer.get_font_size()
    w, h = layer.get_width(), layer.get_height()
    _ok, ox, oy = layer.get_offsets()
    twin = Gimp.TextLayer.new(image, layer.get_text() or "x", font, size, unit)
    image.insert_layer(twin, None, 0)
    try:
        if layer.get_markup():
            twin.set_markup(layer.get_markup())
        twin.set_color(layer.get_color())
        twin.set_justification(layer.get_justification())
        twin.set_line_spacing(layer.get_line_spacing())
        twin.set_letter_spacing(layer.get_letter_spacing())
        twin.set_indent(layer.get_indent())
        if layer.get_language():
            twin.set_language(layer.get_language())
        if par.get("box-mode"):
            fixed = par["box-mode"] == "fixed"
        elif "shape" in ours:
            fixed = ours["shape"] == "box"
        else:
            # drawn in this session: a box when its size is not the natural one
            probe = Gimp.TextLayer.new(image, "x", font, size, unit)
            image.insert_layer(probe, None, 0)
            try:
                if layer.get_markup():
                    probe.set_markup(layer.get_markup())
                else:
                    probe.set_text(layer.get_text() or "x")
                probe.set_base_direction(Gimp.TextDirection.TTB_RTL)
                probe.set_line_spacing(layer.get_line_spacing())
                probe.set_letter_spacing(layer.get_letter_spacing())
                tol = max(4, 0.04 * max(w, h))
                fixed = abs(probe.get_width() - w) > tol or abs(probe.get_height() - h) > tol
            finally:
                image.remove_layer(probe)
        if fixed:
            twin.resize(h, w)
        twin = twin.transform_rotate_simple(Gimp.RotationType.DEGREES90, True, 0, 0)
        twin.set_offsets(round(ox + (w - twin.get_width()) / 2.0), round(oy + (h - twin.get_height()) / 2.0))
        own = {k: v for k, v in ours.items() if k != "vertical"}
        own.update({"angle": 90.0, "shape": "box" if fixed else "point", "hscale": 1, "shift": [0, 0]})
        set_parasite_json(twin, own)
        return describe_text(image, twin, notes)
    finally:
        image.remove_layer(twin)


def describe_link_text(image, link, notes):
    """A rotated text smart object (see text_smart_object): the straight
    text in its XCF, rotated like the link layer, around the same centre."""
    ours = get_parasite_json(link)
    name = link.get_name()
    f = link.get_file()
    if link.is_rasterized() or f is None or not f.query_exists(None):
        notes.add(f'"{name}": its smart object file is missing or was rasterized - exported as pixels')
        return None
    contents = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, f)
    try:
        texts = [l for _p, l in walk(contents.get_layers()) if isinstance(l, Gimp.TextLayer)]
        if len(texts) != 1:
            notes.add(f'"{name}": its smart object holds {len(texts)} text layers - exported as pixels')
            return None
        inner = texts[0]
        info = describe_vertical(contents, inner, notes) if is_vertical(inner) else describe_text(contents, inner, notes)
        if not info:
            return None
        info["language_tag"] = inner.get_language() or ""
        cw, ch = contents.get_width(), contents.get_height()
    finally:
        contents.delete()
    angle = float(ours.get("angle") or 0)
    hscale = float(ours.get("hscale") or 1)
    rad = math.radians(angle)
    # the text's centre inside the contents, scaled and turned with the link layer
    vx, vy = (info["box"]["cx"] - cw / 2.0) * hscale, info["box"]["cy"] - ch / 2.0
    if abs(hscale - 1) >= 0.02:
        info["box"]["w"] *= hscale
        info["hscale"] = hscale
    _ok, ox, oy = link.get_offsets()
    info["box"]["cx"] = ox + link.get_width() / 2.0 + vx * math.cos(rad) - vy * math.sin(rad)
    info["box"]["cy"] = oy + link.get_height() / 2.0 + vx * math.sin(rad) + vy * math.cos(rad)
    info["angle"] = angle + float(info.get("angle") or 0)
    return info


def describe_image(image, notes, default_language):
    """Text layers + Text Styling filters of image, for write_psd_text.mjs.
    Returns (entries, filters that Photoshop will redraw as Layer Styles)."""
    entries, to_hide = [], []
    for path, l in list(walk(image.get_layers())):
        text = None
        if isinstance(l, Gimp.TextLayer):
            text = describe_vertical(image, l, notes) if is_vertical(l) else describe_text(image, l, notes)
            if text:
                text["language"] = adobe_language(l, default_language)
        elif isinstance(l, Gimp.LinkLayer) and get_parasite_json(l).get("text_contents"):
            text = describe_link_text(image, l, notes)
            if text:
                tag = text.pop("language_tag", "").lower().replace("_", "-")
                text["language"] = GIMP_TO_ADOBE_LANGUAGE.get(tag, default_language)
        fx, hide = describe_filters(l, notes)
        if text and text.get("outline"):
            o = text.pop("outline")
            if "stroke" in fx:
                notes.add(f'"{l.get_name()}": has both a text outline and a Text Styling outline, the filter one was kept')
            else:
                # GIMP draws its own text outline into the pixels; Photoshop redraws it as a Stroke
                fx["stroke"] = {"size": o["width"], "color": o["color"], "opacity": 1.0, "position": o["position"]}
                if o["only"]:
                    fx["fill_opacity"] = 0.0
        if text or fx:
            entries.append({"path": list(path), "name": l.get_name(), "text": text, "effects": fx or None})
            to_hide += hide
    return entries, to_hide
