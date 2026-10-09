#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wi-Fi provisioning + settings web page for the e-Paper dashboard.

Boot:  no uplink within CONNECT_WAIT, or the reset button held
         -> scan, start hotspot "ePaper-Setup-XXXX", draw a setup screen with
            two QR codes on the panel, serve a captive portal on 10.42.0.1
         -> user picks home Wi-Fi (+ city) -> join, geocode, redraw dashboard
       otherwise
         -> settings page on http://<hostname>.local
            (location search, photo upload, refresh now, redo Wi-Fi setup)

Usage: python3 portal.py                        # what epaper-portal.service runs
       python3 portal.py --setup                # force setup mode
       python3 portal.py --preview /tmp/s.png   # render the setup screen only
       python3 portal.py --port 8080 --no-panel # development

Help:  http://<hostname>.local/help serves help/help-zh-TW.html or help-en.html
       (?lang=zh-TW|en, default follows the browser language). Those pages
       are built from the READMEs by build_help.py.

Deps:  sudo apt install python3-flask python3-qrcode
       plus the polkit rule and dnsmasq snippet described in the README
"""

import os, sys, time, json, signal, socket, secrets, logging, argparse, threading
import subprocess, urllib.request, urllib.parse
import numpy as np
from PIL import Image, ImageDraw, ImageOps

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)

from flask import (Flask, request, redirect, render_template, url_for, flash,
                   abort, send_file, send_from_directory)
from werkzeug.utils import secure_filename

import config, wifi, dashboard
from epaper_photo import W, H, PALETTE_SRGB, I_BLACK, I_WHITE, I_RED, I_BLUE

# ------------------------- config -------------------------
CONNECT_WAIT = 90          # 開機後等已存 Wi-Fi 連上的秒數，逾時就進設定模式
BUTTON_PIN   = 26          # BCM；按鈕接 GND，開機時按住強制進設定模式。None = 沒接按鈕
# "open"：設定熱點不設密碼（部分 Pi 3B 開 WPA2 熱點時，手機會一直顯示密碼錯誤），
#         改用面板上的 PIN 擋住看不到面板的人
# "wpa2"：設定熱點使用 .ap_psk 裡的密碼（面板上同時顯示密碼與 PIN）
AP_SECURITY  = "open"
PIN_TRIES    = 5           # PIN 連錯這麼多次就暫停 PIN_LOCKOUT 秒
PIN_LOCKOUT  = 300
PSK_FILE     = os.path.join(HERE, ".ap_psk")
THUMB_DIR    = os.path.join(HERE, ".thumbs")
PHOTO_EXT    = (".jpg", ".jpeg", ".png", ".bmp")
GEO_URL      = "https://geocoding-api.open-meteo.com/v1/search"
IMG_DIR      = os.path.join(HERE, "img")
HELP_DIR     = os.path.join(HERE, "help")                # built by build_help.py
HELP_PAGES   = {"zh-TW": "help-zh-TW.html", "en": "help-en.html"}
# ----------------------------------------------------------


class State:
    mode = "normal"        # normal | setup | connecting
    networks = []          # scan taken before the hotspot came up
    ap_ssid = ap_psk = None  # ap_psk is None for an open hotspot
    pin = None             # shown on the panel, required by the setup form
    pin_fails = 0
    pin_locked_until = 0.0
    target = None          # SSID being joined
    error = None           # shown on the setup page
    notice = None          # shown once on the settings page
    panel = True           # False with --no-panel


S = State()


# --------------------------- setup screen ---------------------------

def wifi_qr_payload(ssid, psk):
    def esc(v):
        return "".join("\\" + c if c in '\\;,:"' else c for c in v)
    if not psk:
        return f"WIFI:T:nopass;S:{esc(ssid)};;"
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(psk)};;"


def qr_block(data, size):
    """QR code as a palette-index array, at most size x size, crisp modules."""
    import qrcode
    q = qrcode.QRCode(border=2)
    q.add_data(data)
    q.make(fit=True)
    m = np.array(q.get_matrix(), dtype=bool)
    box = size // len(m)
    return np.where(np.kron(m, np.ones((box, box), dtype=bool)),
                    I_BLACK, I_WHITE).astype(np.uint8)


def render_setup_screen(ssid, psk, pin):
    """Same idea as the dashboard: solid palette indices, no dithering."""
    def s(v):
        return int(round(v * H / 480))      # laid out at 800x480

    idx = np.full((H, W), I_WHITE, dtype=np.uint8)
    ov = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(ov)
    d.fontmode = "1"     # no anti-aliasing: in-between values would map to other colours
    f_title, f_body, f_small = dashboard.font(s(40)), dashboard.font(s(24)), dashboard.font(s(20))

    def t(xy, text, f, fill=I_BLACK, anchor="la"):
        d.text(xy, text, font=f, fill=fill + 1, anchor=anchor)

    t((s(32), s(24)), "Wi-Fi 設定", f_title, I_BLUE)

    url = f"http://{wifi.AP_ADDR}/"
    qsize, gap = s(210), s(30)
    for i, (data, caption) in enumerate(((wifi_qr_payload(ssid, psk), "① 掃描加入熱點"),
                                         (url, "② 開啟設定頁"))):
        q = qr_block(data, qsize)
        x, y = s(32) + i * (qsize + gap), s(100)
        idx[y:y + q.shape[0], x:x + q.shape[1]] = q
        t((x + q.shape[1] // 2, y + qsize + s(12)), caption, f_body, anchor="ma")

    rows = [("熱點名稱", ssid, I_BLACK)]
    if psk:
        rows.append(("熱點密碼", psk, I_BLACK))
    rows += [("設定頁 PIN", pin, I_BLUE), ("設定網址", url, I_BLACK)]
    x, y = s(32) + 2 * (qsize + gap) + s(10), s(100)
    step = s(70) if len(rows) > 3 else s(78)
    for label, value, colour in rows:
        t((x, y), label, f_small)
        t((x, y + s(28)), value, f_body, colour)
        y += step
    t((x, y), "只支援 2.4 GHz Wi-Fi", f_small, I_RED)

    t((s(32), H - s(44)), "設定完成後，這個畫面會自動換成天氣看板", f_small)
    return dashboard.compose(idx, ov)


# --------------------------- panel worker ---------------------------

class Panel:
    """The one thread that refreshes the panel on the portal's behalf.

    Requests coalesce: asking for "setup" and then "dashboard" while waiting
    out MIN_INTERVAL draws only the dashboard.
    """

    def __init__(self):
        self.cv = threading.Condition()
        self.want = None

    def request(self, what):
        with self.cv:
            self.want = what
            self.cv.notify()

    def run(self):
        while True:
            with self.cv:
                if self.want is None:
                    self.cv.wait(timeout=600)
                if self.want is None:
                    # the hourly timer stands down in setup mode, so the
                    # once-per-24h refresh the panel needs is our job then
                    if S.mode != "normal" and dashboard.age() > dashboard.MAX_AGE:
                        self.want = "setup"
                    else:
                        continue
            wait = dashboard.MIN_INTERVAL - dashboard.age()
            if wait > 0:
                logging.info("panel: waiting %.0fs (min refresh interval)", wait)
                time.sleep(wait)
            with self.cv:
                what, self.want = self.want, None
            self.draw(what)

    def draw(self, what):
        if not S.panel:
            logging.info("panel: would draw %s (--no-panel)", what)
            return
        try:
            if what == "setup":
                dashboard.show(render_setup_screen(S.ap_ssid, S.ap_psk, S.pin))
                # the panel no longer shows the last dashboard frame
                _rm(dashboard.FRAME_SIG)
            else:
                r = subprocess.run([sys.executable, os.path.join(HERE, "dashboard.py")],
                                   cwd=HERE, timeout=900)
                logging.info("panel: dashboard.py exited %d", r.returncode)
        except Exception:
            logging.exception("panel: drawing %s failed", what)


panel = Panel()


# --------------------------- provisioning ---------------------------

def _rm(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def ap_psk():
    """Per-device hotspot password, created once and kept."""
    try:
        with open(PSK_FILE) as f:
            psk = f.read().strip()
        if len(psk) >= 8:
            return psk
    except FileNotFoundError:
        pass
    psk = "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(10))
    fd = os.open(PSK_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(psk)
    return psk


def button_held():
    if BUTTON_PIN is None:
        return False
    try:
        from gpiozero import Button
        b = Button(BUTTON_PIN)              # internal pull-up, press = to GND
        held = b.is_pressed
        b.close()
        return held
    except Exception as e:
        logging.warning("reset button unreadable: %s", e)
        return False


def wait_online(timeout):
    deadline = time.time() + timeout
    while True:
        try:
            if wifi.online():
                return True
        except wifi.WifiError as e:
            logging.warning("nmcli: %s", e)
        if time.time() >= deadline:
            return False
        time.sleep(3)


def new_pin():
    return f"{secrets.randbelow(10 ** 6):06d}"


def start_hotspot():
    """Two tries: a client link that was just torn down sometimes needs a moment."""
    for attempt in (1, 2):
        try:
            wifi.ap_up(S.ap_ssid, S.ap_psk)
            return True
        except wifi.WifiError as e:
            logging.error("hotspot attempt %d failed: %s", attempt, e)
            time.sleep(5)
    return False


def abort_setup(why):
    """The hotspot won't come up: step aside so NetworkManager's autoconnect
    brings the saved network back, instead of leaving the panel pointing at a
    hotspot that doesn't exist."""
    logging.error("leaving Wi-Fi setup: %s", why)
    wifi.ap_down()
    S.notice = why
    leave_setup()


