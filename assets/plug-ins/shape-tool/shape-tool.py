#!/usr/bin/env python3
#
# Shape Tool: Photoshop's shape tools (U) for GIMP 3.2 - Rectangle,
# Ellipse, Triangle, Polygon, Line and Custom Shape - as vector layers.
#
#   Tools > Shape Tool... (also Layer > New Shape Layer..., shortcut U)
#
# Draw a rectangle selection where the shape goes (M, then drag, like
# dragging with Photoshop's shape tool) and press U: the dialog shows the
# shape live in that box. Without a selection the shape is centred in the
# image. The result is a vector layer: crisp at any size, its fill and
# stroke still editable, its points editable with the Path tool. With a
# shape layer selected, U edits that shape instead (type, colours, stroke,
# corner radius...).
#
# Geometry: shape_geometry.py next to this file.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import json
import os
import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gegl', '0.4')
gi.require_version('Gtk', '3.0')
gi.require_version('Babl', '0.1')
from gi.repository import Gimp, GimpUi, Gegl, GLib, Gtk, Gdk, Babl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shape_geometry as G  # noqa: E402

PROC = "shape-tool"
PARASITE = "gimp-setup-shape"
GEOMETRY_KEYS = ("shape", "radius", "sides", "star", "indent", "line_direction", "custom")
LAST = os.path.join(GLib.get_user_config_dir(), "PhotoGIMP", "shape-tool.json")


def hex_of(color):
    b = color.get_bytes(Babl.format("R'G'B'A u8")).get_data()
    return "#%02x%02x%02x" % (b[0], b[1], b[2])


def rgba(value):
    c = Gdk.RGBA()
    c.parse(value)
    return c


def rgba_hex(c):
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in (c.red, c.green, c.blue))


def read_json(item, name):
    try:
        if name in item.get_parasite_list():
            return json.loads(bytes(b & 0xFF for b in item.get_parasite(name).get_data()).decode())
    except (ValueError, UnicodeDecodeError):
        pass
    return None


def load_last():
    try:
        with open(LAST) as f:
            return {k: v for k, v in json.load(f).items() if k in G.DEFAULTS}
    except (OSError, ValueError):
        return {}


def save_last(settings):
    try:
        os.makedirs(os.path.dirname(LAST), exist_ok=True)
        with open(LAST, "w") as f:
            json.dump(settings, f)
    except OSError:
        pass


def fill_path(path, geometry):
    for stroke in path.get_strokes():
        path.remove_stroke(stroke)
    if geometry[0] == "ellipse":
        path.bezier_stroke_new_ellipse(geometry[1], geometry[2], geometry[3], geometry[4], 0.0)
        return
    for closed, anchors in geometry:
        points = [v for anchor in anchors for p in anchor for v in p]
        path.stroke_new_from_points(Gimp.PathStrokeType.BEZIER, points, closed)


def style_layer(layer, s):
    closed = G.is_closed(s)
    layer.set_enable_fill(bool(s["fill"]) and closed)
    layer.set_fill_color(Gegl.Color.new(s["fill_color"]))
    # a line is drawn by its stroke only, as in Photoshop
    stroke = bool(s["stroke"]) or not closed
    layer.set_enable_stroke(stroke)
    layer.set_stroke_color(Gegl.Color.new(s["stroke_color"] if s["stroke"] else s["fill_color"]))
    layer.set_stroke_width(float(max(1, s["stroke_width"])))
    layer.set_stroke_join_style(Gimp.JoinStyle.MITER)
    layer.refresh()


def draw_icon(cr, settings, size):
    geometry = G.build(settings, (3, 3, size - 6, size - 6))
    if geometry[0] == "ellipse":
        _e, cx, cy, rx, ry = geometry
        cr.save()
        cr.translate(cx, cy)
        cr.scale(rx, ry)
        cr.arc(0, 0, 1, 0, 6.2832)
        cr.restore()
    else:
        for closed, anchors in geometry:
            cr.move_to(*anchors[0][1])
            for prev, cur in zip(anchors, anchors[1:] + (anchors[:1] if closed else [])):
                cr.curve_to(*prev[2], *cur[0], *cur[1])
            if closed:
                cr.close_path()


