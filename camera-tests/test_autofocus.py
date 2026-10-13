#!/usr/bin/python3
"""
ED-AIC3000 liquid-lens / autofocus test - talks to the lens directly over I2C,
no EDATEC SDK. Shows a live camera view with the lens code and sharpness on it.

  Lens driver : /dev/i2c-1 (GPIO10/11), address 0x18, register 0x0000 = focus
                code 0..46000 (little-endian). Same bytes as EDATEC's
                setLiquid().
  Buttons     : TUNE = GPIO20, TRIG = GPIO12 (idle high, pressed low)

Put something with fine detail (printed text, a checkerboard) in front of the
camera at your working distance first - a blank wall gives a flat curve.

Run on the camera (the live view opens on the camera's desktop, also when
started over SSH; add --no-preview to run without it):
    python3 test_autofocus.py read                   # current lens code
    python3 test_autofocus.py set 30000              # write a code, read it back
    python3 test_autofocus.py view                   # live view + manual focus (type codes / +N / -N)
    python3 test_autofocus.py sweep                  # sharpness vs code 0..46000 (proves the lens focuses)
    python3 test_autofocus.py sweep --start 20000 --stop 40000 --step 500
    python3 test_autofocus.py autofocus              # coarse + fine search, leaves the lens at best focus
    python3 test_autofocus.py buttons                # TUNE = autofocus, TRIG = photo (Ctrl+C to quit)

Images and a CSV go to ./af_results/. On error or Ctrl+C the lens is put back
where it started (a successful autofocus keeps its result).
"""
import argparse
import csv
import os
import sys
import time
from datetime import datetime

import numpy as np
from smbus2 import SMBus, i2c_msg   # python3-smbus2 - preinstalled on the camera

LENS_BUS, LENS_ADDR = 1, 0x18
CODE_MIN, CODE_MAX = 0, 46000
WRITE_APPLY_S = 0.005        # register reflects a write 1.5-3 ms later
VIEW_SIZE = (1014, 760)
OUT = os.path.join(os.getcwd(), "af_results")


# ------------------------------------------------------------------ lens ---

class Lens:
    def __init__(self):
        self.bus = SMBus(LENS_BUS)
        self.last_write = 0.0

    def read(self):
        wait = self.last_write + WRITE_APPLY_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        w = i2c_msg.write(LENS_ADDR, [0x00, 0x00])
        r = i2c_msg.read(LENS_ADDR, 4)
        self.bus.i2c_rdwr(w, r)
        b = list(r)
        return b[0] | (b[1] << 8)

    def write(self, code):
        code = max(CODE_MIN, min(CODE_MAX, int(code)))
        self.bus.i2c_rdwr(i2c_msg.write(LENS_ADDR, [0x00, 0x00, code & 0xFF, (code >> 8) & 0xFF, 0, 0]))
        self.last_write = time.monotonic()
        return code

    def close(self):
        self.bus.close()


# ------------------------------------------------------------- live view ---

def prepare_display():
    """Point Qt at the camera's own desktop, so the live view also opens when
    the script is started over SSH. Returns False when there is no desktop."""
    if not os.environ.get("DISPLAY") and os.path.exists("/tmp/.X11-unix/X0"):
        os.environ["DISPLAY"] = ":0"
    runtime = f"/run/user/{os.getuid()}"
    if not os.environ.get("XDG_RUNTIME_DIR") and os.path.isdir(runtime):
        os.environ["XDG_RUNTIME_DIR"] = runtime
    # The GL preview crashes on native Wayland on this camera (EGL); through
    # Xwayland it works, so force the X11 backend.
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    return bool(os.environ.get("DISPLAY"))


