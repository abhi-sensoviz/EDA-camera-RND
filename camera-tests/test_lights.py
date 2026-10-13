#!/usr/bin/python3
"""
ED-AIC3000 light test - talks to the hardware directly, no EDATEC SDK.

  Light MCU   : /dev/com2 (ttyAMA3, GPIO8/9), 115200 baud, text commands "<cmd>-<arg>\\r\\n"
  Indicators  : GPIO13 laser, GPIO16 status OK (green), GPIO7 status NG (red), GPIO21 fault

The MCU command set was decoded from EDATEC's libeda_io2.so (see
../ED-AIC3000_PIN_MAPPING.md section 7). This script is what confirms it on the
real hardware, so it prints every byte it sends and everything the MCU replies.

Run on the camera (a live camera view opens on the camera's desktop - also when
started over SSH - showing each command as it is sent; --no-preview to skip it):
    python3 test_lights.py                 # guided: pauses before each step
    python3 test_lights.py --auto          # same steps, no pauses
    python3 test_lights.py --only rgb      # one group: version rgb zones levels flash gpio camera
    python3 test_lights.py --send "1-1"    # send one raw command (\\xNN allowed, e.g. "5-\\x05")

Safety: the area LEDs are only ever switched on manually for 1 s at a time
(EDATEC's own example does the same; their library force-switches them off after
3 s). Don't look into the laser. The DO outputs (GPIO22/27) are not touched.
"""
import argparse
import os
import sys
import time

import serial   # python3-serial (pyserial) - preinstalled on the camera

PORT_CANDIDATES = ("/dev/com2", "/dev/ttyAMA3")
ZONE_NAMES = {1: "TopLeft", 2: "TopRight", 3: "BottomLeft", 4: "BottomRight"}
RGB_WIRE = {"off": 4, "red": 1, "green": 2, "blue": 0, "yellow": 3, "white": 5}
INDICATORS = [(13, "laser aiming spot"), (16, "status LED OK (green)"),
              (7, "status LED NG (red)"), (21, "system fault LED")]
MANUAL_ON_S = 1.0     # never hold the area LEDs on longer than this here
OFF_GAP_S = 0.6
VIEW_SIZE = (1014, 760)


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


class LiveView:
    """Camera preview window with a one-line banner, kept open for the whole test."""

    def __init__(self):
        from picamera2 import Picamera2, Preview
        self.cam = Picamera2()
        self.cam.configure(self.cam.create_preview_configuration(main={"size": VIEW_SIZE}))
        self.cam.start_preview(Preview.QTGL, x=40, y=40, width=VIEW_SIZE[0], height=VIEW_SIZE[1])
        self.cam.start()
        self.ok = True

    def status(self, text):
        if not self.ok:
            return
        try:
            import numpy as np
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGBA", VIEW_SIZE, (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
            except OSError:
                font = ImageFont.load_default()
            draw.rectangle([0, 0, VIEW_SIZE[0], 48], fill=(0, 0, 0, 160))
            draw.text((12, 7), text, fill=(255, 230, 0, 255), font=font)
            self.cam.set_overlay(np.array(img))
        except Exception as e:              # the view is a convenience, never fatal
            print(f"(overlay failed: {e})")
            self.ok = False

    def close(self):
        self.cam.close()


LIVE = None    # LiveView while the test runs


def show(text):
    if LIVE:
        LIVE.status(text)


# --------------------------------------------------------------- MCU link ---

