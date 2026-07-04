#!/usr/bin/env python3
"""Multi-provider backends for the GIMP AI Plugin (gimp-setup patch).

Adds Google Gemini ("Nano Banana") and Stable Diffusion WebUI (local
AUTOMATIC1111) as alternatives to OpenAI for Generative Fill (inpainting)
and Image Generation. Pure standard library, no GIMP imports, so it can
be unit-tested outside GIMP.

Both entry points mirror the plugin's OpenAI call contracts:

    generate_image(provider, config, prompt, size)
        -> (success, message, png_bytes)

    edit_image(provider, config, image_b64, mask_png, prompt)
        -> (success, message, {"data": [{"b64_json": ...}]})

The edit mask follows OpenAI semantics on input (transparent pixels mark
the area to change); it is converted to the white-on-black mask that the
other providers understand.

API keys are looked up in the plugin config first, then environment
variables, then the shared gimp-setup key files, which exist both on the
host (~/.config/PhotoGIMP/) and inside the GIMP Flatpak sandbox
(~/.var/app/org.gimp.GIMP/config/PhotoGIMP/, reached here through
XDG_CONFIG_HOME).
"""

import base64
import json
import os
import re
import struct
import time
import urllib.error
import urllib.request
import zlib

PROVIDERS = {
    "openai": "OpenAI gpt-image-1 (online, paid key)",
    "gemini": "Google Gemini / Nano Banana (online, free key)",
    "sdwebui": "Stable Diffusion WebUI (local)",
}

GEMINI_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + GEMINI_MODEL + ":generateContent"
)
SDWEBUI_DEFAULT_URL = "http://127.0.0.1:7860"

FILL_INSTRUCTION = (
    "You are a photo editing engine. The first image is a photo. The second "
    "image is a mask of the same size: the WHITE area marks the region to "
    "edit. Inside that region only, do the following: {prompt}. Blend the "
    "result seamlessly with the rest of the photo, matching its lighting, "
    "colors, grain and perspective. Do not change anything outside the "
    "white area. Return only the edited photo at the same size, with no "
    "added text, borders or watermarks."
)


# --------------------------------------------------------------- key lookup

def _shared_key_paths(name):
    home = os.path.expanduser("~")
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))
    return [
        os.path.join(home, ".config", "PhotoGIMP", name),
        os.path.join(xdg, "PhotoGIMP", name),
    ]


def read_shared_key(name):
    """Read a key from the shared gimp-setup key files, if present."""
    for path in _shared_key_paths(name):
        try:
            with open(path, encoding="utf-8") as f:
                value = f.read().strip()
            if value:
                return value
        except OSError:
            continue
    return None


def get_openai_key(config):
    key = (config or {}).get("openai", {}).get("api_key")
    return key or os.environ.get("OPENAI_API_KEY") or read_shared_key(
        "openai-api-key")


def get_gemini_key(config):
    key = (config or {}).get("gemini", {}).get("api_key")
    return key or os.environ.get("GEMINI_API_KEY") or read_shared_key(
        "gemini-api-key")


def get_sdwebui_url(config):
    url = (config or {}).get("sdwebui", {}).get("url")
    return (url or os.environ.get("PHOTOGIMP_A1111_URL")
            or SDWEBUI_DEFAULT_URL)


def provider_key(provider, config):
    """Credential (or endpoint) that lets `provider` run; None if missing."""
    if provider == "gemini":
        return get_gemini_key(config)
    if provider == "sdwebui":
        return get_sdwebui_url(config)
    return get_openai_key(config)


def missing_key_message(provider):
    if provider == "gemini":
        return ("No Gemini API key found. Create a free key at "
                "https://aistudio.google.com/apikey and set it in "
                "Filters > AI > Settings, or save it to "
                "~/.config/PhotoGIMP/gemini-api-key")
    if provider == "sdwebui":
        return ("Stable Diffusion WebUI is not reachable. Launch "
                "AUTOMATIC1111 with --api (default http://127.0.0.1:7860).")
    return ("No OpenAI API key found. Create one at "
            "https://platform.openai.com/api-keys and set it in "
            "Filters > AI > Settings.")


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


