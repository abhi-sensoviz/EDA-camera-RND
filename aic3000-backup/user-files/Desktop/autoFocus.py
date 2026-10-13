#!/usr/bin/python3
"""ED-AIC3000: live preview window, TUNE button = autofocus, TRIG button = capture photo.

Run in a terminal on the camera's desktop (VNC):   python3 autoFocus.py
Run from an SSH session (window opens on the VNC desktop):   DISPLAY=:0 python3 autoFocus.py
Quit with Ctrl+C.
"""
import os
import subprocess
import threading
import time
from datetime import datetime

from picamera2 import Picamera2, Preview
from libedaio2 import EdaIo, registerTrigger, registerTune

LIQUID_MIN, LIQUID_MAX = 0, 46000   # setLiquid range from the ED-AIC3000 manual
COARSE_STEP, FINE_STEP = 2000, 250
SETTLE_S = 0.05                     # time for the liquid lens to settle after a move
PREVIEW = Preview.QTGL              # if the window stays black, change to Preview.QT
SAVE_DIR = os.path.expanduser("~/Desktop/captures")
FOCUS_FILE = os.path.expanduser("~/Desktop/focus.txt")
OPEN_CAPTURES = True                # open each saved photo in the image viewer

has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

# --- buttons -------------------------------------------------------------
trig, tune = threading.Event(), threading.Event()
eda = EdaIo.singleton()
registerTrigger(lambda level: trig.set())
registerTune(lambda level: tune.set())
eda.setup()

# --- camera + preview window ---------------------------------------------
cam = Picamera2()
preview_cfg = cam.create_preview_configuration(main={"size": (1024, 768)})
still_cfg = cam.create_still_configuration()    # full resolution 4056x3040
cam.configure(preview_cfg)

if has_display:
    cam.start_preview(PREVIEW, x=50, y=50, width=800, height=600)
else:
    print("No display found, so no preview window. Run from the camera desktop, or prefix with DISPLAY=:0")
    cam.start_preview(Preview.NULL)
cam.start()


# --- autofocus -----------------------------------------------------------
def sharpness():
    """Variance of the Laplacian over the centre half of the frame: higher = sharper."""
    img = cam.capture_array()
    h, w = img.shape[:2]
    g = img[h // 4:3 * h // 4, w // 4:3 * w // 4, :3].mean(axis=2)
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return lap.var()


def focus_at(value):
    eda.setLiquid(int(value))
    time.sleep(SETTLE_S)
    cam.capture_array()             # drop frames exposed while the lens was still moving
    cam.capture_array()
    return sharpness()


def sweep(values):
    scores = {v: focus_at(v) for v in values}
    return max(scores, key=scores.get), scores


def autofocus():
    print("autofocus...")
    # Freeze exposure during the sweep so brightness changes don't fake a sharpness change
    md = cam.capture_metadata()
    cam.set_controls({"AeEnable": False,
                      "ExposureTime": md["ExposureTime"],
                      "AnalogueGain": md["AnalogueGain"]})
    try:
        best, scores = sweep(range(LIQUID_MIN, LIQUID_MAX + 1, COARSE_STEP))
        print("coarse:", "  ".join(f"{v}:{s:.0f}" for v, s in scores.items()))
        lo = max(LIQUID_MIN, best - COARSE_STEP)
        hi = min(LIQUID_MAX, best + COARSE_STEP)
        best, _ = sweep(range(lo, hi + 1, FINE_STEP))
    finally:
        cam.set_controls({"AeEnable": True})
    eda.setLiquid(best)
    with open(FOCUS_FILE, "w") as f:
        f.write(str(best))
    print(f"focus = {best}  (saved to {FOCUS_FILE})")


# --- capture -------------------------------------------------------------
def capture():
    os.makedirs(SAVE_DIR, exist_ok=True)
    name = datetime.now().strftime("img_%Y%m%d_%H%M%S_%f")[:-3] + ".jpg"
    path = os.path.join(SAVE_DIR, name)
    cam.switch_mode_and_capture_file(still_cfg, path)   # full-res shot, then back to preview
    print("saved", path)
    if OPEN_CAPTURES and has_display:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- main loop -----------------------------------------------------------
if os.path.exists(FOCUS_FILE):
    with open(FOCUS_FILE) as f:
        last = int(f.read().strip())
    eda.setLiquid(last)
    print(f"restored focus = {last}")

print("Ready: TUNE = autofocus, TRIG = capture, Ctrl+C = quit")
try:
    while True:
        if tune.is_set():
            autofocus()
            tune.clear()            # clear after, so the button-release callback doesn't re-run it
        if trig.is_set():
            capture()
            trig.clear()
        time.sleep(0.02)
except KeyboardInterrupt:
    pass
finally:
    cam.close()
