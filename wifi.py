#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Thin nmcli wrapper for Wi-Fi provisioning (Raspberry Pi OS Bookworm+ uses
NetworkManager by default).

Pi 3B notes:
  - BCM43438 is 2.4 GHz only: 5 GHz networks never show up in a scan.
  - One radio: hosting the setup hotspot and scanning/joining at the same time
    is unreliable, so callers scan BEFORE ap_up() and take the AP down before
    connect().

Running nmcli as a normal user needs the polkit rule in polkit/.
"""

import time, logging, subprocess

IFACE   = "wlan0"
AP_CON  = "epaper-setup"          # our hotspot profile; autoconnect off
AP_ADDR = "10.42.0.1"             # pinned in ap_up(); captive DNS points here


class WifiError(RuntimeError):
    pass


def nmcli(*args, timeout=30, check=True):
    try:
        r = subprocess.run(["nmcli", *args], capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise WifiError(f"nmcli {args[0]}: {e}")
    if check and r.returncode != 0:
        raise WifiError((r.stderr or r.stdout).strip() or f"nmcli exit {r.returncode}")
    return r.stdout


def _fields(line):
    """Split one line of `nmcli -t` output: ':' separates, '\\' escapes."""
    out, cur, esc = [], [], False
    for c in line:
        if esc:
            cur.append(c)
            esc = False
        elif c == "\\":
            esc = True
        elif c == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    out.append("".join(cur))
    return out


def _rows(text):
    return [_fields(l) for l in text.splitlines() if l]


def online():
    """True when a real uplink (Wi-Fi client or Ethernet) is up — not our hotspot.

    Deliberately says nothing about the internet: a router with a dead ISP
    link is still the right network, and must not kick us into setup mode.
    """
    for name, typ, state in _rows(nmcli("-t", "-f", "NAME,TYPE,STATE",
                                        "con", "show", "--active")):
        if (state == "activated" and name != AP_CON
                and typ in ("802-11-wireless", "802-3-ethernet")):
            return True
    return False


def saved_wifi():
    return [name for name, typ in _rows(nmcli("-t", "-f", "NAME,TYPE", "con", "show"))
            if typ == "802-11-wireless" and name != AP_CON]


def current_ssid():
    for active, ssid in _rows(nmcli("-t", "-f", "ACTIVE,SSID", "dev", "wifi", "list",
                                    "--rescan", "no", "ifname", IFACE)):
        if active == "yes":
            return ssid
    return None


def scan():
    """Visible networks, strongest first, one entry per SSID."""
    best = {}
    for ssid, signal, security in _rows(nmcli(
            "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list",
            "--rescan", "yes", "ifname", IFACE, timeout=40)):
        if not ssid:                        # hidden networks
            continue
        sig = int(signal) if signal.isdigit() else 0
        if ssid not in best or sig > best[ssid]["signal"]:
            best[ssid] = {"ssid": ssid, "signal": sig,
                          "secure": security not in ("", "--")}
    return sorted(best.values(), key=lambda n: -n["signal"])


def mac_suffix():
    """Last 4 hex digits of the Wi-Fi MAC, to tell several frames apart."""
    try:
        with open(f"/sys/class/net/{IFACE}/address") as f:
            return f.read().strip().replace(":", "")[-4:].upper()
    except OSError:
        return "0000"


def ap_up(ssid, psk):
    ap_down()
    nmcli("con", "add", "type", "wifi", "ifname", IFACE, "con-name", AP_CON,
          "autoconnect", "no", "ssid", ssid,
          "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
          "802-11-wireless.channel", "6",
          "ipv4.method", "shared", "ipv4.addresses", f"{AP_ADDR}/24",
          "ipv6.method", "disabled",
          # WPA2-only + PMF off: the brcmfmac AP mode is flaky with anything else
          "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", psk,
          "wifi-sec.proto", "rsn", "wifi-sec.pairwise", "ccmp",
          "wifi-sec.group", "ccmp", "wifi-sec.pmf", "disable")
    nmcli("con", "up", AP_CON, timeout=45)
    logging.info("hotspot %s up on %s", ssid, AP_ADDR)


def ap_down():
    nmcli("con", "down", AP_CON, check=False)
    nmcli("con", "delete", AP_CON, check=False)


def connect(ssid, psk="", hidden=False):
    """Join a network and keep it as an autoconnect profile. Raises WifiError."""
    # a previous attempt with a wrong password would otherwise be reused
    for name in saved_wifi():
        if name == ssid:
            nmcli("con", "delete", "id", ssid, check=False)
    nmcli("dev", "wifi", "rescan", "ifname", IFACE, check=False)
    time.sleep(5)                           # rescan is async
    args = ["--wait", "45", "dev", "wifi", "connect", ssid]
    if psk:
        args += ["password", psk]
    args += ["ifname", IFACE]
    if hidden:
        args += ["hidden", "yes"]
    try:
        nmcli(*args, timeout=60)
    except WifiError:
        nmcli("con", "delete", "id", ssid, check=False)   # don't keep a bad profile
        raise
    logging.info("joined %s", ssid)
