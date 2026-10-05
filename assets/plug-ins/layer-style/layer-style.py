#!/usr/bin/env python3
#
# Layer Style: Photoshop's Layer Style dialog (fx) for GIMP 3.
#
#   Layer > Layer Style > Blending Options...      the dialog
#   Layer > Layer Style > Drop Shadow... / Stroke... / ...
#                                                  the dialog, on that effect
#   Layer > Layer Style > Copy / Paste / Clear Layer Style
#
# The dialog looks and works like Photoshop's: the effects on the left
# (tick to enable, click to edit), their settings on the right in
# Photoshop's own terms (opacity, angle, distance, spread, size, Use Global
# Light...), live preview on the canvas, OK / Cancel. Each effect becomes a
# non-destructive filter named "Layer Style: <effect>", so it also shows
# in the Layers panel's fx column; open the dialog again to change it.
# OK makes one undo step.
#
# Rendering: layer_style_engine.py next to this file.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import json
import math
import os
import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, GimpUi, GLib, GObject, Gtk, Gdk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layer_style_engine as E  # noqa: E402

DIALOG_PROC = "layer-style-dialog"
COPY_PROC = "layer-style-copy"
PASTE_PROC = "layer-style-paste"
CLEAR_PROC = "layer-style-clear"
EFFECT_PROCS = {"layer-style-" + key.replace("_", "-"): key for key, _l in E.EFFECTS}
MENU = "<Image>/Layer/Layer Style"
CLIPBOARD = os.path.join(GLib.get_user_config_dir(), "PhotoGIMP", "layer-style-clipboard.json")
GLOBAL_LIGHT = "gimp-setup-global-light"     # image parasite: the shared angle
GLOBAL_KEYS = ("drop_shadow", "inner_shadow", "bevel")


def error(procedure, message):
    return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(message))


def success(procedure):
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


def target_layer(image):
    layers = image.get_selected_layers()
    return layers[0] if len(layers) == 1 else None


def global_angle(image):
    try:
        return float(E.parasite_text(image, GLOBAL_LIGHT) or 120)
    except ValueError:
        return 120.0


def set_global_angle(image, angle):
    image.attach_parasite(Gimp.Parasite.new(GLOBAL_LIGHT, 1, list(("%g" % angle).encode())))


# ------------------------------------------------------------------ widgets

def hex_to_rgba(value):
    rgba = Gdk.RGBA()
    rgba.parse(value or "#000000")
    return rgba


def rgba_to_hex(rgba):
    return "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in (rgba.red, rgba.green, rgba.blue))


class AngleDial(Gtk.DrawingArea):
    """Photoshop's round angle control: drag the line to set the angle."""

    def __init__(self, on_change):
        super().__init__()
        self.angle = 0.0
        self.on_change = on_change
        self.set_size_request(44, 44)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_MOTION_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._pick)
        self.connect("motion-notify-event", self._pick)

    def set_angle(self, angle):
        self.angle = angle
        self.queue_draw()

    def _draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        r = min(w, h) / 2.0 - 2
        cx, cy = w / 2.0, h / 2.0
        style = widget.get_style_context()
        fg = style.get_color(Gtk.StateFlags.NORMAL)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.9)
        cr.set_line_width(1.2)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        a = math.radians(self.angle)
        cr.move_to(cx, cy)
        cr.line_to(cx + r * math.cos(a), cy - r * math.sin(a))
        cr.stroke()
        cr.arc(cx, cy, 2, 0, 2 * math.pi)
        cr.fill()
        return False

    def _pick(self, widget, event):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        angle = round(math.degrees(math.atan2(h / 2.0 - event.y, event.x - w / 2.0)))
        self.on_change(float(angle))
        return True


