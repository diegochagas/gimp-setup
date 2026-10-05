#!/usr/bin/env python3
#
# AI Object Selection: Photoshop's Object Selection tool and Select
# Subject for GIMP 3, with a local model (SAM 2.1, Segment Anything,
# through a running ComfyUI server).
#
#   Select > Object Selection (AI): draw a rough rectangle (or lasso)
#     around an object, run it: the selection snaps to the object.
#   Select > Subject (AI): selects the main subject of the whole image.
#
# What the model sees is the visible image (all layers), not just the
# active layer, like Photoshop's "Sample All Layers". The area around the
# box is sent at full resolution (up to MAX_SIDE px), so small objects
# keep their detail. The result replaces the selection and is undoable.
#
# Model: SAM 2.1 large through comfyui_client.py next to this file
# (ComfyUI-segment-anything-2 + gimp-setup's GimpSetupBBox node).
# Address: COMFYUI_URL or ~/.config/PhotoGIMP/comfyui-url
# (default http://127.0.0.1:8188).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import os
import shutil
import sys
import tempfile

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
from gi.repository import GLib, Gio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comfyui_client  # noqa: E402

OBJECT_PROC = 'ai-object-select'
SUBJECT_PROC = 'ai-select-subject'
# Context around the box, as a share of its larger side (min MARGIN_MIN px):
# the model needs to see where the object ends.
MARGIN_SHARE = 0.25
MARGIN_MIN = 32
# Longest side sent to the model; SAM itself works at 1024 px.
MAX_SIDE = 2048


def _export_png(image, path):
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image,
                   Gio.File.new_for_path(path), None)


def _region_png(image, cx, cy, cw, ch, scale, path):
    """The visible image inside the region, scaled, as a PNG file."""
    dup = image.duplicate()
    try:
        Gimp.Selection.none(dup)
        dup.flatten()
        dup.crop(cw, ch, cx, cy)
        if scale != 1.0:
            dup.scale(max(1, round(cw * scale)), max(1, round(ch * scale)))
        _export_png(dup, path)
    finally:
        dup.delete()
    with open(path, 'rb') as f:
        return f.read()


def _select_from_mask(image, mask_path, cx, cy, cw, ch):
    """Replace the selection with the white part of the mask PNG placed
    over the region."""
    selected = image.get_selected_layers()
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image,
                                 Gio.File.new_for_path(mask_path))
    image.insert_layer(layer, None, 0)
    try:
        if layer.get_width() != cw or layer.get_height() != ch:
            layer.scale(cw, ch, False)
        layer.set_offsets(cx, cy)
        mask = layer.create_mask(Gimp.AddMaskType.COPY)
        layer.add_mask(mask)
        image.select_item(Gimp.ChannelOps.REPLACE, mask)
    finally:
        image.remove_layer(layer)
        if selected:
            image.set_selected_layers(selected)


def _select_object(image, box):
    """box: x1, y1, x2, y2 in image pixels."""
    x1, y1, x2, y2 = box
    iw, ih = image.get_width(), image.get_height()
    margin = max(MARGIN_MIN, round(MARGIN_SHARE * max(x2 - x1, y2 - y1)))
    cx, cy = max(0, x1 - margin), max(0, y1 - margin)
    cw, ch = min(iw, x2 + margin) - cx, min(ih, y2 + margin) - cy
    scale = min(1.0, MAX_SIDE / float(max(cw, ch)))

    tmpdir = tempfile.mkdtemp(prefix='ai-object-select-')
    try:
        Gimp.progress_init('Preparing image region...')
        png = _region_png(image, cx, cy, cw, ch, scale,
                          os.path.join(tmpdir, 'region.png'))
        local_box = [(x1 - cx) * scale, (y1 - cy) * scale,
                     (x2 - cx) * scale, (y2 - cy) * scale]

        def progress(elapsed):
            Gimp.progress_set_text(
                'Finding the object (SAM 2.1)... %d s — the first run '
                'loads the model' % elapsed)
            Gimp.progress_pulse()

        mask_png = comfyui_client.segment(png, [local_box], progress=progress)
        mask_path = os.path.join(tmpdir, 'mask.png')
        with open(mask_path, 'wb') as f:
            f.write(mask_png)

        image.undo_group_start()
        try:
            _select_from_mask(image, mask_path, cx, cy, cw, ch)
        finally:
            image.undo_group_end()
        if Gimp.Selection.is_empty(image):
            Gimp.message('No object was found inside the box. Draw it a '
                         'little larger around the object and try again.')
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        Gimp.progress_end()
    Gimp.displays_flush()


def run(procedure, run_mode, image, drawables, config, data):
    try:
        if procedure.get_name() == SUBJECT_PROC:
            box = (0, 0, image.get_width(), image.get_height())
        else:
            ok, non_empty, x1, y1, x2, y2 = Gimp.Selection.bounds(image)
            if not non_empty:
                raise RuntimeError(
                    'Draw a rectangle (or a lasso) around the object '
                    'first, then run Object Selection again. For the main '
                    'subject of the whole image use Select > Subject (AI).')
            box = (x1, y1, x2, y2)
        _select_object(image, box)
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                           GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,
                                       GLib.Error())


class AiObjectSelect(Gimp.PlugIn):
    def do_set_i18n(self, procname):
        return False

    def do_query_procedures(self):
        return [OBJECT_PROC, SUBJECT_PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name,
                                            Gimp.PDBProcType.PLUGIN,
                                            run, None)
        procedure.set_image_types('*')
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.NO_DRAWABLES)
        procedure.set_attribution('gimp-setup', 'gimp-setup contributors',
                                  '2026')
        if name == OBJECT_PROC:
            procedure.set_menu_label('_Object Selection (AI)')
            procedure.set_documentation(
                'Select the object inside the selection with AI',
                'Like Photoshop\'s Object Selection tool: draw a rough '
                'rectangle or lasso around an object, run this, and the '
                'selection snaps to the object (SAM 2.1, local).', name)
        else:
            procedure.set_menu_label('S_ubject (AI)')
            procedure.set_documentation(
                'Select the main subject of the image with AI',
                'Like Photoshop\'s Select > Subject (SAM 2.1, local).', name)
        procedure.add_menu_path('<Image>/Select')
        return procedure


Gimp.main(AiObjectSelect.__gtype__, sys.argv)