def enter_setup(reason):
    logging.info("entering Wi-Fi setup: %s", reason)
    S.mode = "setup"
    S.pin, S.pin_fails, S.pin_locked_until = new_pin(), 0, 0.0
    open(dashboard.SETUP_FLAG, "w").close()
    try:
        wifi.ap_down()
        S.networks = wifi.scan()            # one radio: scan before hosting
    except wifi.WifiError as e:
        logging.warning("scan failed: %s", e)
    if not start_hotspot():
        abort_setup("無法開啟設定熱點，已改回原本的 Wi-Fi。詳細原因請看 journalctl -u epaper-portal。")
        return
    panel.request("setup")


def leave_setup():
    S.mode = "normal"
    S.error = None
    _rm(dashboard.SETUP_FLAG)
    panel.request("dashboard")


def do_connect(ssid, psk, hidden, place):
    time.sleep(3)                           # let the reply reach the phone first
    wifi.ap_down()
    try:
        wifi.connect(ssid, psk, hidden)
    except wifi.WifiError as e:
        logging.warning("joining %s failed: %s", ssid, e)
        S.error = f"無法連上「{ssid}」。請確認密碼正確，且是 2.4 GHz 網路。（{e}）"
        try:
            S.networks = wifi.scan() or S.networks
        except wifi.WifiError:
            pass
        if not start_hotspot():
            abort_setup(f"無法連上「{ssid}」，而且設定熱點也無法重新開啟，已改回原本的 Wi-Fi。")
            return
        S.mode = "setup"
        return
    if place:
        set_location_by_name(place)
    leave_setup()