class LightMcu:
    def __init__(self, port):
        self.port = port
        self.ser = serial.Serial(port, 115200, bytesize=8, parity="N", stopbits=1,
                                 timeout=0.05)
        self.ser.reset_input_buffer()
        self.firmware = None

    def send(self, payload, note="", wait=0.08):
        """Send <payload> + CR LF, print it, return whatever comes back."""
        frame = payload + b"\r\n"
        self.ser.write(frame)
        self.ser.flush()
        time.sleep(wait)
        reply = self.ser.read(256)
        shown = frame.decode("latin-1").encode("unicode_escape").decode()
        line = f"  -> {shown:<14} [{frame.hex(' ')}]"
        if note:
            line += f"  {note}"
        show(f"{shown}   {note}")
        if reply:
            line += f"\n  <- reply [{reply.hex(' ')}]"
        print(line)
        return reply

    # The commands, exactly as EDATEC's library builds them
    def query_version(self):
        reply = self.send(b"D-", "version query", wait=0.3)
        i = reply.find(b"\xff")
        if i >= 0 and len(reply) >= i + 5 and reply[i + 3:i + 5] == b"\r\n":
            board, fw = reply[i + 1], reply[i + 2]
            self.firmware = fw
            print(f"     board 0x{board:02x}, light firmware 0x{fw:02x}")
            return board, fw
        print("     no version reply (brightness will use the firmware>=1 encoding)")
        return None

    def zone(self, n, on):
        self.send(f"{n}-{1 if on else 0}".encode(),
                  f"zone {n} {ZONE_NAMES[n]} {'enable' if on else 'disable'}")

    def work_mode(self, mode):
        names = {0: "continuous", 1: "software trigger", 2: "ext rising",
                 3: "ext falling", 4: "ext level", 5: "custom/manual"}
        self.send(b"5-" + bytes([mode]), f"work mode {mode} ({names.get(mode, '?')})")

    def manual(self, on):
        self.send(b"9-" + bytes([1 if on else 0]), f"manual light {'ON' if on else 'off'}")

    def brightness(self, percent):
        percent = max(0, min(100, int(percent)))
        value = percent if (self.firmware is None or self.firmware >= 1) else int((100 - percent) * 9.99)
        self.send(b"C-" + bytes([(value >> 8) & 0xFF, value & 0xFF]), f"brightness {percent}% (wire {value})")

    def rgb(self, name):
        self.send(f"A-{RGB_WIRE[name]}".encode(), f"RGB side light {name}")

    def flash_count(self, n):
        self.send(b"7-" + bytes([n & 0xFF]), f"flash count {n}")

    def flash_time(self, ms):
        self.send(b"8-" + bytes([ms & 0xFF]), f"flash time {ms} ms")

    def flash(self):
        self.send(b"6-1", "fire flash")

    def safe_off(self):
        """Leave things as EDATEC's setup() would: light off, zones on, brightness 90, RGB off."""
        try:
            self.manual(False)
            for n in ZONE_NAMES:
                self.zone(n, True)
            self.brightness(90)
            self.rgb("off")
        except Exception as e:      # noqa: BLE001 - best effort on the way out
            print(f"  (cleanup error: {e})")


# ------------------------------------------------------------- helpers ---

def port_users(dev):
    """PIDs (other than ours) holding the serial port open - e.g. an SDK script."""
    real = os.path.realpath(dev)
    users = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) == os.getpid():
            continue
        fd_dir = f"/proc/{pid}/fd"
        try:
            for fd in os.listdir(fd_dir):
                if os.path.realpath(os.path.join(fd_dir, fd)) == real:
                    cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode()
                    users.append(f"{pid}: {cmd.strip()}")
                    break
        except OSError:
            continue
    return users


def step(title, auto):
    print(f"\n=== {title} ===")
    show(title)
    if not auto:
        input("    press Enter to run this step (Ctrl+C to stop)... ")


def look(what, auto):
    print(f"    LOOK: {what}")
    if not auto:
        r = input("    did you see it? [y/n/Enter=skip] ").strip().lower()
        if r in ("y", "n"):
            RESULTS.append((what, r == "y"))


RESULTS = []


# --------------------------------------------------------------- tests ---

def t_version(mcu, auto):
    step("1. Light MCU version", auto)
    mcu.query_version()


def t_rgb(mcu, auto):
    step("2. RGB side lights (group of 3)", auto)
    for name in ("red", "green", "blue", "yellow", "white"):
        mcu.rgb(name)
        time.sleep(1.2)
    mcu.rgb("off")
    look("RGB side lights went red, green, blue, yellow, white, then off", auto)


def t_zones(mcu, auto):
    step("3. Area light zones (manual mode, 1 s pulses)", auto)
    mcu.work_mode(5)
    mcu.brightness(30)
    for n in ZONE_NAMES:
        mcu.zone(n, True)
    mcu.manual(True)
    time.sleep(MANUAL_ON_S)
    mcu.manual(False)
    look("all 4 area lights flashed on for ~1 s", auto)
    for n in ZONE_NAMES:
        time.sleep(OFF_GAP_S)
        for m in ZONE_NAMES:
            mcu.zone(m, m == n)
        mcu.manual(True)
        time.sleep(MANUAL_ON_S)
        mcu.manual(False)
        look(f"only zone {n} ({ZONE_NAMES[n]}) lit", auto)
    for n in ZONE_NAMES:
        mcu.zone(n, True)


def t_levels(mcu, auto):
    step("4. Brightness levels 15% / 50% / 100% (manual mode, 1 s each)", auto)
    mcu.work_mode(5)
    for n in ZONE_NAMES:
        mcu.zone(n, True)
    for level in (15, 50, 100):
        time.sleep(OFF_GAP_S)
        mcu.brightness(level)
        mcu.manual(True)
        time.sleep(MANUAL_ON_S)
        mcu.manual(False)
    look("three flashes, dim -> medium -> bright", auto)


