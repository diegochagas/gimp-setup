#!/usr/bin/env python3
#
# PhotoGIMP AI tools: Photoshop-style "Remove" and "Generative Fill" for GIMP 3.
#
#   AI Remove       — inpaints (removes) whatever is inside the current
#                     selection, reconstructing the background.
#                     Photoshop-like workflow: press Q (Quick Mask), paint
#                     over the object with a brush (semi-transparent red
#                     overlay), press Q again, then run this.
#
#   Generative Fill — fills the current selection from a text prompt,
#                     blending with the surrounding image. Only pixels
#                     inside the selection are changed; the result comes
#                     back as a separate layer with a feathered mask.
#
# Backends:
#   gemini   Google Gemini image model ("Nano Banana"), free API tier.
#            Key from https://aistudio.google.com/apikey — put it in the
#            GEMINI_API_KEY environment variable or in the file
#            ~/.config/PhotoGIMP/gemini-api-key
#   iopaint  Local inpainting (LaMa model), no prompt support, great for
#            Remove:  pipx install iopaint && iopaint start --model=lama
#            Serves on http://127.0.0.1:8080 (override: PHOTOGIMP_IOPAINT_URL)
#   sdwebui  Local Stable Diffusion WebUI (AUTOMATIC1111) with --api, for
#            prompt-based fills on http://127.0.0.1:7860
#            (override: PHOTOGIMP_A1111_URL)
#
# Adobe Firefly is not included: its Generative Fill API requires paid
# enterprise OAuth credentials, with no free personal tier.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import base64
import json
import os
import sys
import tempfile
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

FILL_INSTRUCTION = (
    'You are a photo editing engine. The first image is a photo. The '
    'second image is a mask of the same size: the WHITE area marks the '
    'region to edit. Inside that region only, do the following: {prompt}. '
    'Blend the result seamlessly with the rest of the photo, matching its '
    'lighting, colors, grain and perspective. Do not change anything '
    'outside the white area. Return only the edited photo at the same '
    'size, with no added text, borders or watermarks.')


# ---------------------------------------------------------------- backends

def _gemini_api_key():
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if key:
        return key
    key_file = os.path.join(GLib.get_user_config_dir(),
                            'PhotoGIMP', 'gemini-api-key')
    try:
        with open(key_file, encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


def _http_json(url, payload, headers, timeout=300):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    for name, value in headers.items():
        req.add_header(name, value)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def call_gemini(context_png, mask_png, instruction):
    key = _gemini_api_key()
    if not key:
        raise RuntimeError(
            'No Gemini API key found. Create a free key at '
            'https://aistudio.google.com/apikey and either export '
            'GEMINI_API_KEY or save it to ~/.config/PhotoGIMP/gemini-api-key')
    payload = {
        'contents': [{'parts': [
            {'text': instruction},
            {'inlineData': {'mimeType': 'image/png',
                            'data': base64.b64encode(context_png).decode()}},
            {'inlineData': {'mimeType': 'image/png',
                            'data': base64.b64encode(mask_png).decode()}},
        ]}],
        'generationConfig': {'responseModalities': ['IMAGE', 'TEXT']},
    }
    raw = _http_json(GEMINI_URL, payload, {'x-goog-api-key': key})
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


def call_sdwebui(context_png, mask_png, prompt, width, height, denoising):
    payload = {
        'init_images': [base64.b64encode(context_png).decode()],
        'mask': base64.b64encode(mask_png).decode(),
        'prompt': prompt,
        'negative_prompt': 'text, watermark, low quality',
        'denoising_strength': denoising,
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


def _composite_result(image, result_bytes, cx, cy, cw, ch, layer_name,
                      tmpdir):
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
    layer.set_name(layer_name)

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


def _run_ai(procedure, image, mode, backend, prompt, padding):
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

    grow = 4 if mode == 'remove' else 0
    tmpdir = tempfile.mkdtemp(prefix='photogimp-ai-')

    Gimp.progress_init('Preparing image region...')
    ctx_png, mask_png = _render_context_and_mask(image, cx, cy, cw, ch,
                                                 grow, tmpdir)

    Gimp.progress_set_text('Waiting for %s...' % backend)
    Gimp.progress_pulse()
    if backend == 'iopaint':
        if mode == 'fill':
            raise RuntimeError('IOPaint (LaMa) cannot use text prompts. '
                               'Pick the Gemini or Stable Diffusion WebUI '
                               'backend for Generative Fill.')
        result = call_iopaint(ctx_png, mask_png)
    elif backend == 'sdwebui':
        sd_prompt = prompt if mode == 'fill' else 'background'
        denoise = 1.0 if mode == 'fill' else 0.9
        result = call_sdwebui(ctx_png, mask_png, sd_prompt, cw, ch, denoise)
    else:
        instruction = (REMOVE_INSTRUCTION if mode == 'remove'
                       else FILL_INSTRUCTION.format(prompt=prompt))
        result = call_gemini(ctx_png, mask_png, instruction)

    Gimp.progress_set_text('Compositing result...')
    name = ('AI Remove' if mode == 'remove'
            else 'Generative Fill: %s' % prompt)
    image.undo_group_start()
    try:
        _composite_result(image, result, cx, cy, cw, ch, name, tmpdir)
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
    name = procedure.get_name()
    mode = 'remove' if name == 'photogimp-ai-remove' else 'fill'

    if run_mode == Gimp.RunMode.INTERACTIVE:
        gi.require_version('GimpUi', '3.0')
        from gi.repository import GimpUi
        GimpUi.init(name)
        dialog = GimpUi.ProcedureDialog(procedure=procedure, config=config)
        dialog.fill(None)
        if not dialog.run():
            dialog.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL,
                                               GLib.Error())
        dialog.destroy()

    backend = config.get_property('backend')
    padding = config.get_property('padding')
    prompt = config.get_property('prompt') if mode == 'fill' else ''
    if mode == 'fill' and not prompt.strip():
        return procedure.new_return_values(
            Gimp.PDBStatusType.CALLING_ERROR,
            GLib.Error('Type a prompt describing what to generate.'))

    try:
        _run_ai(procedure, image, mode, backend, prompt, padding)
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                           GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,
                                       GLib.Error())


