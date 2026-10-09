#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
User settings shared by dashboard.py (reads) and portal.py (reads + writes).

Stored as config.json next to the scripts. A missing or broken file is never
fatal: every key falls back to DEFAULTS, so the dashboard keeps running even
before the user has finished the setup page.
"""

import os, json, logging, tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
PATH = os.environ.get("EPAPER_CONFIG", os.path.join(HERE, "config.json"))

DEFAULTS = {
    "lat":   24.8138,
    "lon":   120.9675,
    "place": "新竹",
    "tz":    "Asia/Taipei",
}
PLACE_MAX = 12                     # longer names overflow the header


def check_lat(v):
    f = float(v)
    if not -90.0 <= f <= 90.0:
        raise ValueError(f"latitude out of range (-90..90): {f}")
    return f


def check_lon(v):
    f = float(v)
    if not -180.0 <= f <= 180.0:
        raise ValueError(f"longitude out of range (-180..180): {f}")
    return f


def check_place(v):
    v = str(v).strip()
    if not v:
        raise ValueError("location name is empty")
    if any(ord(c) < 32 for c in v):
        raise ValueError("location name contains control characters")
    if len(v) > PLACE_MAX:
        raise ValueError(
            f"location name too long for the header ({len(v)} chars, max {PLACE_MAX})")
    return v


def check_tz(v):
    from zoneinfo import ZoneInfo
    v = str(v).strip()
    try:
        ZoneInfo(v)
    except Exception:
        raise ValueError(f"unknown time zone: {v!r}")
    return v


CHECKS = {"lat": check_lat, "lon": check_lon, "place": check_place, "tz": check_tz}


def load():
    """Returns a full settings dict; bad or missing keys fall back to DEFAULTS."""
    cfg = dict(DEFAULTS)
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return cfg
    except (OSError, ValueError) as e:
        logging.warning("config %s unreadable, using defaults: %s", PATH, e)
        return cfg
    for k, check in CHECKS.items():
        if k in data:
            try:
                cfg[k] = check(data[k])
            except (TypeError, ValueError) as e:
                logging.warning("config %s ignored: %s", k, e)
    return cfg


def save(cfg):
    """Validates every key, then replaces the file atomically."""
    out = {k: check(cfg[k]) for k, check in CHECKS.items()}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(PATH), prefix=".config-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PATH)
    except BaseException:
        os.unlink(tmp)
        raise
    return out