class LayerStyleDialog:
    def __init__(self, image, layer, focus_key=None):
        self.image, self.layer = image, layer
        self.original = E.read_style(layer)
        self.style = {k: dict(v) for k, v in self.original.items()}
        self.global_angle = global_angle(image)
        self.pending = None
        self.widgets = {}            # (effect, setting) -> setter for refresh
        self.checks = {}

        self.dialog = GimpUi.Dialog(title="Layer Style", role="gimp-setup-layer-style")
        self.dialog.set_default_size(780, 520)
        self.dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.dialog.add_button("_OK", Gtk.ResponseType.OK)
        self.dialog.set_default_response(Gtk.ResponseType.OK)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        body.set_border_width(12)
        self.dialog.get_content_area().pack_start(body, True, True, 0)

        # left: the effect list
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.set_size_request(220, -1)
        frame = Gtk.Frame()
        frame.add(self.list)
        body.pack_start(frame, False, False, 0)

        # right: one settings page per effect
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        body.pack_start(self.stack, True, True, 0)

        self.stack.add_named(self._blending_page(), "blending")
        row = self._list_row("Blending Options", None, "blending")
        self.list.add(row)
        for key, label in E.EFFECTS:
            self.stack.add_named(self._effect_page(key), key)
            self.list.add(self._list_row(label, key, key))
        self.list.connect("row-selected", self._row_selected)

        self.dialog.show_all()
        start = focus_key or "blending"
        if focus_key:
            self._enable(focus_key, True)
        for r in self.list.get_children():
            if r.page == start:
                self.list.select_row(r)
        self.stack.set_visible_child_name(start)

    # ---------------------------------------------------------------- list

    def _list_row(self, label, key, page):
        row = Gtk.ListBoxRow()
        row.page = page
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_border_width(4)
        if key:
            check = Gtk.CheckButton()
            check.set_active(bool(self.style.get(key, {}).get("enabled")))
            check.connect("toggled", lambda b, k=key: self._enable(k, b.get_active(), from_check=True))
            self.checks[key] = check
            box.pack_start(check, False, False, 0)
        else:
            box.pack_start(Gtk.Label(label=" "), False, False, 4)
        lab = Gtk.Label(label=label, xalign=0)
        box.pack_start(lab, True, True, 0)
        row.add(box)
        return row

    def _row_selected(self, listbox, row):
        if row is not None:
            self.stack.set_visible_child_name(row.page)

    def _enable(self, key, on, from_check=False):
        s = self.style.setdefault(key, dict(E.DEFAULTS[key]))
        s["enabled"] = on
        if not from_check and key in self.checks:
            self.checks[key].set_active(on)
        self._schedule()

    # --------------------------------------------------------------- pages

    def _page(self, title):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        head = Gtk.Label(xalign=0)
        head.set_markup("<b>%s</b>" % GLib.markup_escape_text(title))
        outer.pack_start(head, False, False, 0)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        grid.set_margin_start(8)
        outer.pack_start(grid, False, False, 0)
        outer.grid_row = 0
        outer.grid = grid
        return outer

    def _add(self, page, label, widget, unit=""):
        lab = Gtk.Label(label=label + ":" if label else "", xalign=1)
        page.grid.attach(lab, 0, page.grid_row, 1, 1)
        page.grid.attach(widget, 1, page.grid_row, 1, 1)
        if unit:
            page.grid.attach(Gtk.Label(label=unit, xalign=0), 2, page.grid_row, 1, 1)
        page.grid_row += 1

    def _value(self, key, name):
        return self.style.get(key, E.DEFAULTS[key]).get(name, E.DEFAULTS[key].get(name))

    def _changed(self, key, name, value):
        s = self.style.setdefault(key, dict(E.DEFAULTS[key]))
        s[name] = value
        if name == "angle" and key in GLOBAL_KEYS and s.get("use_global", True):
            self._set_global(value)
        # editing an effect switches it on, as in Photoshop
        if not s.get("enabled"):
            self._enable(key, True)
        self._schedule()

    def _set_global(self, angle):
        self.global_angle = angle
        for k in GLOBAL_KEYS:
            s = self.style.get(k)
            if s is not None and s.get("use_global", True):
                s["angle"] = angle
            setter = self.widgets.get((k, "angle"))
            if setter and (s is None or s.get("use_global", True)):
                setter(angle)

    def slider(self, page, key, name, label, lo, hi, unit="", digits=0):
        adj = Gtk.Adjustment(value=float(self._value(key, name)), lower=lo, upper=hi,
                             step_increment=1, page_increment=10)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
        scale.set_draw_value(False)
        scale.set_size_request(220, -1)
        spin = Gtk.SpinButton(adjustment=adj, digits=digits)
        spin.set_width_chars(5)
        box = Gtk.Box(spacing=6)
        box.pack_start(scale, True, True, 0)
        box.pack_start(spin, False, False, 0)
        adj.connect("value-changed", lambda a: self._changed(key, name, round(a.get_value(), digits) if digits else int(a.get_value())))
        self.widgets[(key, name)] = lambda v: adj.set_value(float(v))
        self._add(page, label, box, unit)

    def color(self, page, key, name, label):
        btn = Gtk.ColorButton.new_with_rgba(hex_to_rgba(self._value(key, name)))
        btn.connect("color-set", lambda b: self._changed(key, name, rgba_to_hex(b.get_rgba())))
        self.widgets[(key, name)] = lambda v: btn.set_rgba(hex_to_rgba(v))
        self._add(page, label, btn)

    def choice(self, page, key, name, label, options):
        combo = Gtk.ComboBoxText()
        for value, text in options:
            combo.append(value, text)
        combo.set_active_id(str(self._value(key, name)))
        combo.connect("changed", lambda c: self._changed(key, name, c.get_active_id()))
        self.widgets[(key, name)] = lambda v: combo.set_active_id(str(v))
        self._add(page, label, combo)

    def blend(self, page, key, label="Blend Mode"):
        self.choice(page, key, "blend", label, [(k, l) for k, l, _m in E.BLEND_MODES])

    def check(self, page, key, name, label):
        btn = Gtk.CheckButton(label=label)
        btn.set_active(bool(self._value(key, name)))
        btn.connect("toggled", lambda b: self._changed(key, name, b.get_active()))
        self.widgets[(key, name)] = lambda v: btn.set_active(bool(v))
        self._add(page, "", btn)

    def angle(self, page, key, label="Angle", global_light=True):
        if key in GLOBAL_KEYS and self._value(key, "use_global") is not False:
            self.style.setdefault(key, dict(E.DEFAULTS[key]))["angle"] = self.global_angle
        adj = Gtk.Adjustment(value=float(self._value(key, "angle")), lower=-180, upper=180,
                             step_increment=1, page_increment=15)
        spin = Gtk.SpinButton(adjustment=adj, digits=0)
        dial = AngleDial(lambda a: adj.set_value(a))
        dial.set_angle(adj.get_value())

        def moved(a):
            dial.set_angle(a.get_value())
            self._changed(key, "angle", int(a.get_value()))
        adj.connect("value-changed", moved)
        box = Gtk.Box(spacing=6)
        box.pack_start(dial, False, False, 0)
        box.pack_start(spin, False, False, 0)
        box.pack_start(Gtk.Label(label="°"), False, False, 0)
        if global_light and key in GLOBAL_KEYS:
            use = Gtk.CheckButton(label="Use Global Light")
            use.set_active(self._value(key, "use_global") is not False)

            def toggled(b):
                self.style.setdefault(key, dict(E.DEFAULTS[key]))["use_global"] = b.get_active()
                if b.get_active():
                    adj.set_value(self.global_angle)
            use.connect("toggled", toggled)
            box.pack_start(use, False, False, 8)
        self.widgets[(key, "angle")] = lambda v: adj.set_value(float(v))
        self._add(page, label, box)

    def reset_button(self, page, key):
        btn = Gtk.Button(label="Reset to Default")

        def reset(_b):
            enabled = self.style.get(key, {}).get("enabled", True)
            self.style[key] = dict(E.DEFAULTS[key], enabled=enabled)
            for (k, name), setter in self.widgets.items():
                if k == key and name in E.DEFAULTS[key]:
                    setter(E.DEFAULTS[key][name])
            self._schedule()
        btn.connect("clicked", reset)
        btn.set_halign(Gtk.Align.START)
        page.pack_start(btn, False, False, 6)

    def _blending_page(self):
        page = self._page("Blending Options")
        adj = Gtk.Adjustment(value=self.layer.get_opacity(), lower=0, upper=100, step_increment=1, page_increment=10)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
        scale.set_draw_value(False)
        scale.set_size_request(220, -1)
        spin = Gtk.SpinButton(adjustment=adj, digits=0)
        box = Gtk.Box(spacing=6)
        box.pack_start(scale, True, True, 0)
        box.pack_start(spin, False, False, 0)
        self.opacity_adj = adj
        adj.connect("value-changed", lambda a: self._schedule())
        self._add(page, "Opacity", box, "%")
        note = Gtk.Label(xalign=0)
        note.set_line_wrap(True)
        note.set_max_width_chars(60)
        note.set_markup("<small>Tick an effect on the left to add it, click its name to change it. "
                        "Effects are non-destructive filters: they also show in the Layers "
                        "panel's fx column. Satin and Contours have no GIMP counterpart.</small>")
        page.pack_start(note, False, False, 12)
        return page

    def _effect_page(self, key):
        page = self._page(E.LABELS[key])
        if key in ("drop_shadow", "inner_shadow"):
            self.color(page, key, "color", "Color")
            self.slider(page, key, "opacity", "Opacity", 0, 100, "%")
            self.angle(page, key)
            self.slider(page, key, "distance", "Distance", 0, 300, "px")
            self.slider(page, key, "spread" if key == "drop_shadow" else "choke",
                        "Spread" if key == "drop_shadow" else "Choke", 0, 100, "%")
            self.slider(page, key, "size", "Size", 0, 250, "px")
        elif key in ("outer_glow", "inner_glow"):
            self.color(page, key, "color", "Color")
            self.slider(page, key, "opacity", "Opacity", 0, 100, "%")
            self.slider(page, key, "spread" if key == "outer_glow" else "choke",
                        "Spread" if key == "outer_glow" else "Choke", 0, 100, "%")
            self.slider(page, key, "size", "Size", 0, 250, "px")
        elif key == "stroke":
            self.slider(page, key, "size", "Size", 1, 250, "px")
            self.choice(page, key, "position", "Position",
                        [("outside", "Outside"), ("inside", "Inside"), ("center", "Center")])
            self.slider(page, key, "opacity", "Opacity", 0, 100, "%")
            self.color(page, key, "color", "Color")
        elif key == "bevel":
            self.choice(page, key, "technique", "Technique", [("smooth", "Smooth"), ("chisel", "Chisel Hard")])
            self.slider(page, key, "depth", "Depth", 1, 250, "%")
            self.choice(page, key, "direction", "Direction", [("up", "Up"), ("down", "Down")])
            self.slider(page, key, "size", "Size", 1, 13, "px")
            self.angle(page, key)
            self.slider(page, key, "altitude", "Altitude", 0, 90, "°")
            self.choice(page, key, "highlight_mode", "Light Mode",
                        [("hardlight", "Hard Light"), ("multiply", "Multiply"), ("colordodge", "Color Dodge"),
                         ("darken", "Darken"), ("lighten", "Lighten"), ("add", "Add")])
        elif key == "color_overlay":
            self.blend(page, key)
            self.color(page, key, "color", "Color")
            self.slider(page, key, "opacity", "Opacity", 0, 100, "%")
        elif key == "gradient_overlay":
            self.blend(page, key)
            self.slider(page, key, "opacity", "Opacity", 0, 100, "%")
            self.color(page, key, "color1", "From")
            self.color(page, key, "color2", "To")
            self.check(page, key, "reverse", "Reverse")
            self.angle(page, key, global_light=False)
            self.slider(page, key, "scale", "Scale", 10, 150, "%")
        elif key == "pattern_overlay":
            self.blend(page, key)
            self.slider(page, key, "opacity", "Opacity", 0, 100, "%")
            chooser = Gtk.FileChooserButton(title="Pattern image", action=Gtk.FileChooserAction.OPEN)
            if self._value(key, "image"):
                chooser.set_filename(self._value(key, "image"))
            chooser.connect("file-set", lambda c: self._changed(key, "image", c.get_filename() or ""))
            self._add(page, "Pattern", chooser)
        self.reset_button(page, key)
        return page

    # ------------------------------------------------------------- preview

    def _schedule(self):
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(150, self._preview)

    def _preview(self):
        self.pending = None
        E.apply_style(self.layer, self.style)
        self.layer.set_opacity(self.opacity_adj.get_value())
        Gimp.displays_flush()
        return False

    def run(self):
        opacity = self.layer.get_opacity()
        # the preview edits the layer many times: none of it goes to the
        # undo history, the final result is one step
        self.image.undo_freeze()
        try:
            response = self.dialog.run()
            if self.pending:
                GLib.source_remove(self.pending)
                self.pending = None
            final = {k: dict(v) for k, v in self.style.items()}
            final_opacity = self.opacity_adj.get_value()
            E.apply_style(self.layer, self.original)
            self.layer.set_opacity(opacity)
        finally:
            self.image.undo_thaw()
            self.dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.image.undo_group_start()
            try:
                E.apply_style(self.layer, final)
                self.layer.set_opacity(final_opacity)
                set_global_angle(self.image, self.global_angle)
            finally:
                self.image.undo_group_end()
        Gimp.displays_flush()
        return response == Gtk.ResponseType.OK


