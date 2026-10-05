#!/usr/bin/env python3
#
# Smart Objects: Photoshop's Smart Object workflow for GIMP 3.2, built on
# GIMP's link layers (a layer rendered from a file, re-rendered whenever
# that file changes, whose moves/scales/rotations stay non-destructive).
#
#   Layer > Smart Object > Convert to Smart Object
#     The selected layers (groups, text, effects included) move into an
#     XCF of their own, cropped to them, and are replaced, at the same
#     place in the stack and on the canvas, by one link layer showing it.
#   Layer > Smart Object > Edit Contents
#     Opens the selected smart object's file in a new tab. Save it
#     (Ctrl+S) and every link layer showing it updates.
#   Layer > Smart Object > Replace Contents...
#     Points the selected smart object at another image file.
#   Rasterize: GIMP's own Layer > Rasterize.
#
# Photoshop embeds a smart object inside the PSD; a GIMP link layer points
# at a file instead. The files go into "<image name> smart objects/" next
# to the image, or, for an image never saved, into
# ~/.local/share/gimp-smart-objects/ (save the image, then convert, to
# keep them together). Copy that folder along with the image.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import os
import re
import sys
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
from gi.repository import GLib, GObject, Gio

CONVERT_PROC = 'smart-object-convert'
EDIT_PROC = 'smart-object-edit'
REPLACE_PROC = 'smart-object-replace'
MENU = '<Image>/Layer/Smart Object'


def error(procedure, message):
    return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                       GLib.Error(message))


def success(procedure):
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


def safe_name(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', name).strip(' .')
    return (name or 'Smart Object')[:80]


def contents_dir(image):
    """Folder for the smart object files of image."""
    f = image.get_xcf_file() or image.get_file()
    if f is not None and f.get_path():
        path = f.get_path()
        stem = os.path.splitext(os.path.basename(path))[0]
        return os.path.join(os.path.dirname(path), stem + ' smart objects')
    stamp = time.strftime('%Y-%m-%d %H%M%S')
    return os.path.join(GLib.get_user_data_dir(), 'gimp-smart-objects',
                        'Untitled %s' % stamp)


def unique_path(folder, name):
    base = os.path.join(folder, safe_name(name))
    path, n = base + '.xcf', 2
    while os.path.exists(path):
        path, n = '%s %d.xcf' % (base, n), n + 1
    return path


def layer_bounds(layers):
    x1 = y1 = None
    x2 = y2 = None
    for l in layers:
        _ok, x, y = l.get_offsets()
        w, h = l.get_width(), l.get_height()
        x1 = x if x1 is None else min(x1, x)
        y1 = y if y1 is None else min(y1, y)
        x2 = x + w if x2 is None else max(x2, x + w)
        y2 = y + h if y2 is None else max(y2, y + h)
    return x1, y1, x2 - x1, y2 - y1


def top_level_selection(image):
    """Selected layers, minus those inside another selected group, in stack
    order (top first)."""
    selected = list(image.get_selected_layers())
    ids = {l.get_id() for l in selected}

    def inside_selected_group(l):
        p = l.get_parent()
        while p is not None:
            if p.get_id() in ids:
                return True
            p = p.get_parent()
        return False

    layers = [l for l in selected if not inside_selected_group(l)]

    def stack_key(l):
        key, item = [], l
        while item is not None:
            key.insert(0, image.get_item_position(item))
            item = item.get_parent()
        return key
    return sorted(layers, key=stack_key)


def convert(procedure, image):
    layers = top_level_selection(image)
    if not layers:
        return error(procedure, 'Select the layer(s) to turn into a smart object.')
    parent = layers[0].get_parent()
    if any((l.get_parent() and l.get_parent().get_id()) != (parent and parent.get_id())
           for l in layers):
        return error(procedure, 'The selected layers must be in the same group.')

    bx, by, bw, bh = layer_bounds(layers)
    name = layers[0].get_name() if len(layers) == 1 else 'Smart Object'
    folder = contents_dir(image)
    os.makedirs(folder, exist_ok=True)
    path = unique_path(folder, name)

    # The contents image: same type, precision, resolution and colour
    # profile, the layers copied bottom first so the stack order is kept.
    contents = Gimp.Image.new_with_precision(bw, bh, image.get_base_type(),
                                             image.get_precision())
    try:
        res = image.get_resolution()
        contents.set_resolution(res.xresolution, res.yresolution)
        profile = image.get_color_profile()
        if profile is not None:
            contents.set_color_profile(profile)
        contents.undo_disable()
        for l in reversed(layers):
            copy = Gimp.Layer.new_from_drawable(l, contents)
            contents.insert_layer(copy, None, 0)
            _ok, x, y = l.get_offsets()
            copy.set_offsets(x - bx, y - by)
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, contents,
                       Gio.File.new_for_path(path), None)
    finally:
        contents.delete()

    image.undo_group_start()
    try:
        link = Gimp.LinkLayer.new(image, Gio.File.new_for_path(path))
        if link is None:
            raise RuntimeError('GIMP could not create a link layer for %s' % path)
        image.insert_layer(link, parent, image.get_item_position(layers[0]))
        link.set_offsets(bx, by)
        link.set_name(name)
        for l in layers:
            image.remove_layer(l)
        image.set_selected_layers([link])
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return success(procedure)