# --------------------------- location ---------------------------

def geocode(name, count=8):
    q = urllib.parse.urlencode({"name": name, "count": count,
                                "language": "zh", "format": "json"})
    with urllib.request.urlopen(f"{GEO_URL}?{q}", timeout=10) as r:
        return json.loads(r.read().decode()).get("results", [])


def save_location(lat, lon, place, tz=None):
    cfg = config.load()
    cfg.update(lat=lat, lon=lon, place=place)
    if tz:
        cfg["tz"] = tz
    return config.save(cfg)


def set_location_by_name(place):
    """After joining Wi-Fi: resolve the city typed on the setup page.

    Display name stays what the user typed; only coordinates and the time zone
    come from the geocoder. DNS can lag the link by a few seconds, so retry.
    """
    for attempt in range(6):
        try:
            hits = geocode(place, count=1)
            if hits:
                h = hits[0]
                save_location(h["latitude"], h["longitude"], place, h.get("timezone"))
                logging.info("location %s -> %.4f, %.4f", place, h["latitude"], h["longitude"])
                return
            break
        except Exception as e:
            logging.warning("geocode attempt %d failed: %s", attempt + 1, e)
            time.sleep(10)
    S.notice = f"找不到地點「{place}」，請在下方重新搜尋。"


# --------------------------- photos ---------------------------

def list_photos():
    if not os.path.isdir(dashboard.BG_DIR):
        return []
    return sorted(f for f in os.listdir(dashboard.BG_DIR) if f.lower().endswith(PHOTO_EXT))


def save_photo(fs):
    ext = os.path.splitext(fs.filename or "")[1].lower()
    if ext not in PHOTO_EXT:
        raise ValueError(f"{fs.filename}：只接受 JPG / PNG / BMP")
    name = secure_filename(fs.filename)
    if not name.lower().endswith(ext):      # e.g. an all-CJK file name
        name = time.strftime("photo_%Y%m%d_%H%M%S") + ext
    base, ext = os.path.splitext(name)
    n = 1
    while os.path.exists(os.path.join(dashboard.BG_DIR, name)):
        name, n = f"{base}_{n}{ext}", n + 1

    os.makedirs(dashboard.BG_DIR, exist_ok=True)
    # no image extension until verified, so dashboard.py never picks it up half-written
    tmp = os.path.join(dashboard.BG_DIR, f".upload-{secrets.token_hex(4)}")
    fs.save(tmp)
    try:
        with Image.open(tmp) as im:
            im.verify()
    except Exception:
        os.unlink(tmp)
        raise ValueError(f"{fs.filename}：不是有效的圖片")
    os.replace(tmp, os.path.join(dashboard.BG_DIR, name))
    return name


