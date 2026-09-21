#!/usr/bin/env python3
#
# AI Remove Selection: Photoshop-style "Remove tool" for GIMP 3.
#
# Inpaints (removes) whatever is inside the current selection and
# reconstructs the background. Photoshop-like workflow: press Q
# (Quick Mask), paint over the object with a brush (semi-transparent
# red overlay), press Q again, then run this from Filters > AI.
#
# For prompt-based fills ("Generative Fill") use the GIMP AI Plugin
# installed by gimp-setup, which shares the same models.
#
# Models (fully local, through a running ComfyUI server; no account, key
# or online service):
#   comfyui-klein / comfyui-qwen
#            FLUX.2 klein (fast) or Qwen-Image-Edit (slower, cleaner on
#            structured backgrounds), through comfyui_client.py next to
#            this file.
#            Address: COMFYUI_URL or ~/.config/PhotoGIMP/comfyui-url
#            (default http://127.0.0.1:8188). ComfyUI must be running.
#            "What is selected" picks how the model is shown the area:
#            an object is hidden from it (or FLUX.2 klein redraws it);
#            text or marks over a texture stay visible, so the real
#            texture between the strokes is continued (a hidden area
#            comes back as a flat patch on halftone scans). Auto hides
#            it first and redoes the job the other way when the fill
#            comes back flat.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import os
import sys
import tempfile

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
gi.require_version('Gegl', '0.4')
from gi.repository import Gegl
from gi.repository import GLib, GObject, Gio

import comfyui_client


# ---------------------------------------------------------------- backends

COMFYUI_MODES = {'auto': 'auto', 'object': 'hidden', 'texture': 'see_through'}


def call_comfyui(model, context_png, mask_png, target):
    def progress(elapsed):
        Gimp.progress_set_text(
            'ComfyUI (%s) is working... %d s — the first run loads the '
            'model and takes longer' % (comfyui_client.MODELS[model], elapsed))
        Gimp.progress_pulse()

    return comfyui_client.inpaint(model, context_png, mask_png, None,
                                  progress=progress,
                                  mode=COMFYUI_MODES.get(target, 'auto'))


# ------------------------------------------------------------- gimp helpers

def _export_png(image, path):
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image,
                   Gio.File.new_for_path(path), None)


def _render_context_and_mask(image, cx, cy, cw, ch, grow, tmpdir):
    """Export the padded selection region and its mask as PNG bytes."""
    ctx_path = os.path.join(tmpdir, 'context.png')
    mask_path = os.path.join(tmpdir, 'mask.png')

    dup = image.duplicate()
    try:
        dup.flatten()
        dup.crop(cw, ch, cx, cy)
        _export_png(dup, ctx_path)

        # Rasterize the selection into a black/white mask layer.
        Gimp.context_push()
        try:
            sel_chan = Gimp.Selection.save(dup)
            mask_layer = Gimp.Layer.new(dup, 'mask', cw, ch,
                                        Gimp.ImageType.RGBA_IMAGE, 100,
                                        Gimp.LayerMode.NORMAL)
            dup.insert_layer(mask_layer, None, -1)
            Gimp.Selection.none(dup)
            Gimp.context_set_foreground(Gegl.Color.new('black'))
            mask_layer.edit_fill(Gimp.FillType.FOREGROUND)
            dup.select_item(Gimp.ChannelOps.REPLACE, sel_chan)
            if grow > 0:
                Gimp.Selection.grow(dup, grow)
            Gimp.context_set_foreground(Gegl.Color.new('white'))
            mask_layer.edit_fill(Gimp.FillType.FOREGROUND)
            Gimp.Selection.none(dup)
        finally:
            Gimp.context_pop()
        dup.flatten()
        _export_png(dup, mask_path)
    finally:
        dup.delete()

    with open(ctx_path, 'rb') as f:
        ctx_png = f.read()
    with open(mask_path, 'rb') as f:
        mask_png = f.read()
    return ctx_png, mask_png


def _composite_result(image, result_bytes, cx, cy, cw, ch, tmpdir):
    """Insert the AI result as a new layer masked to the selection."""
    result_path = os.path.join(tmpdir, 'result.png')
    with open(result_path, 'wb') as f:
        f.write(result_bytes)

    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image,
                                 Gio.File.new_for_path(result_path))
    image.insert_layer(layer, None, -1)
    if layer.get_width() != cw or layer.get_height() != ch:
        layer.scale(cw, ch, False)
    layer.set_offsets(cx, cy)
    layer.set_name('AI Remove')

    # Mask the layer to a slightly feathered copy of the selection so the
    # edit blends with the untouched pixels around it, then restore the
    # user's original selection.
    sel_chan = Gimp.Selection.save(image)
    Gimp.Selection.grow(image, 1)
    Gimp.Selection.feather(image, 2.5)
    mask = layer.create_mask(Gimp.AddMaskType.SELECTION)
    layer.add_mask(mask)
    image.select_item(Gimp.ChannelOps.REPLACE, sel_chan)
    image.remove_channel(sel_chan)
    return layer


