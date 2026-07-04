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
# installed by gimp-setup, which shares the same backends and API keys.
#
# Backends:
#   gemini   Google Gemini image model ("Nano Banana"), free API tier.
#            Key from https://aistudio.google.com/apikey, stored in
#            ~/.config/PhotoGIMP/gemini-api-key (host and/or Flatpak
#            sandbox copy) or the GEMINI_API_KEY environment variable.
#   iopaint  Local inpainting (LaMa model), no key needed:
#            pipx install iopaint && iopaint start --model=lama --port=8080
#            Serves on http://127.0.0.1:8080 (override: PHOTOGIMP_IOPAINT_URL)
#   sdwebui  Local Stable Diffusion WebUI (AUTOMATIC1111) with --api on
#            http://127.0.0.1:7860 (override: PHOTOGIMP_A1111_URL)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import base64
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
gi.require_version('Gegl', '0.4')
from gi.repository import Gegl
from gi.repository import GLib, GObject, Gio

GEMINI_MODEL = os.environ.get('GEMINI_IMAGE_MODEL', 'gemini-2.5-flash-image')
GEMINI_URL = ('https://generativelanguage.googleapis.com/v1beta/models/'
              + GEMINI_MODEL + ':generateContent')
IOPAINT_URL = os.environ.get('PHOTOGIMP_IOPAINT_URL', 'http://127.0.0.1:8080')
A1111_URL = os.environ.get('PHOTOGIMP_A1111_URL', 'http://127.0.0.1:7860')

REMOVE_INSTRUCTION = (
    'You are a photo retouching engine. The first image is a photo. The '
    'second image is a mask of the same size: the WHITE area marks an '
    'unwanted object. Remove that object completely and reconstruct the '
    'background behind it so the photo looks natural, matching the '
    'surrounding texture, lighting, grain and perspective. Do not change '
    'anything outside the white area. Return only the edited photo at the '
    'same size, with no added text, borders or watermarks.')


# ---------------------------------------------------------------- backends

def _gemini_api_key():
    """Find the Gemini key: env var, host key file, sandbox key file.

    Under Flatpak GIMP, GLib.get_user_config_dir() points inside the
    sandbox (~/.var/app/org.gimp.GIMP/config), while gimp-setup writes
    the key to the host ~/.config — so both locations are probed.
    """
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if key:
        return key
    candidates = [
        os.path.join(os.path.expanduser('~'), '.config',
                     'PhotoGIMP', 'gemini-api-key'),
        os.path.join(GLib.get_user_config_dir(),
                     'PhotoGIMP', 'gemini-api-key'),
    ]
    for key_file in candidates:
        try:
            with open(key_file, encoding='utf-8') as f:
                key = f.read().strip()
            if key:
                return key
        except OSError:
            continue
    return ''


RATE_LIMIT_MESSAGE = (
    'Gemini rate limit reached (HTTP 429). The free tier only allows a few '
    'image requests per minute and per day. Wait a minute and try again, '
    'check your quota at https://aistudio.google.com/usage, or switch the '
    'Backend to IOPaint (local), which has no limits.')


def _http_json(url, payload, headers, timeout=300):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    for name, value in headers.items():
        req.add_header(name, value)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _retry_delay_seconds(body):
    """Retry delay suggested by a Gemini 429 response, if any."""
    match = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body)
    if match:
        return float(match.group(1))
    return None


def _gemini_post(payload, key):
    """POST to Gemini, retrying once when it suggests a short delay."""
    for attempt in (1, 2):
        try:
            return _http_json(GEMINI_URL, payload, {'x-goog-api-key': key})
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode('utf-8', 'replace')
            except Exception:
                body = ''
            if e.code == 429:
                delay = _retry_delay_seconds(body)
                if attempt == 1 and delay is not None and delay <= 35:
                    Gimp.progress_set_text(
                        'Gemini rate limit — retrying in %.0fs...' % delay)
                    time.sleep(delay)
                    continue
                raise RuntimeError(RATE_LIMIT_MESSAGE)
            raise RuntimeError('Gemini API error %d: %s'
                               % (e.code, body[:300]))