# ------------------------------------------------------------------- procs

def run(procedure, run_mode, image, drawables, config, data):
    name = procedure.get_name()
    layer = target_layer(image)
    if layer is None and name not in (PASTE_PROC, CLEAR_PROC):
        return error(procedure, "Select one layer.")
    try:
        if name == COPY_PROC:
            style = E.read_style(layer)
            if not any(s.get("enabled") for s in style.values()):
                return error(procedure, "This layer has no layer style to copy.")
            os.makedirs(os.path.dirname(CLIPBOARD), exist_ok=True)
            with open(CLIPBOARD, "w") as f:
                json.dump(style, f)
            return success(procedure)
        if name in (PASTE_PROC, CLEAR_PROC):
            style = {}
            if name == PASTE_PROC:
                try:
                    with open(CLIPBOARD) as f:
                        style = json.load(f)
                except (OSError, ValueError):
                    return error(procedure, "Copy a layer style first (Layer > Layer Style > Copy Layer Style).")
            image.undo_group_start()
            try:
                for l in image.get_selected_layers():
                    E.apply_style(l, style)
            finally:
                image.undo_group_end()
            Gimp.displays_flush()
            return success(procedure)
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return error(procedure, "The Layer Style dialog needs an interactive run.")
        GimpUi.init(name)
        LayerStyleDialog(image, layer, EFFECT_PROCS.get(name)).run()
        return success(procedure)
    except Exception as e:
        return error(procedure, str(e))


