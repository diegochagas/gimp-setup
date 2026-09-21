#!/usr/bin/env python3
"""Local ComfyUI backends for the GIMP AI Plugin (gimp-setup patch).

The only providers are the two fully local ComfyUI models (FLUX.2 klein
and Qwen-Image-Edit, through comfyui_client.py next to this file) for
Generative Fill (inpainting) and Image Generation. Pure standard library,
no GIMP imports, so it can be unit-tested outside GIMP.

Both entry points keep the call contracts of the plugin's original
online backend, so its compositing code is reused as-is:

    generate_image(provider, config, prompt, size)
        -> (success, message, png_bytes)

    edit_image(provider, config, image_b64, mask_png, prompt)
        -> (success, message, {"data": [{"b64_json": ...}]})

The edit mask arrives with the plugin's semantics (transparent pixels mark
the area to change); it is converted to the white-on-black mask that
comfyui_client understands.
"""

import base64
import struct
import zlib

import comfyui_client

PROVIDERS = {
    "comfyui-klein": "ComfyUI - FLUX.2 klein (local, fast)",
    "comfyui-qwen": "ComfyUI - Qwen-Image-Edit (local, slower)",
}

DEFAULT_PROVIDER = "comfyui-klein"

# provider id -> comfyui_client model
COMFYUI_MODELS = {"comfyui-klein": "klein", "comfyui-qwen": "qwen"}


def normalize_provider(provider):
    """`provider` if it is a known provider, else the default.

    Settings saved by earlier versions may name a provider that no longer
    exists (the online ones and Stable Diffusion WebUI were removed).
    """
    return provider if provider in PROVIDERS else DEFAULT_PROVIDER


# ---------------------------------------------------------------- endpoint

def get_comfyui_url(config):
    return comfyui_client.get_url((config or {}).get("comfyui", {}).get("url"))


def max_wait_seconds(provider, default):
    """How long the plugin waits for `provider` before giving up.

    Local ComfyUI models can take many minutes on their first run (the
    model is loaded from disk and partly kept in system RAM on small
    GPUs), far longer than the plugin's default wait.
    """
    if provider in COMFYUI_MODELS:
        return comfyui_client.TIMEOUT
    return default


def cancel(provider, config):
    """Stop a request the user cancelled."""
    if provider in COMFYUI_MODELS:
        comfyui_client.cancel(get_comfyui_url(config))


def provider_key(provider, config):
    """Endpoint that lets `provider` run (the ComfyUI server address)."""
    return get_comfyui_url(config)


def missing_key_message(provider):
    return comfyui_client.unreachable_message(comfyui_client.DEFAULT_URL)


# ------------------------------------------------------------- PNG helpers

def png_size(png_bytes):
    """(width, height) from a PNG header, or (None, None)."""
    if png_bytes[:8] != b"\x89PNG\r\n\x1a\n" or len(png_bytes) < 24:
        return None, None
    width, height = struct.unpack(">II", png_bytes[16:24])
    return width, height