def openai_mask_to_bw(mask_png):
    """Convert an OpenAI-style mask (transparent = edit) to white-on-black.

    Returns a grayscale PNG where WHITE marks the area to edit, which is
    what Gemini instructions and SD WebUI inpainting expect.
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


# -------------------------------------------------------------- HTTP layer

RATE_LIMIT_MESSAGE = (
    "Gemini rate limit reached (HTTP 429). The free tier only allows a few "
    "image requests per minute and per day. Wait a minute and try again, "
    "check your quota at https://aistudio.google.com/usage, or switch the "
    "provider in Filters > AI > Settings.")


class HTTPCallError(RuntimeError):
    """HTTP error with status code and body attached."""

    def __init__(self, code, body, url):
        super().__init__("HTTP %d from %s: %s" % (code, url, body[:300]))
        self.code = code
        self.body = body


def _http_json(url, payload, headers, timeout=300):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        raise HTTPCallError(e.code, body, url)
    except urllib.error.URLError as e:
        raise RuntimeError("Could not reach %s (%s)" % (url, e.reason))


def _retry_delay_seconds(body):
    """Retry delay suggested by a Gemini 429 response, if any."""
    match = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body)
    if match:
        return float(match.group(1))
    return None


# ----------------------------------------------------------------- Gemini

def _gemini_request(parts, api_key):
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }
    raw = None
    for attempt in (1, 2):
        try:
            raw = _http_json(GEMINI_URL, payload, {"x-goog-api-key": api_key})
            break
        except HTTPCallError as e:
            if e.code == 429:
                delay = _retry_delay_seconds(e.body)
                if attempt == 1 and delay is not None and delay <= 35:
                    time.sleep(delay)
                    continue
                raise RuntimeError(RATE_LIMIT_MESSAGE)
            raise
    reply = json.loads(raw)
    for candidate in reply.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    raise RuntimeError("Gemini returned no image. Reply: "
                       + raw.decode("utf-8", "replace")[:500])


def _gemini_generate(prompt, api_key):
    return _gemini_request([{"text": prompt}], api_key)


def _gemini_edit(image_png, mask_png, prompt, api_key):
    parts = [
        {"text": FILL_INSTRUCTION.format(prompt=prompt)},
        {"inlineData": {"mimeType": "image/png",
                        "data": base64.b64encode(image_png).decode()}},
        {"inlineData": {"mimeType": "image/png",
                        "data": base64.b64encode(mask_png).decode()}},
    ]
    return _gemini_request(parts, api_key)


# ------------------------------------------------------------------ SD WebUI

def _sdwebui_txt2img(prompt, url, width, height):
    payload = {
        "prompt": prompt,
        "negative_prompt": "text, watermark, low quality",
        "width": width,
        "height": height,
        "steps": 28,
        "cfg_scale": 7,
    }
    raw = _http_json(url.rstrip("/") + "/sdapi/v1/txt2img", payload, {})
    images = json.loads(raw).get("images")
    if not images:
        raise RuntimeError("Stable Diffusion WebUI returned no image.")
    return base64.b64decode(images[0])


def _sdwebui_img2img(image_png, mask_bw_png, prompt, url):
    width, height = png_size(image_png)
    payload = {
        "init_images": [base64.b64encode(image_png).decode()],
        "mask": base64.b64encode(mask_bw_png).decode(),
        "prompt": prompt,
        "negative_prompt": "text, watermark, low quality",
        "denoising_strength": 0.9,
        "inpainting_fill": 1,
        "inpainting_mask_invert": 0,
        "inpaint_full_res": False,
        "width": width,
        "height": height,
        "steps": 28,
        "cfg_scale": 7,
    }
    raw = _http_json(url.rstrip("/") + "/sdapi/v1/img2img", payload, {})
    images = json.loads(raw).get("images")
    if not images:
        raise RuntimeError("Stable Diffusion WebUI returned no image.")
    return base64.b64decode(images[0])


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
        credential = provider_key(provider, config)
        if not credential:
            return False, missing_key_message(provider), None

        if provider == "gemini":
            data = _gemini_generate(prompt, credential)
        elif provider == "sdwebui":
            width, height = _parse_size(size, (1024, 1024))
            data = _sdwebui_txt2img(prompt, credential, width, height)
        else:
            return False, "generate_image() does not handle OpenAI", None
        return True, "%s generation successful" % provider, data
    except Exception as e:  # noqa: BLE001 - reported to the GIMP dialog
        return False, str(e), None


def edit_image(provider, config, image_b64, mask_png, prompt):
    """Inpainting. Mask uses OpenAI semantics (transparent = edit).

    Returns (success, message, response_json) with an OpenAI-shaped
    response so the plugin's compositing code can be reused as-is.
    """
    try:
        credential = provider_key(provider, config)
        if not credential:
            return False, missing_key_message(provider), None

        image_png = (base64.b64decode(image_b64)
                     if isinstance(image_b64, str) else image_b64)
        mask_bw = openai_mask_to_bw(mask_png)

        if provider == "gemini":
            data = _gemini_edit(image_png, mask_bw, prompt, credential)
        elif provider == "sdwebui":
            data = _sdwebui_img2img(image_png, mask_bw, prompt, credential)
        else:
            return False, "edit_image() does not handle OpenAI", None

        response = {"data": [{"b64_json": base64.b64encode(data).decode()}]}
        return True, "%s edit successful" % provider, response
    except Exception as e:  # noqa: BLE001 - reported to the GIMP dialog
        return False, str(e), None