def _run_remove(image, model, padding, target):
    ok, non_empty, x1, y1, x2, y2 = Gimp.Selection.bounds(image)
    if not non_empty:
        raise RuntimeError(
            'Select the area first. Tip for a Photoshop-style Remove: '
            'press Q (Quick Mask), paint over the object with any brush, '
            'press Q again, then run this tool.')

    # Pad the selection with surrounding context so the AI understands
    # the scene, clamped to the canvas.
    cx = max(0, x1 - padding)
    cy = max(0, y1 - padding)
    cw = min(image.get_width(), x2 + padding) - cx
    ch = min(image.get_height(), y2 + padding) - cy

    tmpdir = tempfile.mkdtemp(prefix='ai-remove-selection-')

    Gimp.progress_init('Preparing image region...')
    ctx_png, mask_png = _render_context_and_mask(image, cx, cy, cw, ch,
                                                 4, tmpdir)

    Gimp.progress_set_text('Waiting for ComfyUI (%s)...'
                           % comfyui_client.MODELS[model])
    Gimp.progress_pulse()
    result = call_comfyui(model, ctx_png, mask_png, target)

    Gimp.progress_set_text('Compositing result...')
    image.undo_group_start()
    try:
        _composite_result(image, result, cx, cy, cw, ch, tmpdir)
    finally:
        image.undo_group_end()

    for fname in os.listdir(tmpdir):
        try:
            os.unlink(os.path.join(tmpdir, fname))
        except OSError:
            pass
    try:
        os.rmdir(tmpdir)
    except OSError:
        pass
    Gimp.progress_end()
    Gimp.displays_flush()


# ---------------------------------------------------------------- plug-in

def run(procedure, run_mode, image, drawables, config, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        gi.require_version('GimpUi', '3.0')
        from gi.repository import GimpUi
        GimpUi.init(procedure.get_name())
        dialog = GimpUi.ProcedureDialog(procedure=procedure, config=config)
        dialog.fill(None)
        if not dialog.run():
            dialog.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL,
                                               GLib.Error())
        dialog.destroy()

    try:
        _run_remove(image,
                    config.get_property('model'),
                    config.get_property('padding'),
                    config.get_property('target'))
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                           GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,
                                       GLib.Error())


class AiRemoveSelection(Gimp.PlugIn):
    def do_set_i18n(self, procname):
        return False

    def do_query_procedures(self):
        return ['ai-remove-selection']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name,
                                            Gimp.PDBProcType.PLUGIN,
                                            run, None)
        procedure.set_image_types('RGB*, GRAY*')
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_attribution('PhotoGIMP', 'PhotoGIMP contributors',
                                  '2026')
        procedure.set_menu_label('_Remove Selection (AI)...')
        procedure.set_documentation(
            'Remove the selected object with AI inpainting',
            'Removes whatever is inside the current selection and '
            'reconstructs the background with a local model, like '
            'Photoshop\'s Remove tool. '
            'Paint the selection with Quick Mask (Q) for a brush-like '
            'workflow.', name)

        model = Gimp.Choice.new()
        model.add('klein', 0,
                  'FLUX.2 klein (local, fast)', '')
        model.add('qwen', 1,
                  'Qwen-Image-Edit (local, slower)', '')
        procedure.add_choice_argument(
            'model', '_Model', 'Local ComfyUI model to use', model,
            'klein', GObject.ParamFlags.READWRITE)
        target = Gimp.Choice.new()
        target.add('auto', 2, 'Auto (retries as texture if the fill is flat)',
                   '')
        target.add('object', 0, 'An object (photo)', '')
        target.add('texture', 1,
                   'Text or marks over a texture (scan, print)', '')
        procedure.add_choice_argument(
            'target', '_What is selected',
            'An object is hidden from the AI so it is '
            'not redrawn; text or marks over a texture stay visible so '
            'the texture under them is continued; Auto tries the first '
            'and falls back to the second',
            target, 'auto', GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            'padding', 'Context _padding (px)',
            'Surrounding pixels sent to the AI for context',
            16, 1024, 128, GObject.ParamFlags.READWRITE)

        procedure.add_menu_path('<Image>/Filters/AI')
        return procedure


Gimp.main(AiRemoveSelection.__gtype__, sys.argv)
