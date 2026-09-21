#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ghosting recovery for Spectra 6 (E6). Alternating full-screen solids shake the
electrophoretic particles loose; this is what recovers a panel that has been in
storage or hammered with rapid refreshes.

Runs unattended for roughly an hour. Do it at ~25C, panel flat and face up.

  python3 recover.py            # 8 cycles of black/white
  python3 recover.py --colours  # add a 6-colour sweep first (stronger)
  python3 recover.py --black    # single full black, for the diagnostic test
"""

import sys, os, time, logging
from PIL import Image

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
if os.path.exists(os.path.join(HERE, 'lib')):
    sys.path.append(os.path.join(HERE, 'lib'))

from epaper_photo import W, H, load_driver
GAP = 185                       # >= 180s per the panel spec

SOLIDS = {
    "black":  (0, 0, 0),
    "white":  (255, 255, 255),
    "red":    (255, 0, 0),
    "green":  (0, 255, 0),
    "blue":   (0, 0, 255),
    "yellow": (255, 255, 0),
}


def flash(name):
    epd = load_driver().EPD()
    epd.init()
    img = Image.new("RGB", (W, H), SOLIDS[name])
    epd.display(epd.getbuffer(img))
    epd.sleep()                 # power down between passes, never idle powered
    logging.info("flashed %s", name)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if "--black" in sys.argv:
        flash("black")
        logging.info("Look at the panel. Uniform black -> ghosting, recoverable. "
                     "Lines visible in the black at fixed positions -> hardware.")
        return

    seq = []
    if "--colours" in sys.argv:
        seq += ["red", "green", "blue", "yellow"]
    for _ in range(8):
        seq += ["black", "white"]

    for i, name in enumerate(seq):
        flash(name)
        if i < len(seq) - 1:
            logging.info("waiting %ds (%d/%d)", GAP, i + 1, len(seq))
            time.sleep(GAP)

    logging.info("done — compare against the photo you took before starting")


if __name__ == "__main__":
    main()