# --------------------------- web ---------------------------

app = Flask(__name__, template_folder=os.path.join(HERE, "templates"))
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
app.secret_key = secrets.token_hex(16)


def hostname():
    return socket.gethostname() + ".local"


@app.before_request
def guard():
    if S.mode != "normal":
        # captive portal: every foreign host (the phone's connectivity probes
        # included) is bounced to the setup page so the OS pops it up
        if request.host.split(":")[0] not in (wifi.AP_ADDR, "localhost", "127.0.0.1"):
            return redirect(f"http://{wifi.AP_ADDR}/")
        if request.endpoint not in ("index", "connect", "help", "help_lang", "img"):
            return redirect(url_for("index"))
    if request.method == "POST":
        # cheap CSRF guard: browsers send Origin on cross-site POSTs
        origin = request.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).netloc != request.host:
            abort(403)


@app.get("/")
def index():
    if S.mode == "setup":
        return render_template("setup.html", s=S, place_max=config.PLACE_MAX)
    if S.mode == "connecting":
        return connecting_page()

    q = request.args.get("q", "").strip()
    results, search_error = [], None
    if q:
        try:
            results = geocode(q)
            if not results:
                search_error = f"找不到「{q}」，試試其他寫法或英文名稱。"
        except Exception as e:
            search_error = f"搜尋失敗：{e}"
    try:
        ssid = wifi.current_ssid()
    except wifi.WifiError:
        ssid = None
    if S.notice:
        flash(S.notice, "err")
        S.notice = None
    today = dashboard.pick_background()
    return render_template(
        "settings.html", cfg=config.load(), ssid=ssid, photos=list_photos(),
        today=os.path.basename(today) if today else None, q=q, results=results,
        search_error=search_error, place_max=config.PLACE_MAX,
        pending=panel.want is not None, host=hostname())


def connecting_page():
    return render_template(
        "message.html", title="正在連線…",
        lines=[f"正在連到「{S.target}」，設定熱點會關閉，手機會自動斷線。",
               "成功：約 1–4 分鐘內看板會換成天氣畫面。之後在家中 Wi-Fi 下開啟 "
               f"http://{hostname()} 可以修改設定。",
               f"失敗：熱點「{S.ap_ssid}」會重新出現，請再連上它並開啟 "
               f"http://{wifi.AP_ADDR}/ 重試。"])


@app.post("/connect")
def connect():
    if S.mode != "setup":
        return redirect(url_for("index"))
    f = request.form
    manual = f.get("ssid_manual", "").strip()
    ssid, psk, place = manual or f.get("ssid", ""), f.get("psk", ""), f.get("place", "").strip()
    S.error = None
    if time.time() < S.pin_locked_until:
        S.error = f"PIN 錯誤次數過多，請 {PIN_LOCKOUT // 60} 分鐘後再試。"
    elif not secrets.compare_digest(f.get("pin", "").strip().encode(), (S.pin or "").encode()):
        S.pin_fails += 1
        if S.pin_fails >= PIN_TRIES:
            S.pin_fails, S.pin_locked_until = 0, time.time() + PIN_LOCKOUT
        S.error = "PIN 不正確，請輸入看板畫面上顯示的 6 位數 PIN。"
    elif not 1 <= len(ssid.encode()) <= 32:
        S.error = "請選擇或輸入 Wi-Fi 名稱。"
    elif psk and not 8 <= len(psk) <= 63:
        S.error = "Wi-Fi 密碼應為 8–63 個字元。"
    elif place:
        try:
            config.check_place(place)
        except ValueError:
            S.error = f"地點名稱最多 {config.PLACE_MAX} 個字。"
    if S.error:
        return redirect(url_for("index"))
    S.mode, S.target = "connecting", ssid
    threading.Thread(target=do_connect, args=(ssid, psk, bool(manual), place),
                     daemon=True).start()
    return connecting_page()


@app.post("/location")
def location():
    f = request.form
    try:
        save_location(f["lat"], f["lon"], f["place"], f.get("tz") or None)
    except (KeyError, ValueError) as e:
        flash(f"地點沒有儲存：{e}", "err")
        return redirect(url_for("index"))
    flash("地點已儲存，看板將自動更新。", "ok")
    panel.request("dashboard")
    return redirect(url_for("index"))


