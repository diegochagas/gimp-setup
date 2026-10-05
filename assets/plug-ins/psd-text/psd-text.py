#!/usr/bin/env python3
#
# PSD with editable text: opens and exports Photoshop files in GIMP 3
# keeping text layers EDITABLE in both programs.
#
#   Open (.psd): GIMP's own PSD loader brings the pixels, groups, masks,
#     blend modes and opacity; then every Photoshop Type layer, which that
#     loader rasterizes, is replaced by a native GIMP text layer (font,
#     size, colour, justification, tracking, leading, paragraph box or
#     point text, rotation, mixed bold/italic/colour/size runs), and every
#     Layer Style stroke / drop shadow / colour overlay becomes a
#     non-destructive Filters > Text Styling filter.
#   Export (.psd): GIMP's own PSD exporter writes the file, then every GIMP
#     text layer in it is turned back into a Photoshop Type layer and every
#     Text Styling outline / shadow into a live Layer Style, so the text is
#     still editable when the file is opened in Photoshop.
#
# Both procedures are registered with a lower priority value than GIMP's
# built-in PSD procedures, so GIMP picks them for .psd files: File > Open
# and File > Export As... "name.psd" use them without any extra step.
#
# The Photoshop text records are read and written by ag-psd under Node.js
# (psd_text_info.mjs / write_psd_text.mjs, ag-psd in node_modules next to
# this file). Node is the host's own binary (the GIMP Flatpak can run it
# from the home folder): PSD_TEXT_NODE, else the path written by gimp-setup
# to ~/.config/PhotoGIMP/node-path, else "node" on PATH. Without Node the
# file still opens / exports, through GIMP's own PSD support only.
#
# Text language for Type layers whose GIMP layer has none (an Adobe text
# engine code, e.g. 11 = Portuguese: Brazilian, 0 = English: USA):
# PSD_TEXT_LANGUAGE, else ~/.config/PhotoGIMP/psd-text-language, else 0.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
from gi.repository import GLib, GObject, Gio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psd_text_gimp as core            # noqa: E402
from psd_text_fonts import Fonts        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "PhotoGIMP")
LOAD_PROC = "file-psd-text-load"
EXPORT_PROC = "file-psd-text-export"
# GIMP uses the file procedure with the LOWEST priority value; the built-in
# PSD procedures have the default, 0.
PRIORITY = -10
NODE_TIMEOUT = 300


def read_config(name):
    try:
        with open(os.path.join(CONFIG_DIR, name)) as f:
            return f.read().strip()
    except OSError:
        return ""


def find_node():
    for cand in (os.environ.get("PSD_TEXT_NODE"), read_config("node-path"), shutil.which("node")):
        if cand and os.access(cand, os.X_OK):
            return cand
    # nvm installs, newest first: the Flatpak's PATH does not include them
    found = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")), reverse=True)
    return found[0] if found else None


def default_language():
    value = os.environ.get("PSD_TEXT_LANGUAGE") or read_config("psd-text-language")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def node_script(script, *args):
    """Run one of the .mjs scripts. Returns (ok, stdout, error text)."""
    node = find_node()
    if not node:
        return False, "", "Node.js not found (set PSD_TEXT_NODE or re-run gimp-setup)"
    if not os.path.isdir(os.path.join(HERE, "node_modules", "ag-psd")):
        return False, "", "ag-psd is not installed next to the plug-in (re-run gimp-setup)"
    try:
        r = subprocess.run([node, "--max-old-space-size=8192", os.path.join(HERE, script), *args],
                           capture_output=True, text=True, cwd=HERE, timeout=NODE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, "", str(e)
    err = [l for l in (r.stderr or "").strip().splitlines() if l.strip() and not l.lstrip().startswith("at ")]
    return r.returncode == 0, r.stdout, " / ".join(err[-3:])


def run_pdb(name, **args):
    proc = Gimp.get_pdb().lookup_procedure(name)
    config = proc.create_config()
    for key, value in args.items():
        config.set_property(key, value)
    result = proc.run(config)
    if result.index(0) != Gimp.PDBStatusType.SUCCESS:
        raise RuntimeError(f"{name} failed: {result.index(1) if result.length() > 1 else 'error'}")
    return result


def tell(run_mode, title, notes):
    """Show what was approximated, once per file, in interactive use."""
    # "info:" notes say how something was kept (e.g. rotated text became a
    # smart object), not that something was lost: not worth a dialog
    lines = sorted(n for n in notes if not n.startswith("info:"))
    if not lines or run_mode != Gimp.RunMode.INTERACTIVE:
        return
    more = len(lines) - 12
    text = "\n".join("• " + n for n in lines[:12]) + (f"\n… and {more} more" if more > 0 else "")
    Gimp.message(f"{title}\n{text}")


# ------------------------------------------------------------------ open

def load_psd(procedure, run_mode, file, metadata, flags, config, data):
    try:
        # NONINTERACTIVE: the interactive loader only shows a notice that text
        # layers will be rasterized, which this plug-in is here to avoid
        result = run_pdb("file-psd-load", run_mode=Gimp.RunMode.NONINTERACTIVE, file=file)
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                           GLib.Error(str(e))), flags
    image = result.index(1)
    path = file.get_path()
    notes = set()
    if path:
        try:
            convert_text_layers(image, path, notes)
        except Exception:
            notes.add("text layers left as pixels: " + traceback.format_exc().splitlines()[-1])
    tell(run_mode, f"{os.path.basename(path or '')}: opened with editable text, notes:", notes)
    return Gimp.ValueArray.new_from_values([
        GObject.Value(Gimp.PDBStatusType, Gimp.PDBStatusType.SUCCESS),
        GObject.Value(Gimp.Image, image),
    ]), flags


