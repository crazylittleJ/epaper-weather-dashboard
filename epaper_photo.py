#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spectra 6 (E6) photo pipeline for Waveshare e-Paper (default: 7.3" 800x480).

Pipeline: fit/crop -> linear light -> tone map to panel DR -> local contrast
          -> saturation pre-comp -> serpentine FS dither in linear space
          -> nominal-colour RGB image -> Waveshare getbuffer() -> panel.

Usage:  python3 epaper_photo.py photo.jpg
        python3 epaper_photo.py photo.jpg --preview /tmp/p.png   # PNG only
        python3 epaper_photo.py --calib    # show 6-colour chart, then measure it
"""

import sys, os, time, logging
import numpy as np
from PIL import Image, ImageFilter

libdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

# ---- panel selection: change these two lines when swapping panels ----
DRIVER = "epd7in3e"       # 4in0e -> "epd4in0e" | 7.3in E6 -> "epd7in3e"
W, H = 800, 480           # 4in0e -> 600, 400    | 7.3in E6 -> 800, 480
# ----------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 1. PANEL PALETTE  —  REPLACE THESE WITH YOUR OWN MEASURED VALUES.
#    Run with --calib, photograph the panel head-on under daylight / D65,
#    sample the centre of each block in an image editor, paste the RGB here.
#    These defaults are typical E6 values, not your unit.
# ---------------------------------------------------------------------------
PALETTE_SRGB = np.array([
    [ 28,  28,  28],   # black
    [215, 215, 210],   # white
    [190, 170,  60],   # yellow
    [150,  50,  50],   # red
    [ 45,  65, 125],   # blue
    [ 60, 110,  80],   # green
], dtype=np.float64)

# Legacy: only used by pack(). show() goes through getbuffer(), which owns the
# per-panel colour codes, so this table does NOT need changing per panel.
# Panel colour codes for 4inch e-Paper (E), per Waveshare wiki:
#   Black 0x0, White 0x1, Green 0x2, Blue 0x3, Red 0x4, Yellow 0x5
# Order below must match PALETTE_SRGB above.
PANEL_CODE = np.array([0x0, 0x1, 0x5, 0x4, 0x3, 0x2], dtype=np.uint8)

# Index constants into PALETTE_SRGB (used by the dashboard overlay)
I_BLACK, I_WHITE, I_YELLOW, I_RED, I_BLUE, I_GREEN = range(6)

# Nominal (idealised) primaries that Waveshare's getbuffer() matches against.
# Same order as PALETTE_SRGB. We dither against the MEASURED palette but hand
# getbuffer() the NOMINAL one, so its nearest-colour match is exact and lossless
# and we inherit its rotation + nibble packing instead of reimplementing them.
NOMINAL_SRGB = np.array([
    [  0,   0,   0],   # black
    [255, 255, 255],   # white
    [255, 255,   0],   # yellow
    [255,   0,   0],   # red
    [  0,   0, 255],   # blue
    [  0, 255,   0],   # green
], dtype=np.uint8)


def to_epd_image(idx):
    """Index array -> RGB PIL image in nominal panel colours, for getbuffer()."""
    return Image.fromarray(NOMINAL_SRGB[idx], "RGB")

# Tuning knobs
SATURATION   = 1.25   # pre-boost; dithering desaturates
LOCAL_RADIUS = 3.0    # unsharp radius (px)
LOCAL_AMOUNT = 0.55   # 0 = off, 1.0 = strong
BLACK_LIFT   = 0.02   # keep a little detail out of crushed shadows
EXPOSURE     = 1.25   # >1 lifts midtones; the panel's low contrast eats them

# ---------------------------------------------------------------------------


def srgb_to_linear(a):
    a = np.asarray(a, dtype=np.float64) / 255.0
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(a):
    a = np.clip(a, 0.0, 1.0)
    s = np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)
    return s * 255.0


def luminance(lin):
    return lin[..., 0] * 0.2126 + lin[..., 1] * 0.7152 + lin[..., 2] * 0.0722


def fit_crop(img):
    """Aspect-preserving fill + centre crop to WxH."""
    img = img.convert("RGB")
    if img.height > img.width:
        img = img.rotate(-90, expand=True)
    scale = max(W / img.width, H / img.height)
    nw, nh = max(W, int(round(img.width * scale))), max(H, int(round(img.height * scale)))
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - W) // 2, (nh - H) // 2
    return img.crop((left, top, left + W, top + H))


def preprocess(img, pal_lin):
    """Return float64 HxWx3 linear-light image, mapped into panel gamut."""
    # local contrast first, in sRGB space where unsharp is well behaved
    blur = img.filter(ImageFilter.GaussianBlur(LOCAL_RADIUS))
    a = np.asarray(img, dtype=np.float64)
    b = np.asarray(blur, dtype=np.float64)
    a = np.clip(a + LOCAL_AMOUNT * (a - b), 0, 255)

    lin = srgb_to_linear(a)

    # saturation pre-compensation around luminance
    y = luminance(lin)[..., None]
    lin = np.clip(y + (lin - y) * SATURATION, 0.0, 1.0)

    # map full-range luminance into the panel's actual dynamic range
    lo = luminance(pal_lin[0])          # panel black
    hi = luminance(pal_lin[1])          # panel white
    y2 = luminance(lin)
    y2 = np.clip(y2, BLACK_LIFT, 1.0)
    y2 = (y2 - BLACK_LIFT) / (1.0 - BLACK_LIFT)
    y2 = y2 ** (1.0 / EXPOSURE)
    # gentle S-curve to retain midtone separation after compression
    y2 = y2 * y2 * (3.0 - 2.0 * y2) * 0.35 + y2 * 0.65
    y_target = lo + y2 * (hi - lo)

    y_src = np.maximum(luminance(lin), 1e-6)
    lin = np.clip(lin * (y_target / y_src)[..., None], 0.0, 1.0)
    return lin


def dither(lin, pal_lin, progress_every=60):
    """Serpentine Floyd-Steinberg in linear light. Returns HxW index array.

    Deliberately pure-Python floats rather than numpy: the palette is only six
    entries, so per-pixel numpy call overhead dominates and costs ~20x more
    than doing the arithmetic directly.
    """
    h, w, _ = lin.shape
    R = lin[:, :, 0].tolist()
    G = lin[:, :, 1].tolist()
    B = lin[:, :, 2].tolist()
    pal = [(float(p[0]), float(p[1]), float(p[2])) for p in pal_lin]
    CLAMP = 0.35

    rows = []
    t0 = time.time()
    for y in range(h):
        cr, cg, cb = R[y], G[y], B[y]
        nxt = y + 1 < h
        if nxt:
            nr, ng, nb = R[y + 1], G[y + 1], B[y + 1]
        out = [0] * w

        if y % 2 == 0:
            xs, step = range(w), 1
        else:
            xs, step = range(w - 1, -1, -1), -1

        for x in xs:
            orr, og, ob = cr[x], cg[x], cb[x]
            best, bd = 0, 1e18
            for i in range(6):
                pr, pg, pb = pal[i]
                dr = orr - pr; dg = og - pg; db = ob - pb
                dd = dr * dr + dg * dg + db * db
                if dd < bd:
                    bd, best = dd, i
            out[x] = best

            pr, pg, pb = pal[best]
            er = orr - pr; eg = og - pg; eb = ob - pb
            if er > CLAMP: er = CLAMP
            elif er < -CLAMP: er = -CLAMP
            if eg > CLAMP: eg = CLAMP
            elif eg < -CLAMP: eg = -CLAMP
            if eb > CLAMP: eb = CLAMP
            elif eb < -CLAMP: eb = -CLAMP

            nx = x + step
            if 0 <= nx < w:
                cr[nx] += er * .4375; cg[nx] += eg * .4375; cb[nx] += eb * .4375
            if nxt:
                px = x - step
                if 0 <= px < w:
                    nr[px] += er * .1875; ng[px] += eg * .1875; nb[px] += eb * .1875
                nr[x] += er * .3125; ng[x] += eg * .3125; nb[x] += eb * .3125
                if 0 <= nx < w:
                    nr[nx] += er * .0625; ng[nx] += eg * .0625; nb[nx] += eb * .0625

        rows.append(out)
        if progress_every and y and y % progress_every == 0:
            logging.info("dither %d/%d rows (%.0fs elapsed)", y, h, time.time() - t0)

    return np.array(rows, dtype=np.uint8)


def pack(idx):
    """4bpp, two pixels per byte, high nibble = left pixel."""
    codes = PANEL_CODE[idx]
    hi = codes[:, 0::2].astype(np.uint8) << 4
    lo = codes[:, 1::2].astype(np.uint8) & 0x0F
    return bytearray((hi | lo).reshape(-1).tolist())


def calib_chart():
    """Solid blocks of the six native codes, for measuring real primaries."""
    idx = np.zeros((H, W), dtype=np.uint8)
    for i in range(6):
        idx[:, i * (W // 6):(i + 1) * (W // 6)] = i
    return idx


def load_driver():
    import importlib
    return importlib.import_module("waveshare_epd." + DRIVER)


def show(idx):
    epd = load_driver().EPD()
    epd.init()
    epd.Clear()
    epd.display(epd.getbuffer(to_epd_image(idx)))
    epd.sleep()          # NOTE: no Clear() here — that is what wipes your photo


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pal_lin = srgb_to_linear(PALETTE_SRGB)

    if "--calib" in sys.argv:
        show(calib_chart())
        print("Photograph the panel head-on, sample each block, "
              "paste the RGB values into PALETTE_SRGB.")
        sys.exit(0)

    if len(sys.argv) < 2:
        print("usage: epaper_photo.py <image> [--preview out.png]")
        sys.exit(1)

    img = fit_crop(Image.open(sys.argv[1]))
    lin = preprocess(img, pal_lin)

    t0 = time.time()
    idx = dither(lin, pal_lin)
    logging.info("dither took %.1fs", time.time() - t0)

    if "--preview" in sys.argv:
        out = sys.argv[sys.argv.index("--preview") + 1]
        Image.fromarray(PALETTE_SRGB[idx].astype(np.uint8)).save(out)
        logging.info("preview written to %s", out)
        sys.exit(0)

    show(idx)