def call_gemini(context_png, mask_png):
    key = _gemini_api_key()
    if not key:
        raise RuntimeError(
            'No Gemini API key found. Create a free key at '
            'https://aistudio.google.com/apikey and either export '
            'GEMINI_API_KEY or save it to ~/.config/PhotoGIMP/gemini-api-key')
    payload = {
        'contents': [{'parts': [
            {'text': REMOVE_INSTRUCTION},
            {'inlineData': {'mimeType': 'image/png',
                            'data': base64.b64encode(context_png).decode()}},
            {'inlineData': {'mimeType': 'image/png',
                            'data': base64.b64encode(mask_png).decode()}},
        ]}],
        'generationConfig': {'responseModalities': ['IMAGE', 'TEXT']},
    }
    raw = _gemini_post(payload, key)
    reply = json.loads(raw)
    for candidate in reply.get('candidates', []):
        for part in candidate.get('content', {}).get('parts', []):
            inline = part.get('inlineData') or part.get('inline_data')
            if inline and inline.get('data'):
                return base64.b64decode(inline['data'])
    raise RuntimeError('Gemini returned no image. Full reply: '
                       + raw.decode('utf-8', 'replace')[:800])


def call_iopaint(context_png, mask_png):
    payload = {
        'image': base64.b64encode(context_png).decode(),
        'mask': base64.b64encode(mask_png).decode(),
    }
    try:
        return _http_json(IOPAINT_URL.rstrip('/') + '/api/v1/inpaint',
                          payload, {})
    except urllib.error.URLError as e:
        raise RuntimeError(
            'Could not reach IOPaint at %s (%s). Start it with:\n'
            '  pipx install iopaint\n'
            '  iopaint start --model=lama --port=8080' % (IOPAINT_URL, e))


def call_sdwebui(context_png, mask_png, width, height):
    payload = {
        'init_images': [base64.b64encode(context_png).decode()],
        'mask': base64.b64encode(mask_png).decode(),
        'prompt': 'background',
        'negative_prompt': 'text, watermark, low quality',
        'denoising_strength': 0.9,
        'inpainting_fill': 1,          # keep original pixels as base
        'inpainting_mask_invert': 0,
        'inpaint_full_res': False,     # context is already cropped
        'width': width,
        'height': height,
        'steps': 28,
        'cfg_scale': 7,
    }
    try:
        raw = _http_json(A1111_URL.rstrip('/') + '/sdapi/v1/img2img',
                         payload, {})
    except urllib.error.URLError as e:
        raise RuntimeError(
            'Could not reach Stable Diffusion WebUI at %s (%s). Launch '
            'AUTOMATIC1111 with the --api flag.' % (A1111_URL, e))
    images = json.loads(raw).get('images')
    if not images:
        raise RuntimeError('Stable Diffusion WebUI returned no image.')
    return base64.b64decode(images[0])


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


def _run_remove(image, backend, padding):
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

    Gimp.progress_set_text('Waiting for %s...' % backend)
    Gimp.progress_pulse()
    if backend == 'iopaint':
        result = call_iopaint(ctx_png, mask_png)
    elif backend == 'sdwebui':
        result = call_sdwebui(ctx_png, mask_png, cw, ch)
    else:
        result = call_gemini(ctx_png, mask_png)

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
                    config.get_property('backend'),
                    config.get_property('padding'))
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
            'reconstructs the background, like Photoshop\'s Remove tool. '
            'Paint the selection with Quick Mask (Q) for a brush-like '
            'workflow.', name)

        backend = Gimp.Choice.new()
        backend.add('gemini', 0, 'Gemini / Nano Banana (online, free key)', '')
        backend.add('iopaint', 1, 'IOPaint - LaMa (local)', '')
        backend.add('sdwebui', 2, 'Stable Diffusion WebUI (local)', '')
        procedure.add_choice_argument(
            'backend', '_Backend', 'AI service to use', backend, 'gemini',
            GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            'padding', 'Context _padding (px)',
            'Surrounding pixels sent to the AI for context',
            16, 1024, 128, GObject.ParamFlags.READWRITE)

        procedure.add_menu_path('<Image>/Filters/AI')
        return procedure


Gimp.main(AiRemoveSelection.__gtype__, sys.argv)