def convert_text_layers(image, path, notes):
    work = tempfile.mkdtemp(prefix="gimp-psd-text-")
    try:
        info_path = os.path.join(work, "info.json")
        ok, _out, err = node_script("psd_text_info.mjs", path, info_path)
        if not ok:
            notes.add(f"text layers left as pixels: {err}")
            return
        with open(info_path) as f:
            info = json.load(f)
        if not info.get("layers"):
            return
        fonts = Fonts()
        names = {run["font"] for l in info["layers"] if l.get("text") for run in l["text"]["runs"]}
        fonts_map = {n: fonts.to_gimp(n, {}) for n in names}
        Gimp.context_push()
        image.undo_disable()
        try:
            Gimp.context_set_interpolation(Gimp.InterpolationType.CUBIC)
            Gimp.context_set_transform_resize(Gimp.TransformResize.ADJUST)
            Gimp.Selection.none(image)
            # rotated text becomes a smart object: its XCF goes next to the PSD
            stem = os.path.splitext(os.path.basename(path))[0]
            contents_dir = os.path.join(os.path.dirname(path), stem + " smart objects")
            if not os.access(os.path.dirname(path), os.W_OK):
                contents_dir = os.path.join(GLib.get_user_data_dir(), "gimp-smart-objects", stem)
            core.apply_psd_text(image, info, fonts_map, notes, contents_dir=contents_dir)
        finally:
            image.undo_enable()
            Gimp.context_pop()
        image.clean_all()
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- export

def export_psd(procedure, run_mode, image, file, options, metadata, config, data):
    path = file.get_path()
    notes = set()
    work = tempfile.mkdtemp(prefix="gimp-psd-text-")
    copy = image.duplicate()
    try:
        copy.undo_disable()
        Gimp.Selection.none(copy)
        entries, to_hide = core.describe_image(copy, notes, default_language())
        raw = os.path.join(work, "gimp.psd")
        composite = None
        if entries and to_hide:
            # the flattened image inside the PSD (what viewers and thumbnails
            # show) keeps the outlines; the layers go without them, Photoshop
            # redraws them as Layer Styles
            composite = os.path.join(work, "gimp_full.psd")
            gimp_export(copy, composite, options)
            for f in to_hide:
                f.set_visible(False)
        gimp_export(copy, raw, options)
        if not entries:
            shutil.copyfile(raw, path)
            return success()

        fonts = Fonts()
        for e in entries:
            for run in (e.get("text") or {}).get("runs", []):
                ps, fb, fi, note = fonts.to_ps(run, (e["text"].get("font_back") or {}))
                run.update(font=ps, fauxBold=fb, fauxItalic=fi)
                if note:
                    notes.add(note)
        res = copy.get_resolution()
        info_path = os.path.join(work, "info.json")
        with open(info_path, "w") as f:
            json.dump({"width": copy.get_width(), "height": copy.get_height(), "yres": res.yresolution,
                       "composite_from": composite, "layers": entries}, f)

        tmp_out = os.path.join(work, "out.psd")
        ok, out, err = node_script("write_psd_text.mjs", raw, info_path, tmp_out)
        try:
            report = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            report = {}
        if ok and os.path.exists(tmp_out):
            notes.update(report.get("problems") or [])
            shutil.copyfile(tmp_out, path)
        else:
            # never lose the export: fall back to GIMP's own PSD (text as pixels)
            problems = report.get("problems") or [err or "write_psd_text.mjs failed"]
            notes.add("text was exported as pixels, not Type layers: " + "; ".join(problems))
            shutil.copyfile(composite or raw, path)
        tell(run_mode, f"{os.path.basename(path)}: exported, notes:", notes)
        return success()
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                           GLib.Error(f"PSD export failed: {e}"))
    finally:
        copy.delete()
        shutil.rmtree(work, ignore_errors=True)


def gimp_export(image, path, options):
    run_pdb("file-psd-export", run_mode=Gimp.RunMode.NONINTERACTIVE, image=image,
            file=Gio.File.new_for_path(path), options=None)


def success():
    return Gimp.ValueArray.new_from_values([
        GObject.Value(Gimp.PDBStatusType, Gimp.PDBStatusType.SUCCESS)
    ])


class PsdText(Gimp.PlugIn):
    def do_set_i18n(self, procname):
        return False

    def do_query_procedures(self):
        return [LOAD_PROC, EXPORT_PROC]

    def do_create_procedure(self, name):
        if name == LOAD_PROC:
            procedure = Gimp.LoadProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, load_psd, None)
            procedure.set_menu_label("Photoshop image (editable text)")
            procedure.set_documentation(
                "Loads a Photoshop PSD keeping its text layers editable",
                "GIMP's own PSD loader plus Type layers rebuilt as GIMP text layers "
                "and Layer Styles as Text Styling filters.",
                name)
            procedure.set_magics("0,string,8BPS")
        else:
            procedure = Gimp.ExportProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, False, export_psd, None)
            procedure.set_image_types("*")
            procedure.set_menu_label("Photoshop image (editable text)")
            procedure.set_documentation(
                "Exports a Photoshop PSD keeping text layers editable in Photoshop",
                "GIMP's own PSD export plus GIMP text layers written as Photoshop "
                "Type layers and Text Styling filters as Layer Styles.",
                name)
        procedure.set_mime_types("image/x-psd")
        procedure.set_extensions("psd")
        procedure.set_priority(PRIORITY)
        procedure.set_attribution("gimp-setup", "gimp-setup contributors", "2026")
        return procedure


Gimp.main(PsdText.__gtype__, sys.argv)