class PhotoGimpAI(Gimp.PlugIn):
    def do_set_i18n(self, procname):
        return False

    def do_query_procedures(self):
        return ['photogimp-ai-remove', 'photogimp-ai-generative-fill']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name,
                                            Gimp.PDBProcType.PLUGIN,
                                            run, None)
        procedure.set_image_types('RGB*, GRAY*')
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_attribution('PhotoGIMP', 'PhotoGIMP contributors',
                                  '2026')

        backend = Gimp.Choice.new()
        backend.add('gemini', 0, 'Gemini / Nano Banana (online, free key)', '')
        if name == 'photogimp-ai-remove':
            backend.add('iopaint', 1, 'IOPaint - LaMa (local)', '')
        backend.add('sdwebui', 2, 'Stable Diffusion WebUI (local)', '')

        if name == 'photogimp-ai-remove':
            procedure.set_menu_label('_Remove Selection (AI)...')
            procedure.set_documentation(
                'Remove the selected object with AI inpainting',
                'Removes whatever is inside the current selection and '
                'reconstructs the background, like Photoshop\'s Remove '
                'tool. Paint the selection with Quick Mask (Q) for a '
                'brush-like workflow.', name)
        else:
            procedure.set_menu_label('_Generative Fill...')
            procedure.set_documentation(
                'Fill the selection from a text prompt with AI',
                'Replaces the content of the current selection following '
                'a text prompt, blended with the surrounding image, like '
                'Photoshop\'s Generative Fill. The result is added as a '
                'separately masked layer.', name)
            procedure.add_string_argument(
                'prompt', '_Prompt',
                'What to generate inside the selection', '',
                GObject.ParamFlags.READWRITE)

        procedure.add_choice_argument(
            'backend', '_Backend', 'AI service to use', backend, 'gemini',
            GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            'padding', 'Context _padding (px)',
            'Surrounding pixels sent to the AI for context',
            16, 1024, 128, GObject.ParamFlags.READWRITE)

        procedure.add_menu_path('<Image>/Filters/AI')
        if name == 'photogimp-ai-generative-fill':
            procedure.add_menu_path('<Image>/Edit')

        return procedure


Gimp.main(PhotoGimpAI.__gtype__, sys.argv)
