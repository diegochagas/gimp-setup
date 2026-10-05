#!/usr/bin/env python3
#
# Layer via Copy / Layer via Cut: Photoshop's Ctrl+J and Ctrl+Shift+J.
#
#   Layer > Layer via Copy    new layer from the selected area (no selection:
#                             duplicate the layer)
#   Layer > Layer via Cut     the same, and clear that area from the layer
#
# gimp-setup's Photoshop keymap (features/photoshop-keymap.sh) puts them on
# Ctrl+J and Ctrl+Shift+J. Each is one undo step. Logic: layer_via.py.
# Same plug-in as GIMPhoto's (github.com/diegochagas/gimphoto, plugins/).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import os
import sys

import gi

gi.require_version("Gimp", "3.0")
from gi.repository import Gimp, GLib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from layer_via import layer_via

COPY_PROC = "layer-via-copy"
CUT_PROC = "layer-via-cut"
MENU = "<Image>/Layer"


def run(procedure, run_mode, image, drawables, config, data):
    image.undo_group_start()
    try:
        layer_via(image, cut=procedure.get_name() == CUT_PROC)
    except ValueError as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


class LayerVia(Gimp.PlugIn):
    def do_set_i18n(self, procname):
        return False

    def do_query_procedures(self):
        return [COPY_PROC, CUT_PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        procedure.set_image_types("*")
        procedure.set_attribution("gimp-setup", "gimp-setup contributors", "2026")
        if name == COPY_PROC:
            # several layers: duplicated, as Ctrl+J without a selection
            procedure.set_sensitivity_mask(
                Gimp.ProcedureSensitivityMask.DRAWABLE | Gimp.ProcedureSensitivityMask.DRAWABLES
            )
            label = "Layer via _Copy"
            blurb = "New layer from the selected area (no selection: duplicate the layer)"
        else:
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
            label = "Layer via Cu_t"
            blurb = "New layer from the selected area, cleared from the layer"
        procedure.set_menu_label(label)
        procedure.set_documentation(blurb, blurb + " (Photoshop's Layer via Copy / Cut).", name)
        procedure.add_menu_path(MENU)
        return procedure


Gimp.main(LayerVia.__gtype__, sys.argv)