def selected_link(image):
    layers = image.get_selected_layers()
    if len(layers) != 1 or not isinstance(layers[0], Gimp.LinkLayer):
        return None
    return layers[0]


def edit(procedure, image):
    link = selected_link(image)
    if link is None:
        return error(procedure, 'Select one smart object (a link layer) first.')
    if link.is_rasterized():
        return error(procedure, 'This layer was rasterized: it no longer shows a file.')
    f = link.get_file()
    if f is None or not f.query_exists(None):
        return error(procedure, 'The smart object file is missing: %s'
                     % (f.get_path() if f else '?'))
    for img in Gimp.get_images():
        xf = img.get_xcf_file() or img.get_file()
        if xf is not None and xf.equal(f):
            Gimp.message('The contents of "%s" are already open in another tab.'
                         % link.get_name())
            return success(procedure)
    contents = Gimp.file_load(Gimp.RunMode.INTERACTIVE, f)
    Gimp.Display.new(contents)
    if not (f.get_path() or '').lower().endswith('.xcf'):
        Gimp.message('This smart object shows "%s". Use File > Overwrite '
                     '(not Save) after editing so the link layer updates.'
                     % os.path.basename(f.get_path() or ''))
    return success(procedure)


def replace(procedure, image, config):
    link = selected_link(image)
    if link is None:
        return error(procedure, 'Select one smart object (a link layer) first.')
    f = config.get_property('file')
    if f is None:
        return error(procedure, 'No file chosen.')
    image.undo_group_start()
    try:
        if not link.set_file(f):
            raise RuntimeError('GIMP could not load %s' % f.get_path())
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return success(procedure)


def run(procedure, run_mode, image, drawables, config, data):
    name = procedure.get_name()
    try:
        if name == CONVERT_PROC:
            return convert(procedure, image)
        if name == EDIT_PROC:
            return edit(procedure, image)
        if run_mode == Gimp.RunMode.INTERACTIVE:
            gi.require_version('GimpUi', '3.0')
            from gi.repository import GimpUi
            GimpUi.init(name)
            dialog = GimpUi.ProcedureDialog(procedure=procedure, config=config)
            dialog.fill(None)
            ok = dialog.run()
            dialog.destroy()
            if not ok:
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        return replace(procedure, image, config)
    except Exception as e:
        return error(procedure, str(e))


class SmartObjects(Gimp.PlugIn):
    def do_set_i18n(self, procname):
        return False

    def do_query_procedures(self):
        # link layers arrived in GIMP 3.2
        if not hasattr(Gimp, 'LinkLayer'):
            return []
        return [CONVERT_PROC, EDIT_PROC, REPLACE_PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        procedure.set_image_types('*')
        procedure.set_attribution('gimp-setup', 'gimp-setup contributors', '2026')
        if name == CONVERT_PROC:
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                           Gimp.ProcedureSensitivityMask.DRAWABLES)
            procedure.set_menu_label('_Convert to Smart Object')
            procedure.set_documentation(
                'Turn the selected layers into a smart object',
                'Moves the selected layers into an XCF of their own and shows '
                'it through a link layer, like Photoshop\'s Convert to Smart '
                'Object: transforms stay non-destructive and Edit Contents '
                'changes it everywhere.', name)
        elif name == EDIT_PROC:
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
            procedure.set_menu_label('_Edit Contents')
            procedure.set_documentation(
                'Open the contents of the selected smart object',
                'Opens the file of the selected link layer in a new tab; save '
                'it and the smart object updates.', name)
        else:
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
            procedure.set_menu_label('_Replace Contents...')
            procedure.set_documentation(
                'Show another file in the selected smart object',
                'Points the selected link layer at another image file, like '
                'Photoshop\'s Replace Contents.', name)
            procedure.add_file_argument('file', '_File', 'Image file to show',
                                        Gimp.FileChooserAction.OPEN, False, None,
                                        GObject.ParamFlags.READWRITE)
        procedure.add_menu_path(MENU)
        return procedure


Gimp.main(SmartObjects.__gtype__, sys.argv)