class LayerStyle(Gimp.PlugIn):
    def do_set_i18n(self, procname):
        return False

    def do_query_procedures(self):
        return [DIALOG_PROC, *EFFECT_PROCS, COPY_PROC, PASTE_PROC, CLEAR_PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        procedure.set_image_types("*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_attribution("gimp-setup", "gimp-setup contributors", "2026")
        if name == DIALOG_PROC:
            label, blurb = "_Blending Options...", "Photoshop-style Layer Style dialog"
        elif name in EFFECT_PROCS:
            label = E.LABELS[EFFECT_PROCS[name]] + "..."
            blurb = "Layer Style: " + E.LABELS[EFFECT_PROCS[name]]
        elif name == COPY_PROC:
            label, blurb = "_Copy Layer Style", "Copy the layer's style"
        elif name == PASTE_PROC:
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                           Gimp.ProcedureSensitivityMask.DRAWABLES)
            label, blurb = "_Paste Layer Style", "Paste the copied style on the selected layers"
        else:
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                           Gimp.ProcedureSensitivityMask.DRAWABLES)
            label, blurb = "C_lear Layer Style", "Remove the layer style"
        procedure.set_menu_label(label)
        procedure.set_documentation(blurb, blurb + " (gimp-setup Layer Style).", name)
        procedure.add_menu_path(MENU)
        return procedure


Gimp.main(LayerStyle.__gtype__, sys.argv)
