#!/usr/bin/env python3
"""Damage mask for AI Restore Photo (numpy + scipy + Pillow, no GIMP).

The model redraws the whole scanned print with its damage repaired; this
keeps its pixels ONLY where the print was damaged, so every undamaged
pixel stays the scan's own. Same method as the photo-restore project
(restore-photos/scripts/restore.py), minus what needs OpenCV (face
guard, Poisson blending, affine alignment):

  1. align: the model's picture is shifted onto the scan (phase
     correlation, translation only);
  2. match_colors: its colours are fitted to the scan's, per channel,
     on the pixels the model left alone;
  3. damage_mask: where the two still differ (blurred mean |diff| above
     `threshold`) the model repaired something. Changed blobs closer
     than GROUP_PX form one region; a region is kept when its changed
     area reaches `min_area` px, or when it is small but the change is
     strong. The result is grown GROW px and feathered FEATHER px.

GIMP's Flatpak Python ships numpy, scipy and Pillow. Test outside GIMP:

    restore_mask.py scan.png model.png out.png [threshold] [min_area]

out.png is the aligned, colour-matched model picture with the mask as
its alpha channel (the plug-in turns that into a layer mask).
"""

import sys

import numpy as np
from PIL import Image
from scipy import ndimage

THRESHOLD = 22.0   # 0-255 blurred mean difference that counts as repaired
MIN_AREA = 300     # px of change a region needs (smaller: a moved highlight)
GROUP_PX = 20      # changed blobs closer than this form one region
BLUR_SIGMA = 4
GROW = 3
FEATHER = 4
MAX_SHIFT = 0.03   # a larger "shift" is a wrong phase-correlation peak


def load_rgb(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)


def _gray(rgb):
    return rgb.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)


def align(orig, gen):
    """Shift `gen` onto `orig` by the translation phase correlation finds.
    The strip the shift uncovers gets the scan's own pixels."""
    a, b = _gray(orig), _gray(gen)
    step = max(1, int(max(a.shape) / 1024))
    a, b = a[::step, ::step], b[::step, ::step]
    fa, fb = np.fft.fft2(a - a.mean()), np.fft.fft2(b - b.mean())
    cross = fa * np.conj(fb)
    corr = np.fft.ifft2(cross / (np.abs(cross) + 1e-6)).real
    dy, dx = np.unravel_index(np.argmax(corr), corr.shape)
    h, w = corr.shape
    dy = (dy - h if dy > h // 2 else dy) * step
    dx = (dx - w if dx > w // 2 else dx) * step
    H, W = orig.shape[:2]
    if (dx == 0 and dy == 0) or abs(dy) > MAX_SHIFT * H or abs(dx) > MAX_SHIFT * W:
        return gen
    out = orig.copy()
    ys, yd = (slice(0, H - dy), slice(dy, H)) if dy >= 0 else (slice(-dy, H), slice(0, H + dy))
    xs, xd = (slice(0, W - dx), slice(dx, W)) if dx >= 0 else (slice(-dx, W), slice(0, W + dx))
    out[yd, xd] = gen[ys, xs]
    return out


def match_colors(orig, gen):
    """Per-channel linear fit of gen onto orig, using only the pixels the
    model did not change much (found iteratively). Bright colourless
    pixels of the scan (paper showing through the damage) never take
    part; an implausible fit keeps the model's colours for that channel."""
    a, b = orig.astype(np.float32), gen.astype(np.float32)
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1) * 255, 0)
    ok = ~((mx >= 215) & (sat <= 50))
    d = ndimage.gaussian_filter(np.abs(b - a).mean(axis=2), 3)
    keep = ok & (d <= np.percentile(d[ok], 60)) if ok.sum() > 2000 else ok
    fitted = b.copy()
    for _ in range(3):
        if keep.sum() < 2000:
            break
        fitted = b.copy()
        for c in range(3):
            x, y = b[:, :, c][keep], a[:, :, c][keep]
            if x.std() < 1:
                continue
            k, m = np.polyfit(x, y, 1)
            if 0.6 <= k <= 1.5 and abs(m) <= 60:
                fitted[:, :, c] = b[:, :, c] * k + m
        d = ndimage.gaussian_filter(np.abs(fitted - a).mean(axis=2), 3)
        keep = ok & (d < 20)
        if keep.mean() < 0.05:
            keep = ok & (d <= np.percentile(d[ok], 30))
    return np.clip(fitted + 0.5, 0, 255).astype(np.uint8)


def damage_mask(orig, gen, threshold=THRESHOLD, min_area=MIN_AREA):
    """Feathered 0-255 mask of the regions the model repaired, and the
    number of regions kept."""
    d = ndimage.gaussian_filter(
        np.abs(gen.astype(np.float32) - orig.astype(np.float32)).mean(axis=2), BLUR_SIGMA)
    hard = ndimage.binary_opening(d > threshold, structure=np.ones((5, 5), bool))
    grouped = ndimage.maximum_filter(hard, size=2 * GROUP_PX + 1)
    labels, n = ndimage.label(grouped, structure=np.ones((3, 3), int))
    labels = np.where(hard, labels, 0)
    index = np.arange(1, n + 1)
    areas = ndimage.sum_labels(hard, labels, index)
    strength = ndimage.mean(d, labels, index) if n else np.array([])
    keep = (areas >= min_area) | ((areas >= 80) & (strength >= 2 * threshold))
    lut = np.zeros(n + 1, bool)
    lut[1:] = keep
    mask = lut[labels]
    if GROW:
        mask = ndimage.maximum_filter(mask, size=2 * GROW + 1)
    alpha = np.maximum(ndimage.gaussian_filter(mask.astype(np.float32), FEATHER), mask)
    return np.clip(alpha * 255 + 0.5, 0, 255).astype(np.uint8), int(keep.sum())


def process(scan_path, model_path, out_path, threshold=THRESHOLD, min_area=MIN_AREA):
    """Write the repaired layer (RGBA, alpha = damage mask) to out_path.
    Returns (regions kept, share of the image masked)."""
    orig = load_rgb(scan_path)
    gen = load_rgb(model_path)
    if gen.shape != orig.shape:
        gen = np.asarray(Image.fromarray(gen).resize(
            (orig.shape[1], orig.shape[0]), Image.LANCZOS))
    gen = match_colors(orig, align(orig, gen))
    alpha, regions = damage_mask(orig, gen, threshold, min_area)
    Image.fromarray(np.dstack([gen, alpha]), "RGBA").save(out_path)
    return regions, float((alpha > 127).mean())


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    args = sys.argv[1:4] + [float(v) for v in sys.argv[4:6]]
    found, share = process(*args)
    print("%d regions, %.1f%% of the image" % (found, share * 100))
