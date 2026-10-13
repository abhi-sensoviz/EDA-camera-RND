#!/usr/bin/python3
"""Proves (or disproves) that the I2C device at 0x18 changes optical focus.

Raw I2C through ctypes (no extra packages, no vendor library). It locks exposure,
sweeps the code 0..46000, scores centre-of-frame sharpness, saves the sharpest
and blurriest frames to /tmp/lenstest/, and restores the original code.

First run on 2026-10-13 pointed at a blank ceiling: flat curve (1.7-2.4), so it
was inconclusive. The proof came later from camera-tests/test_autofocus.py
sweeps with a detailed target (see ../findings/).
"""
import ctypes
import fcntl
import os
import time

import numpy as np
from picamera2 import Picamera2

I2C_RDWR, I2C_M_RD, ADDR = 0x0707, 0x0001, 0x18


class I2cMsg(ctypes.Structure):
    _fields_ = [("addr", ctypes.c_uint16), ("flags", ctypes.c_uint16),
                ("len", ctypes.c_uint16), ("buf", ctypes.POINTER(ctypes.c_uint8))]


class I2cRdwr(ctypes.Structure):
    _fields_ = [("msgs", ctypes.POINTER(I2cMsg)), ("nmsgs", ctypes.c_uint32)]


bus = open("/dev/i2c-1", "r+b", buffering=0)


def xfer(*msgs):
    arr = (I2cMsg * len(msgs))(*msgs)
    fcntl.ioctl(bus, I2C_RDWR, I2cRdwr(arr, len(msgs)))


def write_code(code):
    b = (ctypes.c_uint8 * 6)(0x00, 0x00, code & 0xFF, (code >> 8) & 0xFF, 0, 0)
    xfer(I2cMsg(ADDR, 0, 6, b))


def read_code():
    time.sleep(0.005)   # register reflects a write 1.5-3 ms later
    reg = (ctypes.c_uint8 * 2)(0x00, 0x00)
    out = (ctypes.c_uint8 * 4)()
    xfer(I2cMsg(ADDR, 0, 2, reg), I2cMsg(ADDR, I2C_M_RD, 4, out))
    return out[0] | (out[1] << 8)


def sharpness(img):
    g = img[..., :3].astype(np.float32).mean(axis=2)
    h, w = g.shape
    g = g[h // 4:3 * h // 4, w // 4:3 * w // 4]
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return float(lap.var()), float(g.mean())


os.makedirs("/tmp/lenstest", exist_ok=True)
orig = read_code()
print(f"original lens code: {orig}")

cam = Picamera2()
cam.configure(cam.create_preview_configuration(main={"size": (1014, 760), "format": "RGB888"}))
cam.start()
time.sleep(1.5)
md = cam.capture_metadata()
cam.set_controls({"AeEnable": False, "AwbEnable": False,
                  "ExposureTime": md["ExposureTime"], "AnalogueGain": md["AnalogueGain"]})
time.sleep(0.5)
print(f"exposure locked: {md['ExposureTime']} us, gain {md['AnalogueGain']:.2f}")


def measure(code):
    write_code(code)
    time.sleep(0.15)
    cam.capture_array()          # drop a frame exposed mid-change
    return sharpness(cam.capture_array())


rows = []
try:
    for code in range(0, 46001, 2000):
        s, m = measure(code)
        rows.append((code, s, m))
        print(f"code {code:5d}  sharpness {s:9.1f}  mean {m:6.1f}")

    best = max(rows, key=lambda r: r[1])
    worst = min(rows, key=lambda r: r[1])
    rep = [measure(best[0])[0] for _ in range(3)]
    print(f"\nsharpest code {best[0]} ({best[1]:.1f}), repeat {[round(r, 1) for r in rep]}")
    print(f"blurriest code {worst[0]} ({worst[1]:.1f})")
    print(f"ratio sharpest/blurriest: {best[1] / max(worst[1], 1e-6):.1f}x")
    print(f"brightness range across sweep: {min(r[2] for r in rows):.1f}..{max(r[2] for r in rows):.1f}")

    for name, code in (("sharpest", best[0]), ("blurriest", worst[0])):
        write_code(code)
        time.sleep(0.2)
        cam.capture_array()
        cam.capture_file(f"/tmp/lenstest/lens_{name}_code{code}.jpg")
finally:
    write_code(orig)
    restored = read_code()
    cam.close()
    print(f"restored lens code: {restored} ({'OK' if restored == orig else 'MISMATCH'})")