def t_flash(mcu, auto):
    step("5. Flash command (count 5 x 10 ms) in manual mode, then software-trigger mode", auto)
    for n in ZONE_NAMES:
        mcu.zone(n, True)
    mcu.brightness(50)
    mcu.flash_count(5)
    mcu.flash_time(10)
    for mode in (5, 1):
        mcu.work_mode(mode)
        time.sleep(0.2)
        mcu.flash()
        time.sleep(1.0)
        look(f"a short burst of flashes in work mode {mode}", auto)
    mcu.work_mode(5)
    mcu.manual(False)


def t_camera(mcu, auto):
    step("6. Lights synced to the camera (work mode 0, camera streaming 2 s)", auto)
    for n in ZONE_NAMES:
        mcu.zone(n, True)
    mcu.brightness(30)
    if LIVE:
        # The live view is already streaming - just switch the MCU to follow it.
        mcu.work_mode(0)
        try:
            time.sleep(2.0)
        finally:
            mcu.work_mode(5)
            mcu.manual(False)
        look("area lights lit/strobed with the live view for 2 s, then stopped", auto)
        return
    try:
        from picamera2 import Picamera2
    except ImportError:
        print("    picamera2 not available - skipped")
        return
    mcu.work_mode(0)
    cam = Picamera2()
    try:
        cam.configure(cam.create_preview_configuration())
        cam.start()
        time.sleep(2.0)
    finally:
        cam.close()
        mcu.work_mode(5)
        mcu.manual(False)
    look("area lights strobed/lit while the camera was streaming, and stopped after", auto)


def t_gpio(auto):
    step("7. GPIO indicators: laser, status OK, status NG, fault (1 s each)", auto)
    from gpiozero import LED
    for pin, name in INDICATORS:
        led = LED(pin)
        try:
            print(f"  GPIO{pin} high -> {name}")
            show(f"GPIO{pin} on: {name}")
            led.on()
            time.sleep(1.0)
        finally:
            led.off()
            led.close()
        look(f"{name} came on for 1 s", auto)


TESTS = {"version": t_version, "rgb": t_rgb, "zones": t_zones, "levels": t_levels,
         "flash": t_flash, "camera": t_camera, "gpio": None}


def unescape(text):
    return text.encode("latin-1").decode("unicode_escape").encode("latin-1")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--auto", action="store_true", help="no pauses")
    ap.add_argument("--only", choices=list(TESTS), action="append", help="run only these groups")
    ap.add_argument("--send", help='send one raw command, e.g. "1-1" or "5-\\x05" (CR LF added)')
    ap.add_argument("--port", help="serial port (default /dev/com2)")
    ap.add_argument("--no-preview", action="store_true", help="run without the live camera view")
    args = ap.parse_args()

    port = args.port or next((p for p in PORT_CANDIDATES if os.path.exists(p)), None)
    if not port:
        sys.exit("light MCU port not found (/dev/com2 or /dev/ttyAMA3)")
    others = port_users(port)
    if others:
        print("WARNING: another program has the light port open - stop it first:")
        print("\n".join("  " + o for o in others))
        if input("continue anyway? [y/N] ").strip().lower() != "y":
            sys.exit(1)

    mcu = LightMcu(port)
    print(f"light MCU on {port} (-> {os.path.realpath(port)}) at 115200 baud")

    if args.send:
        mcu.send(unescape(args.send), "raw command", wait=0.3)
        return

    global LIVE
    if not args.no_preview:
        if prepare_display():
            try:
                LIVE = LiveView()
                show("light test - live view")
            except Exception as e:      # camera busy / no picamera2: carry on without it
                print(f"(live view unavailable: {e})")
        else:
            print("(no desktop display - running without the live view)")

    groups = args.only or list(TESTS)
    try:
        if "version" not in groups:
            mcu.query_version()     # brightness encoding depends on it
        for g in groups:
            if g == "gpio":
                t_gpio(args.auto)
            else:
                TESTS[g](mcu, args.auto)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        print("\n=== restoring: light off, all zones enabled, brightness 90, RGB off ===")
        mcu.safe_off()
        mcu.ser.close()
        if LIVE:
            LIVE.close()

    if RESULTS:
        print("\n=== what you reported ===")
        for what, ok in RESULTS:
            print(f"  [{'OK ' if ok else 'NO '}] {what}")


if __name__ == "__main__":
    main()