def _decode_png(png_bytes):
    """Minimal PNG decoder: returns (width, height, channels, pixels).

    Supports 8-bit depth, color types 0 (gray), 2 (RGB), 4 (gray+alpha)
    and 6 (RGBA), non-interlaced — which covers everything GIMP exports
    here. Raises ValueError on anything else.
    """
    if png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")

    width = height = None
    color_type = None
    idat = b""
    pos = 8
    while pos + 8 <= len(png_bytes):
        length, ctype = struct.unpack(">I4s", png_bytes[pos:pos + 8])
        data = png_bytes[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            (width, height, bit_depth, color_type,
             _comp, _filt, interlace) = struct.unpack(">IIBBBBB", data)
            if bit_depth != 8:
                raise ValueError("unsupported bit depth %d" % bit_depth)
            if interlace != 0:
                raise ValueError("interlaced PNG not supported")
        elif ctype == b"IDAT":
            idat += data
        elif ctype == b"IEND":
            break
        pos += 12 + length

    channels_by_type = {0: 1, 2: 3, 4: 2, 6: 4}
    if color_type not in channels_by_type:
        raise ValueError("unsupported color type %s" % color_type)
    channels = channels_by_type[color_type]

    raw = zlib.decompress(idat)
    stride = width * channels
    pixels = bytearray(height * stride)
    previous = bytearray(stride)

    src = 0
    for row in range(height):
        filter_type = raw[src]
        src += 1
        line = bytearray(raw[src:src + stride])
        src += stride

        if filter_type == 1:    # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = previous[i]
                up_left = previous[i - channels] if i >= channels else 0
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                if pa <= pb and pa <= pc:
                    predictor = left
                elif pb <= pc:
                    predictor = up
                else:
                    predictor = up_left
                line[i] = (line[i] + predictor) & 0xFF
        elif filter_type != 0:
            raise ValueError("unknown PNG filter %d" % filter_type)

        pixels[row * stride:(row + 1) * stride] = line
        previous = line

    return width, height, channels, bytes(pixels)


def _encode_gray_png(width, height, gray_pixels):
    """Encode 8-bit grayscale pixels as a PNG."""
    def chunk(ctype, data):
        return (struct.pack(">I", len(data)) + ctype + data
                + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = b"".join(
        b"\x00" + gray_pixels[row * width:(row + 1) * width]
        for row in range(height)
    )
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def edit_mask_to_bw(mask_png):
    """Convert the plugin's edit mask (transparent = edit) to white-on-black.

    Returns a grayscale PNG where WHITE marks the area to edit, which is
    what comfyui_client expects.
    """
    width, height, channels, pixels = _decode_png(mask_png)
    gray = bytearray(width * height)
    if channels in (2, 4):        # has an alpha channel (last channel)
        alpha_offset = channels - 1
        for i in range(width * height):
            alpha = pixels[i * channels + alpha_offset]
            gray[i] = 255 if alpha < 128 else 0
    else:                         # no alpha: treat bright pixels as edit area
        for i in range(width * height):
            gray[i] = 255 if pixels[i * channels] >= 128 else 0
    return _encode_gray_png(width, height, bytes(gray))


# -------------------------------------------------------------- entry points

def _parse_size(size, default=(1024, 1024)):
    try:
        width, height = str(size).lower().split("x")
        return int(width), int(height)
    except (ValueError, AttributeError):
        return default


def generate_image(provider, config, prompt, size="auto"):
    """Text-to-image. Returns (success, message, png_bytes)."""
    try:
        provider = normalize_provider(provider)
        url = provider_key(provider, config)

        # Text-to-image always runs on FLUX.2 klein: Qwen-Image-Edit is an
        # editing model.
        width, height = _parse_size(size, (1024, 1024))
        data = comfyui_client.generate(prompt, width, height, url)
        return True, "%s generation successful" % provider, data
    except Exception as e:  # noqa: BLE001 - reported to the GIMP dialog
        return False, str(e), None


def edit_image(provider, config, image_b64, mask_png, prompt):
    """Inpainting. Mask: transparent = edit (see edit_mask_to_bw).

    Returns (success, message, response_json) shaped like the plugin's
    original online backend so its compositing code can be reused as-is.
    """
    try:
        provider = normalize_provider(provider)
        url = provider_key(provider, config)

        image_png = (base64.b64decode(image_b64)
                     if isinstance(image_b64, str) else image_b64)
        mask_bw = edit_mask_to_bw(mask_png)

        data = comfyui_client.inpaint(COMFYUI_MODELS[provider], image_png,
                                      mask_bw, prompt, url)

        response = {"data": [{"b64_json": base64.b64encode(data).decode()}]}
        return True, "%s edit successful" % provider, response
    except Exception as e:  # noqa: BLE001 - reported to the GIMP dialog
        return False, str(e), None