def banner(text, size=VIEW_SIZE):
    """RGBA overlay with one line of text along the top of the live view."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    draw.rectangle([0, 0, size[0], 48], fill=(0, 0, 0, 160))
    draw.text((12, 7), text, fill=(255, 230, 0, 255), font=font)
    return np.array(img)


# ---------------------------------------------------------------- camera ---

class Camera:
    def __init__(self, live=True):
        live = live and prepare_display()
        from picamera2 import Picamera2, Preview
        self.cam = Picamera2()
        # XBGR8888: a format the GL live view can display (it rejects RGB888)
        self.cam.configure(self.cam.create_preview_configuration(main={"size": VIEW_SIZE, "format": "XBGR8888"}))
        self.live = live
        if live:
            self.cam.start_preview(Preview.QTGL, x=40, y=40, width=VIEW_SIZE[0], height=VIEW_SIZE[1])
        else:
            print("(running without live view)")
        self.cam.start()
        time.sleep(1.5)                       # let auto exposure settle

    def status(self, text):
        if not self.live:
            return
        try:
            self.cam.set_overlay(banner(text))
        except Exception as e:                # the view is a convenience, never fatal
            print(f"(overlay failed: {e})")
            self.live = False

    def lock_exposure(self):
        md = self.cam.capture_metadata()
        controls = {"AeEnable": False, "ExposureTime": md["ExposureTime"],
                    "AnalogueGain": md["AnalogueGain"], "AwbEnable": False}
        if "ColourGains" in md:
            controls["ColourGains"] = md["ColourGains"]
        self.cam.set_controls(controls)
        time.sleep(0.3)
        print(f"exposure locked: {md['ExposureTime']} us, gain {md['AnalogueGain']:.2f}")

    def unlock_exposure(self):
        self.cam.set_controls({"AeEnable": True, "AwbEnable": True})

    def frame(self, drop=2):
        for _ in range(drop):                 # frames exposed while the lens was moving
            self.cam.capture_array()
        return self.cam.capture_array()

    def save(self, path):
        self.cam.capture_file(path)

    def photo(self, path):
        self.cam.switch_mode_and_capture_file(self.cam.create_still_configuration(), path)

    def close(self):
        self.cam.close()


def sharpness(img, roi=0.5):
    """Tenengrad (mean squared Sobel gradient) over the centre `roi` fraction."""
    g = img[..., :3].astype(np.float32).mean(axis=2)
    h, w = g.shape
    dh, dw = int(h * (1 - roi) / 2), int(w * (1 - roi) / 2)
    g = g[dh:h - dh, dw:w - dw]
    gx = (g[:-2, 2:] + 2 * g[1:-1, 2:] + g[2:, 2:]) - (g[:-2, :-2] + 2 * g[1:-1, :-2] + g[2:, :-2])
    gy = (g[2:, :-2] + 2 * g[2:, 1:-1] + g[2:, 2:]) - (g[:-2, :-2] + 2 * g[:-2, 1:-1] + g[:-2, 2:])
    return float(np.mean(gx * gx + gy * gy)), float(g.mean())


def measure(lens, cam, code, settle, roi):
    lens.write(code)
    time.sleep(settle)
    return sharpness(cam.frame(), roi)


def parabola_peak(points, best_code):
    """Sub-step peak from the best sample and its two neighbours."""
    pts = sorted(points)
    codes = [c for c, _ in pts]
    i = codes.index(best_code)
    if i == 0 or i == len(pts) - 1:
        return best_code
    (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
    denom = (x0 - x1) * (x0 - x2) * (x1 - x2)
    a = (x2 * (y1 - y0) + x1 * (y0 - y2) + x0 * (y2 - y1)) / denom
    b = (x2 * x2 * (y0 - y1) + x1 * x1 * (y2 - y0) + x0 * x0 * (y1 - y2)) / denom
    if a >= 0:
        return best_code
    return int(round(min(max(-b / (2 * a), x0), x2)))


def stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# -------------------------------------------------------------- commands ---

def cmd_read(args):
    lens = Lens()
    print(f"lens code: {lens.read()}")
    lens.close()


def cmd_set(args):
    lens = Lens()
    before = lens.read()
    written = lens.write(args.code)
    after = lens.read()
    print(f"lens code {before} -> wrote {written} -> reads back {after}  "
          f"[{'OK' if after == written else 'MISMATCH'}]")
    lens.close()


def cmd_view(args):
    lens, cam = Lens(), Camera(not args.no_preview)
    print("live view with manual focus:\n"
          "  <code>  set the lens (0..46000)     +N / -N  step by N     Enter  re-measure\n"
          "  a       autofocus                   p        save a photo  q      quit")
    os.makedirs(OUT, exist_ok=True)
    try:
        while True:
            code = lens.read()
            s, m = sharpness(cam.frame(drop=1), args.roi)
            cam.status(f"lens {code}   sharpness {s:.0f}   brightness {m:.0f}")
            cmd = input(f"[lens {code}  sharpness {s:.0f}] > ").strip().lower()
            if cmd in ("q", "quit", "exit"):
                break
            if cmd == "a":
                autofocus(lens, cam, args)
            elif cmd == "p":
                path = os.path.join(OUT, f"photo_code{code}_{stamp()}.jpg")
                cam.photo(path)
                print(f"saved {path}")
            elif cmd.startswith(("+", "-")) and cmd[1:].isdigit():
                lens.write(code + int(cmd))
                time.sleep(args.settle)
            elif cmd.isdigit():
                lens.write(int(cmd))
                time.sleep(args.settle)
            elif cmd:
                print("  ? type a code, +N, -N, a, p or q")
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        print(f"lens left at {lens.read()}")
        cam.close()
        lens.close()


def run_sweep(lens, cam, codes, args, label):
    rows = []
    for c in codes:
        s, m = measure(lens, cam, c, args.settle, args.roi)
        rows.append((c, s, m))
        best = max(rows, key=lambda r: r[1])
        cam.status(f"{label.strip()}  lens {c}  sharpness {s:.0f}   (best {best[1]:.0f} @ {best[0]})")
        print(f"  {label} code {c:5d}  sharpness {s:10.1f}  brightness {m:6.1f}")
    return rows


def cmd_sweep(args):
    os.makedirs(OUT, exist_ok=True)
    lens, cam = Lens(), Camera(not args.no_preview)
    original = lens.read()
    print(f"original lens code: {original}")
    try:
        cam.lock_exposure()
        rows = run_sweep(lens, cam, range(args.start, args.stop + 1, args.step), args, "sweep")
        best = max(rows, key=lambda r: r[1])
        worst = min(rows, key=lambda r: r[1])
        ratio = best[1] / max(worst[1], 1e-9)
        csv_path = os.path.join(OUT, f"sweep_{stamp()}.csv")
        with open(csv_path, "w", newline="") as f:
            csv.writer(f).writerows([("code", "sharpness", "brightness"), *rows])
        for name, code in (("blurriest", worst[0]), ("sharpest", best[0])):
            lens.write(code)
            time.sleep(args.settle)
            cam.frame()
            cam.status(f"{name}: lens {code}")
            cam.save(os.path.join(OUT, f"sweep_{name}_code{code}.jpg"))
            time.sleep(1.5)                   # time to look at it in the live view
        print(f"\nsharpest code {best[0]} ({best[1]:.1f}), blurriest code {worst[0]} ({worst[1]:.1f}), ratio {ratio:.1f}x")
        if ratio < 1.5:
            verdict = "flat curve - no focus change visible. Is a detailed target in view?"
        else:
            verdict = "the I2C lens code changes optical focus."
        print(f"VERDICT: {verdict}")
        cam.status(f"VERDICT: {'FOCUS CHANGES' if ratio >= 1.5 else 'FLAT - no detail in view?'}  ({ratio:.1f}x)")
        print(f"saved: {csv_path} and the two images in {OUT}/")
        time.sleep(2.0)
    finally:
        lens.write(original)
        print(f"lens restored to {lens.read()}")
        cam.close()
        lens.close()


def autofocus(lens, cam, args):
    """Coarse sweep over [lo, hi], fine sweep around the peak, verify. Returns (ok, code, score)."""
    t0 = time.monotonic()
    cam.lock_exposure()
    try:
        coarse = run_sweep(lens, cam, range(args.lo, args.hi + 1, args.coarse), args, "coarse")
        scores = [s for _, s, _ in coarse]
        if max(scores) / max(min(scores), 1e-9) < 1.5:
            print("no focus signal (flat curve) - put a detailed target in view")
            cam.status("autofocus: NO SIGNAL - put a detailed target in view")
            return False, None, 0.0
        best_c = max(coarse, key=lambda r: r[1])[0]
        flo, fhi = max(args.lo, best_c - args.coarse), min(args.hi, best_c + args.coarse)
        fine = run_sweep(lens, cam, range(flo, fhi + 1, args.fine), args, "fine  ")
        best_f = max(fine, key=lambda r: r[1])
        target = parabola_peak([(c, s) for c, s, _ in fine], best_f[0])
        lens.write(target)
        time.sleep(args.settle)
        verify, _ = sharpness(cam.frame(), args.roi)
        ok = verify >= 0.85 * best_f[1]
        took = time.monotonic() - t0
        print(f"\nfocus {'FOUND' if ok else 'NOT VERIFIED'} at code {target} "
              f"(sweep best {best_f[1]:.1f} at {best_f[0]}, settled {verify:.1f}, "
              f"{len(coarse) + len(fine)} samples, {took:.1f} s)")
        cam.status(f"autofocus {'FOUND' if ok else 'NOT VERIFIED'}: lens {target}  sharpness {verify:.0f}  ({took:.1f} s)")
        return ok, target, verify
    finally:
        cam.unlock_exposure()


def cmd_autofocus(args):
    os.makedirs(OUT, exist_ok=True)
    lens, cam = Lens(), Camera(not args.no_preview)
    original = lens.read()
    print(f"original lens code: {original}")
    keep = False
    try:
        ok, code, _ = autofocus(lens, cam, args)
        if ok:
            keep = True
            path = os.path.join(OUT, f"autofocus_code{code}_{stamp()}.jpg")
            cam.save(path)
            print(f"saved {path}")
        time.sleep(3.0)                       # leave the result on screen for a moment
    finally:
        if not keep:
            lens.write(original)
            print(f"lens restored to {lens.read()}")
        else:
            print(f"lens left at {lens.read()}")
        cam.close()
        lens.close()


def cmd_buttons(args):
    from gpiozero import Button
    os.makedirs(OUT, exist_ok=True)
    lens, cam = Lens(), Camera(not args.no_preview)
    tune = Button(20, pull_up=None, active_state=False, bounce_time=0.05)
    trig = Button(12, pull_up=None, active_state=False, bounce_time=0.05)
    print(f"lens at {lens.read()}.  TUNE = autofocus, TRIG = full-res photo, Ctrl+C = quit")
    cam.status(f"lens {lens.read()}   TUNE = autofocus   TRIG = photo")
    try:
        while True:
            if tune.is_pressed:
                print("\n[TUNE] autofocus")
                autofocus(lens, cam, args)
                tune.wait_for_release()
            if trig.is_pressed:
                path = os.path.join(OUT, f"photo_code{lens.read()}_{stamp()}.jpg")
                cam.status("TRIG: taking photo...")
                cam.photo(path)
                print(f"\n[TRIG] saved {path}")
                cam.status(f"photo saved   lens {lens.read()}   TUNE = autofocus   TRIG = photo")
                trig.wait_for_release()
            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        tune.close()
        trig.close()
        cam.close()
        lens.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("read")
    p = sub.add_parser("set")
    p.add_argument("code", type=int)

    def camera_opts(p):
        p.add_argument("--no-preview", action="store_true", help="run without the live view")
        p.add_argument("--settle", type=float, default=0.12, help="lens settle time per step, s")
        p.add_argument("--roi", type=float, default=0.5, help="centre fraction scored for sharpness")

    def search_opts(p):
        p.add_argument("--lo", type=int, default=0, help="search range start code")
        p.add_argument("--hi", type=int, default=46000, help="search range end code")
        p.add_argument("--coarse", type=int, default=2000, help="coarse step (codes)")
        p.add_argument("--fine", type=int, default=200, help="fine step (codes)")

    p = sub.add_parser("sweep")
    camera_opts(p)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--stop", type=int, default=46000)
    p.add_argument("--step", type=int, default=2000)
    for name in ("view", "autofocus", "buttons"):
        p = sub.add_parser(name)
        camera_opts(p)
        search_opts(p)

    args = ap.parse_args()
    {"read": cmd_read, "set": cmd_set, "view": cmd_view, "sweep": cmd_sweep,
     "autofocus": cmd_autofocus, "buttons": cmd_buttons}[args.cmd](args)


if __name__ == "__main__":
    try:
        main()
    except PermissionError as e:
        sys.exit(f"permission denied ({e}) - the pi user needs the i2c and video groups")