@app.post("/photos")
def upload():
    saved, errors = 0, []
    for fs in request.files.getlist("photos"):
        if not fs.filename:
            continue
        try:
            save_photo(fs)
            saved += 1
        except ValueError as e:
            errors.append(str(e))
    if saved:
        flash(f"已上傳 {saved} 張照片。", "ok")
    for e in errors:
        flash(e, "err")
    return redirect(url_for("index") + "#photos")


@app.get("/thumb/<name>")
def thumb(name):
    if name not in list_photos():
        abort(404)
    src = os.path.join(dashboard.BG_DIR, name)
    out = os.path.join(THUMB_DIR, name + ".jpg")
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(src):
        os.makedirs(THUMB_DIR, exist_ok=True)
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((320, 320))
            im.convert("RGB").save(out, "JPEG", quality=80)
    return send_file(out, mimetype="image/jpeg")


@app.post("/photos/<name>/delete")
def delete_photo(name):
    if name in list_photos():
        os.unlink(os.path.join(dashboard.BG_DIR, name))
        _rm(os.path.join(THUMB_DIR, name + ".jpg"))
        flash(f"已刪除 {name}。", "ok")
    return redirect(url_for("index") + "#photos")


@app.post("/refresh")
def refresh():
    panel.request("dashboard")
    flash("已排入更新；距上次刷新不到 3 分鐘時會稍候再刷。", "ok")
    return redirect(url_for("index"))


@app.get("/help", endpoint="help")
def help_page():
    lang = request.args.get("lang")
    if lang not in HELP_PAGES:
        best = request.accept_languages.best_match(["zh-TW", "zh", "en"], default="zh-TW")
        lang = "en" if best == "en" else "zh-TW"
    return send_from_directory(HELP_DIR, HELP_PAGES[lang])


@app.get("/help-<lang>")
@app.get("/help-<lang>.html")
def help_lang(lang):
    if lang not in HELP_PAGES:
        abort(404)
    return send_from_directory(HELP_DIR, HELP_PAGES[lang])


@app.get("/img/<path:name>")
def img(name):
    # README images; send_from_directory refuses paths outside IMG_DIR
    return send_from_directory(IMG_DIR, name)


@app.post("/wifi/reset")
def wifi_reset():
    def later():
        time.sleep(2)
        enter_setup("requested from the settings page")
    threading.Thread(target=later, daemon=True).start()
    return render_template(
        "message.html", title="切換到 Wi-Fi 設定模式",
        lines=[f"看板即將中斷目前的網路，並開啟設定熱點「{S.ap_ssid}」"
               + (f"（密碼 {S.ap_psk}）。" if S.ap_psk else "（不需要密碼）。"),
               f"請用手機連上該熱點後開啟 http://{wifi.AP_ADDR}/ ，"
               "並輸入看板畫面上顯示的 PIN。",
               "如果找不到熱點，看板會在約 1 分鐘內自動連回原本的 Wi-Fi。"])


# --------------------------- main ---------------------------

def main():
    p = argparse.ArgumentParser(description="Wi-Fi setup portal and settings page.")
    p.add_argument("--setup", action="store_true", help="start in Wi-Fi setup mode")
    p.add_argument("--preview", metavar="OUT.PNG",
                   help="render the setup screen to this PNG and exit")
    p.add_argument("--port", type=int, default=80)
    p.add_argument("--no-panel", action="store_true", help="never touch the panel")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    S.ap_ssid = f"ePaper-Setup-{wifi.mac_suffix()}"
    S.ap_psk = ap_psk() if AP_SECURITY == "wpa2" else None

    if args.preview:
        idx = render_setup_screen(S.ap_ssid, S.ap_psk, new_pin())
        Image.fromarray(PALETTE_SRGB[idx].astype(np.uint8)).save(args.preview)
        logging.info("preview -> %s", args.preview)
        return

    S.panel = not args.no_panel
    _rm(dashboard.SETUP_FLAG)                # stale after a crash
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    threading.Thread(target=panel.run, daemon=True).start()
    try:
        try:
            saved = wifi.saved_wifi()
        except wifi.WifiError as e:
            logging.warning("nmcli: %s", e)
            saved = []
        if args.setup:
            enter_setup("--setup")
        elif button_held():
            enter_setup("reset button held at boot")
        elif not wait_online(CONNECT_WAIT if saved else 15):
            enter_setup("no saved Wi-Fi" if not saved else "no network after %ds" % CONNECT_WAIT)
        app.run(host="0.0.0.0", port=args.port, threaded=True)
    finally:
        if S.mode != "normal":
            wifi.ap_down()
            _rm(dashboard.SETUP_FLAG)


if __name__ == "__main__":
    main()
