> &nbsp;
> ### <div style="text-align: right"> <font color="#02c59b">E-Paper Photo Frame</font> </div>
> ### <div style="text-align: right"> <font color="#ffcc00">Spectra 6 (E6) Full-Color e-Paper Weather Dashboard on Raspberry Pi 3</font></div>
>
> <div style="text-align: right"> Version: 1.0.0 </div>
> <div style="text-align: right"> Author: J </div>
> <div style="text-align: right"> Date: 2026/09/21 </div>

File History :
|         Type         |                         Description                          | Name |    Date    |
| :------------------: | :----------------------------------------------------------: | :--: | :--------: |
| v1.0.0 first release | 7.3" E6 (epd7in3e) photo frame + weather dashboard + hourly update | J | 2026/09/21 |

<div style="page-break-after: always;"></div>

# Table of contents
- [Table of contents](#table-of-contents)
- [Test Environment](#test-environment)
- [0. Overview](#0-overview)
- [1. Hardware](#1-hardware)
  - [1.1. Panel specification](#11-panel-specification)
  - [1.2. Wiring](#12-wiring)
- [2. Raspberry Pi setup](#2-raspberry-pi-setup)
- [3. Install this project](#3-install-this-project)
- [4. Configuration](#4-configuration)
- [5. Usage](#5-usage)
- [6. Color calibration](#6-color-calibration)
- [7. Auto update with systemd](#7-auto-update-with-systemd)
- [8. How it works](#8-how-it-works)
- [9. Result](#9-result)
- [10. Precautions](#10-precautions)
- [11. Troubleshooting](#11-troubleshooting)
- [12. Porting to another panel](#12-porting-to-another-panel)
- [13. References](#13-references)

# Test Environment

| Item        | Version / Model                                   | Comments                                   |
| ----------- | ------------------------------------------------- | ------------------------------------------ |
| Board       | Raspberry Pi 3 Model B V1.2                       | Also works on 3B / 3B+                     |
| OS          | Raspberry Pi OS                                   | Python 3.13                                |
| e-Paper     | Waveshare 7.3inch e-Paper HAT (E)                 | E Ink Spectra 6 (E6), 800 × 480            |
| Driver      | waveshare/e-Paper `epd7in3e`                      | `RaspberryPi_JetsonNano/python/lib`        |
| Python libs | python3-pil, python3-numpy, spidev, gpiozero      | All installed via apt                      |
| Font        | fonts-noto-cjk                                    | CJK font                                   |
| Weather API | [Open-Meteo](https://open-meteo.com/)             | No API key required                        |

# 0. Overview

Connect a Waveshare 7.3" Spectra 6 six-color e-Paper display to a Raspberry Pi 3 to build a "photo + weather" digital photo frame:

- The background is your own photo, changed automatically once a day (or a specific one can be pinned)
- Current temperature, feels-like, humidity, wind speed, chance of rain, and a 4-day forecast are overlaid on the photo
- Updates once when the network comes up at boot, then on the hour every hour thereafter
- No refresh happens without network access; but if no refresh has occurred for over 20 hours, it force-refreshes with cached data (the panel spec requires at least one refresh within 24 hours)
- If the rendered content is unchanged (aside from the timestamp), the refresh is skipped to reduce flicker and panel wear

Three scripts:

| Script            | Purpose                                                                     |
| ----------------- | ---------------------------------------------------------------------------- |
| `epaper_photo.py` | Image processing pipeline (gamut compression + dither), panel setup, single-photo display, color calibration |
| `dashboard.py`    | Main weather dashboard program: fetches weather, overlays text/icons, refreshes the panel |
| `recover.py`      | Panel diagnostics (all-black test) and ghosting recovery (alternating black/white or six-color full refresh) |

# 1. Hardware

### 1.1. Panel specification

| Item                 | Spec                                   |
| -------------------- | --------------------------------------- |
| Resolution           | 800 × 480                              |
| Display area         | 160.0 mm × 96.0 mm                     |
| Dot pitch            | 0.2 mm (approx. 127 ppi)               |
| Colors               | E6: black, white, yellow, red, blue, green |
| Full refresh time    | Approx. 25 s (flickering during refresh is normal) |
| Interface            | SPI (mode 0)                           |
| Operating voltage    | 3.3 V / 5 V                            |
| Operating temp.      | 0 ~ 50 °C                              |

### 1.2. Wiring

The driver board can be plugged directly onto the Pi's 40-pin header, or connected with the included 8-pin cable. When using the 8-pin cable, refer to the table below:

| e-Paper | BCM   | Board pin |
| :-----: | :---: | :-------: |
| VCC     | 3.3V  | 3.3V      |
| GND     | GND   | GND       |
| DIN     | MOSI  | 19        |
| CLK     | SCLK  | 23        |
| CS      | CE0   | 24        |
| DC      | 25    | 22        |
| RST     | 17    | 11        |
| BUSY    | 24    | 18        |

> Raspberry Pi pinout (source: Waveshare Wiki)
>
> ![pinout](img/pinout.png)

> Actual wiring: 8-pin cable connecting the 7.3inch e-Paper HAT (E) to a Raspberry Pi 3 Model B
>
> ![wiring](img/wiring.jpg)

Wiring notes:

- Set the driver board's **SPI Select switch to `0` (4-line SPI)**
- Keep the 8-pin extension cable under 20 cm; longer cables can cause data loss or a shifted image
- The panel's FPC cable is fragile: **only bend it horizontally along the screen**, never fold it vertically or toward the front of the screen, and avoid repeated bending. The FPC connector is a 0.5 mm pitch flip-back type — lift the retaining flap before inserting or removing it, and always disconnect power completely first

# 2. Raspberry Pi setup

**Step 1. Enable SPI**

```shell
$ sudo raspi-config
# Interface Options -> SPI -> Yes
$ sudo reboot
$ ls /dev/spi*        # should show /dev/spidev0.0 /dev/spidev0.1
```

**Step 2. Install packages**

```shell
$ sudo apt update
$ sudo apt install python3-pip python3-pil python3-numpy python3-spidev python3-gpiozero fonts-noto-cjk
```

**Step 3. User groups (run without sudo)**

A regular user only needs to be in the `spi` and `gpio` groups to drive the panel. Scripts in this project should **never be run with sudo** (see [11. Troubleshooting](#11-troubleshooting)).

```shell
$ id                                  # confirm spi and gpio are listed
$ sudo usermod -aG spi,gpio $USER     # if not, add them and re-login
```

**Step 4. Download the official Waveshare driver and run the official example first**

Confirm the hardware and wiring work before running this project:

```shell
$ mkdir -p ~/workspace && cd ~/workspace
$ git clone https://github.com/waveshare/e-Paper.git
$ cd e-Paper/RaspberryPi_JetsonNano/python/examples
$ python3 epd_7in3e_test.py
```

Only move on to the next step once the official example displays the six-color pattern and sample image correctly.

# 3. Install this project

Directory layout:

```
~/epaper/
├── epaper_photo.py
├── dashboard.py
├── recover.py
├── lib -> ~/workspace/e-Paper/RaspberryPi_JetsonNano/python/lib   (symlink)
├── bg/                      # background photos, jpg / png / bmp
├── systemd/
│   ├── epaper-dash.service
│   └── epaper-dash.timer
└── img/                     # images used in this README
```

```shell
$ mkdir -p ~/epaper/bg && cd ~/epaper
# copy in the three .py scripts and systemd/

# link in Waveshare's python lib (note: the python/lib level, not waveshare_epd itself)
$ ln -s ~/workspace/e-Paper/RaspberryPi_JetsonNano/python/lib ~/epaper/lib
$ ls ~/epaper/lib/waveshare_epd/epd7in3e.py      # file listed = link is correct

# add a few background photos
$ cp ~/Pictures/*.jpg ~/epaper/bg/
```

> If `~/epaper/lib` already exists as a directory, `ln -s` will create `lib/lib` inside it and imports will still fail. Remove it first, then re-create the symlink.

# 4. Configuration

**`epaper_photo.py`: panel and image processing**

| Parameter        | Default             | Description                                               |
| ---------------- | ------------------- | ----------------------------------------------------------- |
| `DRIVER`         | `"epd7in3e"`        | Waveshare driver module name                                |
| `W, H`           | `800, 480`          | Panel resolution                                             |
| `PALETTE_SRGB`   | estimated            | Measured primary colors of the panel, **must be calibrated** (see section 6) |
| `EXPOSURE`       | `1.25`              | >1 brightens midtones; increase if photos look too dark      |
| `SATURATION`     | `1.25`              | Saturation pre-compensation (dithering tends to wash colors out) |
| `LOCAL_AMOUNT`   | `0.55`              | Local contrast (unsharp), 0 to disable                        |

**`dashboard.py`: dashboard content and refresh policy**

| Parameter          | Default                  | Description                                          |
| ----------------- | ------------------------ | ------------------------------------------------------ |
| `LAT, LON`        | `24.8138, 120.9675`      | Coordinates used for the weather query                 |
| `PLACE`           | `"Hsinchu"`               | Place name shown on screen                              |
| `TZ`              | `"Asia/Taipei"`           | Timezone                                                |
| `SCRIM`           | `0.0`                     | Background darkening amount. 0 = photo as-is; readability is maintained via black text outlines |
| `SCRIM_BANDS`     | `False`                   | Additionally darken the top and bottom UI bands          |
| `MIN_INTERVAL`    | `180`                     | Minimum refresh interval (seconds), required by the panel spec |
| `MAX_AGE`         | `20 * 3600`               | Force a refresh once this long has passed without one (panel spec requires < 24 h) |

# 5. Usage

> All commands below are run as a regular user, **without sudo**.

**Weather dashboard `dashboard.py`**

```shell
$ cd ~/epaper
$ python3 dashboard.py                              # normal update (subject to refresh-protection rules)
$ python3 dashboard.py --force                      # skip all protection rules, refresh immediately
$ python3 dashboard.py --bg bg/a.jpg --force        # use a specific background photo (bypasses daily rotation)
$ python3 dashboard.py --preview /tmp/p.png         # only output a PNG, does not touch the panel
```

> ⚠️ The argument to `--preview` is an **output** path. Do not point it at a source file inside `bg/` — the program refuses to write into `bg/`.

**Single photo `epaper_photo.py` (no weather overlay)**

```shell
$ python3 epaper_photo.py bg/a.jpg
$ python3 epaper_photo.py bg/a.jpg --preview /tmp/p.png
```

Since there's no UI overlay, this is the cleanest tool for tuning `EXPOSURE` and verifying color calibration.

**Panel diagnostics and recovery `recover.py`**

```shell
$ python3 recover.py --black       # single all-black pass, used to tell ghosting from physical panel damage
$ python3 recover.py               # 8 rounds of alternating black/white (~1 hour, 185 s between passes)
$ python3 recover.py --colours     # flashes red/green/blue/yellow first, then alternating black/white (stronger effect)
```

**Recommended tuning workflow**: use `--preview` to dial in layout and brightness on a PNG first, and only refresh the physical panel once you're satisfied — this avoids wearing out the panel by refreshing it repeatedly while experimenting with parameters.

# 6. Color calibration

The E6 panel's actual primary colors are much darker and less saturated than their nominal values, and **colors vary between batches**. If dithering computes error against nominal colors (pure 0/255), the result looks dull and dark. Every panel should be measured once:

```shell
$ python3 epaper_photo.py --calib
```

1. The panel displays six solid color blocks (black, white, yellow, red, blue, green)
2. Photograph it **straight-on** under white (daylight) light, avoiding reflections
3. Use image editing software to sample the average RGB value at the center of each color block
4. Enter the values into `PALETTE_SRGB` in `epaper_photo.py` (order: black, white, yellow, red, blue, green)
5. Clear the background cache and re-run

```shell
$ rm -f .bg_cache.npz .frame_sig
$ python3 dashboard.py --force
```

# 7. Auto update with systemd

`systemd/epaper-dash.service` (replace `User` and the paths with your own account)

```ini
[Unit]
Description=e-Paper weather dashboard
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=ej
WorkingDirectory=/home/ej/epaper
ExecStart=/usr/bin/python3 /home/ej/epaper/dashboard.py
```

`systemd/epaper-dash.timer`

```ini
[Unit]
Description=Refresh e-Paper dashboard hourly and at boot

[Timer]
OnBootSec=2min
OnCalendar=*-*-* *:00:00
Persistent=true
RandomizedDelaySec=30

[Install]
WantedBy=timers.target
```

| Setting               | Effect                                                   |
| --------------------- | ---------------------------------------------------------- |
| `OnBootSec=2min`      | Update once after boot, once the network is up              |
| `OnCalendar=*:00:00`  | Update on the hour, every hour                               |
| `Persistent=true`     | Missed runs (e.g. while powered off) are caught up after boot |
| `RandomizedDelaySec`  | Avoids all timers firing at exactly the same instant          |

Install and verify:

```shell
$ sudo cp ~/epaper/systemd/epaper-dash.* /etc/systemd/system/
$ sudo systemctl daemon-reload
$ sudo systemctl enable --now epaper-dash.timer
$ systemctl list-timers epaper-dash.timer
$ journalctl -u epaper-dash.service -n 50 --no-pager
```

On every run, `dashboard.py` evaluates the following in order:

```mermaid
flowchart TD
    A[Timer triggers] --> B{Less than 180s since last refresh?}
    B -- Yes --> X[Skip]
    B -- No --> C{Network available?}
    C -- No --> D{No refresh for over 20h?}
    D -- No --> X
    D -- Yes --> E[Read cached weather, mark "offline"]
    C -- Yes --> F[Fetch Open-Meteo weather]
    E --> G[Compose frame]
    F --> G
    G --> H{Frame identical to last one?<br/>ignoring timestamp}
    H -- Yes --> X
    H -- No --> I[init → display → sleep]
```

# 8. How it works

```mermaid
flowchart LR
    P[Background photo] --> C[fit / crop<br/>800x480]
    C --> L[Convert to linear light]
    L --> T[Gamut / dynamic range compression<br/>EXPOSURE, SATURATION]
    T --> D[Floyd-Steinberg dither<br/>error computed against measured PALETTE]
    D --> K[(.bg_cache.npz<br/>computed once per photo)]
    K --> M[Overlay UI<br/>solid color indices, no dither]
    W[Open-Meteo weather] --> M
    M --> N[Convert to nominal RGB]
    N --> G[Waveshare getbuffer]
    G --> E[e-Paper]
```

A few key design decisions:

- **Photos are dithered, UI is not.** Text and icons are written with solid color indices *after* dithering, so small CJK text doesn't get scattered into noise by error diffusion. Text is always white with a black outline, so it stays readable on any photo brightness.
- **Compute error against measured colors, output nominal colors.** Dithering error is computed against the panel's measured `PALETTE_SRGB`, then the output is converted to nominal colors (pure 0/255) before being handed to Waveshare's `getbuffer()`. Since the image now contains only those six exact colors, `getbuffer()`'s nearest-color matching is a lossless one-to-one mapping — rotation, 4bpp packing, and the different color codes across panel sizes are all left to the official driver.
- **Dithering happens in linear light.** Doing error diffusion directly in sRGB values makes midtones look too dark and gradients band.
- **Background caching.** Since the photo only changes once a day, the dithered result is cached to `.bg_cache.npz`, and hourly updates only redraw the text layer.

# 9. Result

> On-device result: photo background + weather info
>
> ![result_cat](img/result_photo_cat.jpg)

> On-device result: night-sky photo background
>
> ![result_milkyway](img/result_photo_milkyway.jpg)

> Refresh in progress (4x speed). A full E6 refresh takes about 25 seconds; the flickering is normal ghost-clearing behavior
>
> ![refresh_demo](img/refresh_demo.gif)

# 10. Precautions

Most of these come from official Waveshare documentation; a few are lessons learned the hard way in this project, including one that destroyed a 4-inch panel:

1. **Always enter sleep mode or cut power after a refresh.** Leaving the panel at high voltage for a long time causes irreversible damage. This project calls `epd.sleep()` after every refresh.
2. **Refresh interval must be at least 180 seconds.** Don't repeatedly refresh with `--force` while debugging — verify on a PNG with `--preview` first.
3. **Refresh at least once every 24 hours**, or leaving the same image on screen for too long causes ghosting that's hard to remove.
4. **Refresh to white before long-term storage.** Storage conditions: below 30 °C, below 55% RH, up to 6 months, stored face-up. Taiwan's humidity is high, and panels stored beyond this period risk becoming unusable.
5. **Only bend the FPC cable horizontally**; never fold it vertically, toward the front, or bend it repeatedly.
6. Refreshing at low temperature can cause color shifts — let the panel sit at 25 °C for 6 hours before refreshing.
7. Indoor use only is recommended; avoid direct sunlight.
8. Color variation between batches is normal for multi-color panels, so every panel should go through [color calibration](#6-color-calibration).

# 11. Troubleshooting

| Symptom                                                       | Cause                                                                  | Fix                                                                      |
| ------------------------------------------------------------ | ----------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `ModuleNotFoundError: No module named 'waveshare_epd'`        | The `lib` symlink doesn't exist or is broken; or the script was run with sudo (root can't see the user's `pip --user` install) | Recreate the `lib` symlink (see section 3), and don't use sudo             |
| systemd fails but running manually works                     | Wrong `User` or path in the service file; or state files are owned by a different user | `sudo chown -R $USER:$USER ~/epaper`, check `journalctl -u epaper-dash.service` |
| Log shows `background: None`                                  | `bg/` isn't next to the script, or the extension doesn't match (e.g. `a.bmp.txt`) | `ls -la ~/epaper/bg/`                                                     |
| Background photo never changes                                | Rotation isn't noticeable with only a few photos                        | Add more photos, or use `--bg` to specify one                             |
| Photo looks too dark                                          | `SCRIM` is on, `EXPOSURE` too low, or `PALETTE_SRGB` isn't calibrated   | Set `SCRIM=0`, raise `EXPOSURE`, calibrate colors, then `rm .bg_cache.npz` |
| Changed a parameter but the screen didn't change              | Background cache is stale (cache key only covers photo path and SCRIM setting) | `rm -f .bg_cache.npz .frame_sig`                                          |
| Image is rotated 90° with regular stripes                     | Bypassed `getbuffer()` and packed data manually, mismatching the panel's scan direction | Use the current version of this project (sends data through `getbuffer()`) |
| Fixed-position stripes on an all-white / all-black screen      | Run `recover.py --black` first: uniform black → ghosting; lines in the same spot → physical damage to driver lines or film layer | Ghosting: run `recover.py --colours`; physical damage can't be fixed — replace the panel (driver board can be reused) |
| Stuck on `e-Paper busy`                                        | SPI not enabled or wiring error                                          | Check `ls /dev/spi*`, wiring, and the SPI Select switch                    |

# 12. Porting to another panel

Panel-specific settings are concentrated in the first two lines of `epaper_photo.py`; both `dashboard.py` and `recover.py` read from there. Layout font sizes and coordinates scale proportionally based on `H / 400`.

```python
DRIVER = "epd7in3e"       # 4in0e -> "epd4in0e" | 7.3in E6 -> "epd7in3e"
W, H = 800, 480           # 4in0e -> 600, 400    | 7.3in E6 -> 800, 480
```

After switching panels:

1. Confirm the corresponding driver file exists under `lib/waveshare_epd/`
2. Update the two lines above
3. Use `--preview` to check the layout
4. Redo [color calibration](#6-color-calibration)
5. `rm -f .bg_cache.npz .frame_sig .last_refresh`

Differing color codes across panels don't need any handling — `getbuffer()` takes care of that.

# 13. References

- [Waveshare 7.3inch e-Paper HAT (E) Manual](https://www.waveshare.com/wiki/7.3inch_e-Paper_HAT_(E)_Manual)
- [Waveshare 7.3inch e-Paper HAT (E) product page](https://www.waveshare.com/product/raspberry-pi/displays/e-paper/7.3inch-e-paper-hat-e.htm)
- [waveshare/e-Paper (GitHub)](https://github.com/waveshare/e-Paper)
- [E Ink Spectra 6 7.3" (EL073TF1U5)](https://www.eink.com/product/detail/EL073TF1U5)
- [Open-Meteo Weather API](https://open-meteo.com/en/docs)
