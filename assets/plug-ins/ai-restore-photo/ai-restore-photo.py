#!/usr/bin/env python3
#
# AI Restore Photo: repair a scanned photo print in GIMP 3 with a local
# model (the photo-restore method).
#
# The model (through a running ComfyUI server, fully local) redraws the
# whole picture with the damage painted over: white and brown blotches,
# flakes, stains, scratches, creases, specks — or, with "Chemical burns",
# gold/orange flakes and rusty blotches. Its pixels are then kept ONLY
# where the print was damaged (restore_mask.py next to this file): the
# result is a new layer "Restored (AI)" whose layer mask is the damage
# the model repaired, over the untouched scan. Paint the mask black where
# the model changed something it should not have (a face, an expression)
# and white where damage was missed — the layer holds the model's whole
# picture, colour-matched to the scan, so any area can be revealed.
#
# With a selection, only damage inside the selection is repaired.
#
# Models: comfyui-klein (FLUX.2 klein, fast, default) / comfyui-qwen
# (Qwen-Image-Edit, slower; better on chemical burns, but it tends to
# repaint faces), through comfyui_client.py next to this file.
# Address: COMFYUI_URL or ~/.config/PhotoGIMP/comfyui-url
# (default http://127.0.0.1:8188). ComfyUI must be running.
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
gi.require_version('Gegl', '0.4')
from gi.repository import Gegl
from gi.repository import GLib, GObject, Gio

import comfyui_client
import restore_mask


# ------------------------------------------------------------- gimp helpers

def _export_flat(image, path):
    """Export the visible image (all layers, canvas size) as a PNG."""
    dup = image.duplicate()
    try:
        dup.flatten()
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup,
                       Gio.File.new_for_path(path), None)
    finally:
        dup.delete()


def _add_restored_layer(image, path):
    """Insert the repaired picture; its alpha (the damage) becomes the
    layer mask, so the mask can be painted to add or drop areas."""
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image,
                                 Gio.File.new_for_path(path))
    layer.set_name('Restored (AI)')
    image.insert_layer(layer, None, 0)
    layer.set_offsets(0, 0)
    mask = layer.create_mask(Gimp.AddMaskType.ALPHA_TRANSFER)
    layer.add_mask(mask)
    return layer, mask


def _limit_to_selection(image, mask):
    """Black out the layer mask outside the user's selection."""
    sel = Gimp.Selection.save(image)
    Gimp.context_push()
    try:
        Gimp.Selection.invert(image)
        Gimp.context_set_foreground(Gegl.Color.new('black'))
        mask.edit_fill(Gimp.FillType.FOREGROUND)
    finally:
        Gimp.context_pop()
        image.select_item(Gimp.ChannelOps.REPLACE, sel)
        image.remove_channel(sel)


def _run_restore(image, model, damage, threshold, min_area):
    _ok, has_selection, _x1, _y1, _x2, _y2 = Gimp.Selection.bounds(image)
    tmpdir = tempfile.mkdtemp(prefix='ai-restore-photo-')
    try:
        scan = os.path.join(tmpdir, 'scan.png')
        raw = os.path.join(tmpdir, 'model.png')
        repaired = os.path.join(tmpdir, 'repaired.png')

        Gimp.progress_init('Preparing the photo...')
        _export_flat(image, scan)
        with open(scan, 'rb') as f:
            scan_png = f.read()

        def progress(elapsed):
            Gimp.progress_set_text(
                'ComfyUI (%s) is repairing the photo... %d s — the first '
                'run loads the model and takes longer'
                % (comfyui_client.MODELS[model], elapsed))
            Gimp.progress_pulse()

        result = comfyui_client.restore(model, scan_png,
                                        burns=(damage == 'burns'),
                                        progress=progress)
        with open(raw, 'wb') as f:
            f.write(result)

        Gimp.progress_set_text('Finding the damage the model repaired...')
        Gimp.progress_pulse()
        regions, share = restore_mask.process(scan, raw, repaired,
                                              threshold, min_area)

        image.undo_group_start()
        try:
            _layer, mask = _add_restored_layer(image, repaired)
            if has_selection:
                _limit_to_selection(image, mask)
        finally:
            image.undo_group_end()
        Gimp.progress_end()
        Gimp.displays_flush()
        if regions == 0:
            Gimp.message(
                'The model changed nothing above the sensitivity threshold, '
                'so the layer mask is empty. Lower "Sensitivity threshold" '
                'or paint the mask white where you want the repair.')
        elif share > 0.5:
            Gimp.message(
                'The repair covers %d%% of the photo. Check faces and '
                'people: paint the "Restored (AI)" layer mask black where '
                'the model invented or changed something.' % (share * 100))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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
        _run_restore(image,
                     config.get_property('model'),
                     config.get_property('damage'),
                     config.get_property('threshold'),
                     config.get_property('min-area'))
    except Exception as e:
        Gimp.progress_end()
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                           GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,
                                       GLib.Error())


class AiRestorePhoto(Gimp.PlugIn):
    def do_set_i18n(self, procname):
        return False

    def do_query_procedures(self):
        return ['ai-restore-photo']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name,
                                            Gimp.PDBProcType.PLUGIN,
                                            run, None)
        procedure.set_image_types('RGB*')
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_attribution('gimp-setup', 'gimp-setup contributors',
                                  '2026')
        procedure.set_menu_label('Restore _Photo (AI)...')
        procedure.set_documentation(
            'Repair a damaged photo print with a local AI model',
            'Blotches, flakes, stains, scratches and specks of a scanned '
            'print are repainted by a local model; its pixels are kept '
            'only where the print was damaged, as a new layer whose mask '
            'can be painted to add or drop areas. With a selection, only '
            'damage inside it is repaired.', name)

        model = Gimp.Choice.new()
        model.add('klein', 0, 'FLUX.2 klein (local, fast)', '')
        model.add('qwen', 1, 'Qwen-Image-Edit (local, slower)', '')
        procedure.add_choice_argument(
            'model', '_Model', 'Local ComfyUI model to use', model,
            'klein', GObject.ParamFlags.READWRITE)
        damage = Gimp.Choice.new()
        damage.add('general', 0,
                   'Blotches, flakes, stains, scratches, specks', '')
        damage.add('burns', 1,
                   'Chemical burns (gold/orange flakes, rusty blotches)', '')
        procedure.add_choice_argument(
            'damage', '_Damage', 'What the print suffers from; chemical '
            'burns usually need Qwen-Image-Edit', damage, 'general',
            GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            'threshold', '_Sensitivity threshold',
            'How much the model must have changed a spot (0-255) for it to '
            'count as repaired damage: lower catches faint damage (white '
            'on white) but also takes changes that are not damage',
            5, 80, int(restore_mask.THRESHOLD), GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            'min-area', 'Smallest _repair (px)',
            'Changed spots smaller than this are ignored unless the change '
            'is strong (a moved highlight, a redrawn button)',
            0, 100000, restore_mask.MIN_AREA, GObject.ParamFlags.READWRITE)

        procedure.add_menu_path('<Image>/Filters/AI')
        return procedure


Gimp.main(AiRestorePhoto.__gtype__, sys.argv)