class Icon(Gtk.DrawingArea):
    def __init__(self, settings, size=26):
        super().__init__()
        self.settings, self.size = settings, size
        self.set_size_request(size, size)
        self.connect("draw", self._draw)

    def _draw(self, widget, cr):
        fg = widget.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.95)
        cr.set_line_width(1.6)
        draw_icon(cr, self.settings, self.size)
        if G.is_closed(self.settings):
            cr.fill_preserve()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.4)
        cr.stroke()
        return False


class ShapeDialog:
    def __init__(self, image, editing=None):
        self.image = image
        self.pending = None
        self.editing = editing
        if editing is not None:
            data = read_json(editing, PARASITE) or {}
            self.settings = {**G.DEFAULTS, **data.get("settings", {})}
            _ok, ox, oy = editing.get_offsets()
            bx, by, bw, bh = data.get("box", (ox, oy, editing.get_width(), editing.get_height()))
            dx, dy = ox - data.get("offsets", (ox, oy))[0], oy - data.get("offsets", (ox, oy))[1]
            self.box = (bx + dx, by + dy, bw, bh)
            self.original = dict(self.settings)
        else:
            fg = hex_of(Gimp.context_get_foreground())
            self.settings = {**G.DEFAULTS, "fill_color": fg, **load_last()}
            ok, non_empty, x1, y1, x2, y2 = Gimp.Selection.bounds(image)
            if non_empty and x2 - x1 > 1 and y2 - y1 > 1:
                self.box = (x1, y1, x2 - x1, y2 - y1)
            else:
                w, h = image.get_width(), image.get_height()
                side = min(w, h) * 0.5
                self.box = ((w - side) / 2.0, (h - side) / 2.0, side, side)
        self.geometry_dirty = editing is None

        self.dialog = GimpUi.Dialog(title="Shape Tool", role="gimp-setup-shape-tool")
        self.dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.dialog.add_button("_OK", Gtk.ResponseType.OK)
        self.dialog.set_default_response(Gtk.ResponseType.OK)
        body = Gtk.Box(spacing=14)
        body.set_border_width(12)
        self.dialog.get_content_area().pack_start(body, True, True, 0)

        # left: Photoshop's shape tool flyout
        tools = Gtk.ListBox()
        tools.set_size_request(210, -1)
        for key, label in G.SHAPES:
            row = Gtk.ListBoxRow()
            row.key = key
            box = Gtk.Box(spacing=10)
            box.set_border_width(5)
            sample = {"shape": key, "custom": "heart", "sides": 6}
            box.pack_start(Icon(sample), False, False, 0)
            box.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            box.pack_start(Gtk.Label(label="U"), False, False, 4)
            row.add(box)
            tools.add(row)
            if key == self.settings["shape"]:
                tools.select_row(row)
        tools.connect("row-selected", self._tool_selected)
        frame = Gtk.Frame()
        frame.add(tools)
        body.pack_start(frame, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.pack_start(right, True, True, 0)
        self.stack = Gtk.Stack()
        right.pack_start(self.stack, False, False, 0)
        self.stack.add_named(self._rect_page(), "rectangle")
        for key in ("ellipse", "triangle"):
            self.stack.add_named(Gtk.Label(label="", xalign=0), key)
        self.stack.add_named(self._polygon_page(), "polygon")
        self.stack.add_named(self._line_page(), "line")
        self.stack.add_named(self._custom_page(), "custom")
        right.pack_start(Gtk.Separator(), False, False, 2)
        right.pack_start(self._paint_grid(), False, False, 0)
        hint = Gtk.Label(xalign=0)
        hint.set_line_wrap(True)
        hint.set_max_width_chars(46)
        hint.set_markup("<small>%s</small>" % GLib.markup_escape_text(
            "Editing this shape layer. Its points can also be moved with the Path tool (B)."
            if editing is not None else
            "The shape fills the selection (draw one with the Rectangle Select tool, M, "
            "then press U), or the middle of the image without one."))
        right.pack_start(hint, False, False, 6)

        self.dialog.show_all()
        self.stack.set_visible_child_name(self.settings["shape"])
        self._start_preview()

    # ---------------------------------------------------------------- pages

    def _grid(self):
        g = Gtk.Grid(column_spacing=10, row_spacing=8)
        g.row = 0
        return g

    def _row(self, grid, label, widget):
        grid.attach(Gtk.Label(label=label + ":" if label else "", xalign=1), 0, grid.row, 1, 1)
        grid.attach(widget, 1, grid.row, 1, 1)
        grid.row += 1

    def _spin(self, key, lo, hi):
        adj = Gtk.Adjustment(value=float(self.settings[key]), lower=lo, upper=hi, step_increment=1, page_increment=10)
        spin = Gtk.SpinButton(adjustment=adj, digits=0)
        adj.connect("value-changed", lambda a: self._set(key, int(a.get_value())))
        return spin

    def _rect_page(self):
        g = self._grid()
        self._row(g, "Corner radius", self._spin("radius", 0, 2000))
        return g

    def _polygon_page(self):
        g = self._grid()
        self._row(g, "Sides", self._spin("sides", 3, 100))
        star = Gtk.CheckButton(label="Star")
        star.set_active(bool(self.settings["star"]))
        star.connect("toggled", lambda b: self._set("star", b.get_active()))
        self._row(g, "", star)
        self._row(g, "Star ratio (indent %)", self._spin("indent", 1, 99))
        return g

    def _line_page(self):
        g = self._grid()
        combo = Gtk.ComboBoxText()
        for value, text in (("horizontal", "Horizontal"), ("vertical", "Vertical"),
                            ("diagonal_down", "Diagonal ↘"), ("diagonal_up", "Diagonal ↗")):
            combo.append(value, text)
        combo.set_active_id(self.settings["line_direction"])
        combo.connect("changed", lambda c: self._set("line_direction", c.get_active_id()))
        self._row(g, "Direction", combo)
        self._row(g, "Weight", self._spin("stroke_width", 1, 500))
        return g

    def _custom_page(self):
        flow = Gtk.FlowBox()
        flow.set_max_children_per_line(4)
        flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
        for key, (label, _d) in G.CUSTOM.items():
            child = Gtk.FlowBoxChild()
            child.key = key
            child.set_tooltip_text(label)
            child.add(Icon({"shape": "custom", "custom": key}, 40))
            flow.add(child)
            if key == self.settings["custom"]:
                flow.select_child(child)
        flow.connect("child-activated", lambda f, c: self._set("custom", c.key))
        flow.connect("selected-children-changed",
                     lambda f: f.get_selected_children() and self._set("custom", f.get_selected_children()[0].key))
        return flow

    def _paint_grid(self):
        g = self._grid()
        fill = Gtk.CheckButton(label="Fill")
        fill.set_active(bool(self.settings["fill"]))
        fill.connect("toggled", lambda b: self._set("fill", b.get_active()))
        fill_color = Gtk.ColorButton.new_with_rgba(rgba(self.settings["fill_color"]))
        fill_color.connect("color-set", lambda b: self._set("fill_color", rgba_hex(b.get_rgba())))
        box = Gtk.Box(spacing=8)
        box.pack_start(fill, False, False, 0)
        box.pack_start(fill_color, True, True, 0)
        self._row(g, "", box)
        stroke = Gtk.CheckButton(label="Stroke")
        stroke.set_active(bool(self.settings["stroke"]))
        stroke.connect("toggled", lambda b: self._set("stroke", b.get_active()))
        stroke_color = Gtk.ColorButton.new_with_rgba(rgba(self.settings["stroke_color"]))
        stroke_color.connect("color-set", lambda b: self._set("stroke_color", rgba_hex(b.get_rgba())))
        box = Gtk.Box(spacing=8)
        box.pack_start(stroke, False, False, 0)
        box.pack_start(stroke_color, True, True, 0)
        self._row(g, "", box)
        self._row(g, "Stroke width (px)", self._spin("stroke_width", 1, 500))
        return g

    def _tool_selected(self, listbox, row):
        if row is not None:
            self.stack.set_visible_child_name(row.key)
            self._set("shape", row.key)

    # -------------------------------------------------------------- preview

    def _set(self, key, value):
        if self.settings.get(key) == value:
            return
        self.settings[key] = value
        if key in GEOMETRY_KEYS:
            self.geometry_dirty = True
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(80, self._update)

    def _start_preview(self):
        self.image.undo_freeze()
        if self.editing is not None:
            self.layer, self.path = self.editing, self.editing.get_path()
        else:
            self.path = Gimp.Path.new(self.image, "Shape")
            self.image.insert_path(self.path, None, 0)
            fill_path(self.path, G.build(self.settings, self.box))
            self.layer = Gimp.VectorLayer.new(self.image, self.path)
            parent = None
            pos = 0
            sel = self.image.get_selected_layers()
            if sel:
                parent, pos = sel[0].get_parent(), self.image.get_item_position(sel[0])
            self.image.insert_layer(self.layer, parent, pos)
        self._update()

    def _update(self):
        self.pending = None
        if self.geometry_dirty:
            fill_path(self.path, G.build(self.settings, self.box))
            self.geometry_dirty = False
        style_layer(self.layer, self.settings)
        Gimp.displays_flush()
        return False

    def _name(self):
        s = self.settings
        if s["shape"] == "custom":
            return G.CUSTOM[s["custom"]][0]
        return dict(G.SHAPES)[s["shape"]].replace(" Tool", "")

    def _tag(self, layer):
        _ok, ox, oy = layer.get_offsets()
        data = {"settings": self.settings, "box": list(self.box), "offsets": [ox, oy]}
        layer.attach_parasite(Gimp.Parasite.new(PARASITE, 1, list(json.dumps(data).encode())))

    def run(self):
        response = self.dialog.run()
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending = None
        final = dict(self.settings)
        ok = response == Gtk.ResponseType.OK
        self.dialog.destroy()
        # take the preview back out of the image, then do it again for
        # real, in one undo step
        if self.editing is not None:
            self.settings = self.original
            self.geometry_dirty = any(final.get(k) != self.original.get(k) for k in GEOMETRY_KEYS)
            self._update()
        else:
            self.image.remove_layer(self.layer)
            self.image.remove_path(self.path)
        self.image.undo_thaw()
        if ok:
            self.image.undo_group_start()
            try:
                self.settings = final
                if self.editing is not None:
                    self.geometry_dirty = any(final.get(k) != self.original.get(k) for k in GEOMETRY_KEYS)
                    self._update()
                    layer = self.editing
                else:
                    self.geometry_dirty = True
                    self._start_without_freeze()
                    layer = self.layer
                    Gimp.Selection.none(self.image)
                layer.set_name(self._name())
                self._tag(layer)
                save_last(final)
            finally:
                self.image.undo_group_end()
        Gimp.displays_flush()

    def _start_without_freeze(self):
        self.path = Gimp.Path.new(self.image, self._name())
        self.image.insert_path(self.path, None, 0)
        fill_path(self.path, G.build(self.settings, self.box))
        self.layer = Gimp.VectorLayer.new(self.image, self.path)
        sel = self.image.get_selected_layers()
        parent = sel[0].get_parent() if sel else None
        pos = self.image.get_item_position(sel[0]) if sel else 0
        self.image.insert_layer(self.layer, parent, pos)
        style_layer(self.layer, self.settings)
        self.image.set_selected_layers([self.layer])


def run(procedure, run_mode, image, drawables, config, data):
    if run_mode != Gimp.RunMode.INTERACTIVE:
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR,
                                           GLib.Error("The Shape Tool needs an interactive run."))
    try:
        GimpUi.init(PROC)
        sel = image.get_selected_layers()
        editing = sel[0] if (len(sel) == 1 and isinstance(sel[0], Gimp.VectorLayer)
                             and read_json(sel[0], PARASITE) is not None) else None
        ShapeDialog(image, editing).run()
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


class ShapeTool(Gimp.PlugIn):
    def do_set_i18n(self, procname):
        return False

    def do_query_procedures(self):
        # vector layers arrived in GIMP 3.2
        return [PROC] if hasattr(Gimp, "VectorLayer") else []

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        procedure.set_image_types("*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.ALWAYS)
        procedure.set_menu_label("S_hape Tool...")
        procedure.set_documentation(
            "Draw a Photoshop-style shape as a vector layer",
            "Rectangle, Ellipse, Triangle, Polygon, Line and Custom Shape, like "
            "Photoshop's shape tools (U): fills the selection, or the middle of the "
            "image; a selected shape layer is edited instead.", name)
        procedure.set_attribution("gimp-setup", "gimp-setup contributors", "2026")
        procedure.add_menu_path("<Image>/Tools")
        procedure.add_menu_path("<Image>/Layer")
        return procedure


Gimp.main(ShapeTool.__gtype__, sys.argv)
