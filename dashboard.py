#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weather dashboard / photo frame for Waveshare Spectra 6 (E6) e-Paper on Raspberry Pi.
Panel and resolution are selected in epaper_photo.py (DRIVER, W, H).

Key idea: the background photo is dithered, the UI is NOT.
Text and icons are painted as solid palette indices AFTER dithering, so they
stay crisp instead of being chewed up by error diffusion.

Data: Open-Meteo (no API key). Cached to disk so a network outage shows the
last known forecast marked as stale rather than a blank screen.

Usage: python3 dashboard.py                      # render to the panel
       python3 dashboard.py --bg bg/a.bmp         # force one background image
       python3 dashboard.py --preview /tmp/p.png  # render to a PNG instead
       python3 dashboard.py --force               # skip the refresh guards

Run as your normal user, NOT with sudo: sudo does not see a --user pip install
or your group membership in spi/gpio.

Deps:  sudo apt install python3-pil python3-numpy fonts-noto-cjk
       (spidev / gpiozero already installed for the Waveshare lib)
"""

import os, sys, json, time, logging, urllib.request, urllib.parse, urllib.error
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
if os.path.exists(os.path.join(HERE, 'lib')):
    sys.path.append(os.path.join(HERE, 'lib'))

from epaper_photo import (
    W, H, PALETTE_SRGB, PANEL_CODE, srgb_to_linear,
    fit_crop, preprocess, dither, to_epd_image, load_driver, DRIVER,
    I_BLACK, I_WHITE, I_YELLOW, I_RED, I_BLUE, I_GREEN,
)

# ------------------------- config -------------------------
LAT, LON = 24.8138, 120.9675          # 新竹；改成你要的座標
PLACE    = "新竹"
TZ       = "Asia/Taipei"

BG_DIR    = os.path.join(HERE, "bg")           # 放當地照片，每天輪一張
CACHE     = os.path.join(HERE, "weather.json")
STAMP     = os.path.join(HERE, ".last_refresh")
BG_CACHE  = os.path.join(HERE, ".bg_cache.npz")
FRAME_SIG = os.path.join(HERE, ".frame_sig")
MIN_INTERVAL = 180                             # 面板規格建議最小刷新間隔（秒）
MAX_AGE      = 20 * 3600                       # 超過這麼久沒刷就強制刷（規格要求 <24h）

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKtc-Bold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# 0 = 照片原樣（文字靠黑描邊撐住，建議值）
# 0.2-0.3 = 只有在照片某塊太亮吃掉文字時才調
SCRIM = 0.0
SCRIM_BANDS = False   # True 時額外壓暗上下兩條 UI 帶
# ----------------------------------------------------------

WMO = {
    0: ("晴",     "sun"),   1: ("晴時多雲", "sun"),  2: ("多雲", "cloud"),
    3: ("陰",     "cloud"), 45:("霧",      "fog"),   48:("霧凇", "fog"),
    51:("毛毛雨", "rain"),  53:("毛毛雨",  "rain"),  55:("毛毛雨","rain"),
    61:("小雨",   "rain"),  63:("陣雨",    "rain"),  65:("大雨", "rain"),
    66:("凍雨",   "rain"),  67:("凍雨",    "rain"),
    71:("小雪",   "snow"),  73:("雪",      "snow"),  75:("大雪", "snow"),
    77:("霰",     "snow"),  80:("陣雨",    "rain"),  81:("陣雨", "rain"),
    82:("豪雨",   "rain"),  85:("陣雪",    "snow"),  86:("陣雪", "snow"),
    95:("雷雨",   "storm"), 96:("雷雨冰雹","storm"), 99:("雷雨冰雹","storm"),
}
WEEK = "一二三四五六日"


def font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


# --------------------------- data ---------------------------

def fetch_weather(timeout=15):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
        "weather_code,wind_speed_10m"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max"
        f"&timezone={urllib.parse.quote(TZ)}&forecast_days=5"
    )
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def has_network(timeout=4):
    """Cheap reachability probe — avoids a long retry storm when offline."""
    import socket
    for host in ("api.open-meteo.com", "1.1.1.1"):
        try:
            socket.setdefaulttimeout(timeout)
            socket.create_connection((host, 443), timeout).close()
            return True
        except OSError:
            continue
    return False


def get_weather(retries=5):
    """Returns (data, stale_bool). Retries, then falls back to cache."""
    for attempt in range(retries):
        try:
            d = fetch_weather()
            d["_fetched"] = time.time()
            with open(CACHE, "w") as f:
                json.dump(d, f)
            return d, False
        except Exception as e:
            logging.warning("fetch attempt %d failed: %s", attempt + 1, e)
            time.sleep(min(60, 5 * 2 ** attempt))
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            return json.load(f), True
    return None, True


# --------------------------- icons ---------------------------

def icon(d, cx, cy, r, kind, fg):
    """Simple flat icons drawn in solid palette indices."""
    if kind in ("sun",):
        d.ellipse((cx - r * .55, cy - r * .55, cx + r * .55, cy + r * .55),
                  fill=I_YELLOW + 1, outline=fg, width=max(2, int(r * .04)))
        for i in range(8):
            a = i * np.pi / 4
            x0, y0 = cx + np.cos(a) * r * .72, cy + np.sin(a) * r * .72
            x1, y1 = cx + np.cos(a) * r * 1.0, cy + np.sin(a) * r * 1.0
            d.line((x0, y0, x1, y1), fill=I_YELLOW + 1, width=max(2, int(r * .065)))
    if kind in ("cloud", "rain", "storm", "snow", "fog"):
        cw = r * 1.6
        yy = cy - r * .1 if kind != "cloud" else cy
        d.ellipse((cx - cw * .5, yy - r * .45, cx - cw * .5 + r * .8, yy + r * .35),
                  fill=I_WHITE + 1, outline=fg, width=max(2, int(r * .04)))
        d.ellipse((cx - r * .2, yy - r * .7, cx + r * .7, yy + r * .3),
                  fill=I_WHITE + 1, outline=fg, width=max(2, int(r * .04)))
        d.rounded_rectangle((cx - cw * .5, yy - r * .05, cx + cw * .5, yy + r * .35),
                            radius=int(r * .2), fill=I_WHITE + 1, outline=fg, width=max(2, int(r * .04)))
    if kind == "rain":
        for i in range(3):
            x = cx - r * .5 + i * r * .5
            d.line((x, cy + r * .45, x - r * .15, cy + r * .95),
                   fill=I_BLUE + 1, width=max(2, int(r * .078)))
    if kind == "snow":
        for i in range(3):
            x = cx - r * .5 + i * r * .5
            d.ellipse((x - r * .065, cy + r * .55, x + r * .065, cy + r * .75), fill=I_BLUE + 1)
    if kind == "storm":
        d.polygon([(cx, cy + r * .4), (cx - r * .3, cy + r * .95),
                   (cx - r * .02, cy + r * .9), (cx - r * .22, cy + r * 1.35),
                   (cx + r * .32, cy + r * .75), (cx + r * .02, cy + r * .78)],
                  fill=I_RED + 1)
    if kind == "fog":
        for i in range(3):
            y = cy + r * .45 + i * r * .22
            d.line((cx - r * .7, y, cx + r * .7, y), fill=I_BLUE + 1, width=max(2, int(r * .065)))


# --------------------------- render ---------------------------

BG_OVERRIDE = None          # set by --bg; skips the daily rotation


def pick_background():
    if BG_OVERRIDE:
        return BG_OVERRIDE
    if not os.path.isdir(BG_DIR):
        return None
    files = sorted(f for f in os.listdir(BG_DIR)
                   if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")))
    if not files:
        return None
    # deterministic daily rotation, keyed on LOCAL date
    import datetime
    return os.path.join(BG_DIR, files[datetime.date.today().toordinal() % len(files)])


def build_background():
    """Returns HxW index array of the dithered photo (or a plain dark field).

    The dither is the expensive part (~30-60s on a Pi 3) and the photo only
    changes once a day, so the result is cached and reused by hourly runs.
    """
    path = pick_background()
    key = f"{path}|{SCRIM}|{SCRIM_BANDS}"
    logging.info("background: %s", path)

    def save(idx):
        try:
            np.savez(BG_CACHE, key=np.array(key), idx=idx)
        except Exception as e:
            logging.warning("bg cache write failed: %s", e)
        return idx

    if os.path.exists(BG_CACHE):
        try:
            z = np.load(BG_CACHE, allow_pickle=False)
            if str(z["key"]) == key:
                logging.info("background cache hit")
                return z["idx"]
        except Exception as e:
            logging.warning("bg cache unreadable: %s", e)

    pal_lin = srgb_to_linear(PALETTE_SRGB)
    if path is None:
        logging.info("no background image, using flat field")
        return save(np.full((H, W), I_BLACK, dtype=np.uint8))

    img = fit_crop(Image.open(path))

    # optional scrim — off by default; the text carries itself on its black stroke
    if SCRIM > 0 or SCRIM_BANDS:
        a = np.asarray(img, dtype=np.float64) * (1.0 - SCRIM)
        if SCRIM_BANDS:
            grad = np.ones((H, 1))
            grad[:int(H * 0.375), 0] = 0.75
            grad[int(H * 0.70):, 0] = 0.75
            a = a * grad[:, :, None]
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    lin = preprocess(img, pal_lin)
    t0 = time.time()
    idx = dither(lin, pal_lin)
    logging.info("background dither %.1fs", time.time() - t0)
    return save(idx)


def build_overlay(w, stale):
    """Draw the UI into an 'L' image where value = palette_index + 1, 0 = transparent.

    All sizes derive from S so the same layout works on any panel resolution.
    """
    S = H / 400.0                       # 600x400 was the design reference
    def s(v):
        return int(round(v * S))

    ov = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(ov)

    FG, ST = I_WHITE + 1, I_BLACK + 1   # fill / stroke
    def t(xy, text, f, fill=FG, anchor="la", sw=5):
        d.text(xy, text, font=f, fill=fill, anchor=anchor,
               stroke_width=max(2, s(sw)), stroke_fill=ST)

    f_big   = font(s(112))
    f_title = font(s(30))
    f_body  = font(s(26))
    f_small = font(s(20))
    f_day   = font(s(22))

    if w is None:
        t((W // 2, H // 2), "無法取得天氣資料", f_title, anchor="mm")
        return ov

    cur = w["current"]
    day = w["daily"]
    code = int(cur["weather_code"])
    desc, kind = WMO.get(code, ("—", "cloud"))

    lt = time.localtime()
    header = f"{PLACE}   {lt.tm_mon}/{lt.tm_mday} (週{WEEK[lt.tm_wday]})"
    t((s(28), s(22)), header, f_title)

    # big temperature
    temp = f"{round(cur['temperature_2m'])}"
    t((s(24), s(58)), temp, f_big)
    tw = d.textlength(temp, font=f_big)
    t((s(28) + tw, s(78)), "°C", f_title)

    t((s(30), s(186)), f"{desc}   體感 {round(cur['apparent_temperature'])}°", f_body)
    t((s(30), s(222)), f"濕度 {round(cur['relative_humidity_2m'])}%   "
                       f"風 {cur['wind_speed_10m']:.0f} km/h", f_small)

    pop = day["precipitation_probability_max"][0]
    pc = (I_RED + 1) if pop >= 70 else (I_YELLOW + 1) if pop >= 40 else FG
    t((s(30), s(250)), f"降雨機率 {pop}%", f_small, fill=pc)

    # hero icon, top right
    icon(d, W - s(122), s(118), s(78), kind, ST)

    # 4-day strip along the bottom
    y0 = H - s(108)
    d.line((s(24), y0 - s(8), W - s(24), y0 - s(8)), fill=FG, width=max(2, s(3)))
    for i in range(1, 5):
        cx = s(24) + (W - s(48)) * (i - 0.5) / 4
        ts = time.localtime(time.time() + i * 86400)
        t((cx, y0), f"週{WEEK[ts.tm_wday]}", f_day, anchor="ma", sw=3)
        _, k = WMO.get(int(day["weather_code"][i]), ("—", "cloud"))
        icon(d, cx, y0 + s(52), s(24), k, ST)
        hi, lo = round(day["temperature_2m_max"][i]), round(day["temperature_2m_min"][i])
        t((cx, y0 + s(76)), f"{hi}° / {lo}°", f_small, anchor="ma", sw=3)

    # date already lives in the header, so the footer carries the time only —
    # keeps it short enough not to collide with the header when stale
    msg = "更新 " + time.strftime("%H:%M") + ("（快取）" if stale else "")
    t((W - s(26), s(28)), msg, f_small, fill=(I_YELLOW + 1) if stale else FG,
      anchor="ra", sw=3)
    return ov


def compose(bg_idx, ov):
    a = np.asarray(ov)
    m = a > 0
    out = bg_idx.copy()
    out[m] = a[m] - 1
    return out


# --------------------------- output ---------------------------

def too_soon():
    if not os.path.exists(STAMP):
        return False
    return (time.time() - os.path.getmtime(STAMP)) < MIN_INTERVAL


def age():
    if not os.path.exists(STAMP):
        return float("inf")
    return time.time() - os.path.getmtime(STAMP)


def signature(idx):
    """Hash of the frame, ignoring the footer strip where the clock lives.

    Lets us skip a refresh when nothing but the timestamp changed.
    """
    import hashlib
    a = idx.copy()
    a[:int(H * 0.13), W // 2:] = 0
    return hashlib.sha1(a.tobytes()).hexdigest()


def unchanged(sig):
    if not os.path.exists(FRAME_SIG):
        return False
    with open(FRAME_SIG) as f:
        return f.read().strip() == sig


def show(idx, sig=None):
    epd = load_driver().EPD()
    epd.init()
    epd.Clear()
    epd.display(epd.getbuffer(to_epd_image(idx)))
    epd.sleep()                      # 刷完立刻睡，長期通電會燒屏
    open(STAMP, "w").close()
    if sig:
        with open(FRAME_SIG, "w") as f:
            f.write(sig)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    preview = "--preview" in sys.argv
    force = "--force" in sys.argv

    if "--bg" in sys.argv:
        p = os.path.abspath(sys.argv[sys.argv.index("--bg") + 1])
        if not os.path.isfile(p):
            logging.error("--bg: no such file: %s", p)
            sys.exit(2)
        BG_OVERRIDE = p

    if not preview:
        try:
            load_driver()
        except ImportError:
            logging.error(
                "waveshare_epd not importable. Expected the Waveshare python "
                "lib (%s) at %s (symlink it: ln -s .../python/lib %s)", DRIVER,
                os.path.join(HERE, "lib"), os.path.join(HERE, "lib"))
            sys.exit(1)

    if not preview and not force and too_soon():
        logging.info("last refresh < %ds ago, skipping", MIN_INTERVAL)
        sys.exit(0)

    online = preview or has_network()
    overdue = age() > MAX_AGE

    # 沒網路就不刷，除非已經超過 MAX_AGE 沒更新 —— 面板規格要求 24h 內至少刷一次
    if not online and not force and not overdue:
        logging.info("offline and last refresh %.1fh ago, skipping", age() / 3600)
        sys.exit(0)
    if not online:
        logging.warning("offline but %.1fh overdue, refreshing from cache",
                        age() / 3600)

    w, stale = get_weather(retries=5 if online else 1)
    idx = compose(build_background(), build_overlay(w, stale))

    if preview:
        out = sys.argv[sys.argv.index("--preview") + 1]
        # --preview takes an OUTPUT path; refuse to clobber a source image
        if os.path.abspath(out).startswith(os.path.abspath(BG_DIR) + os.sep):
            logging.error("--preview writes TO this path; %s is a source image. "
                          "Use something like /tmp/p.png", out)
            sys.exit(2)
        Image.fromarray(PALETTE_SRGB[idx].astype(np.uint8)).save(out)
        logging.info("preview -> %s", out)
        sys.exit(0)

    sig = signature(idx)
    if unchanged(sig) and not overdue and not force:
        logging.info("frame unchanged apart from the clock, skipping refresh")
        sys.exit(0)

    show(idx, sig)
    logging.info("done")
