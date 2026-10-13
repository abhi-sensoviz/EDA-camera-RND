# ED-AIC3000 direct hardware tests (no EDATEC SDK)

These two scripts talk to the camera's hardware directly, using libraries
already installed on the camera (pyserial, smbus2, gpiozero, picamera2, numpy).
They confirm the protocols in `../ED-AIC3000_PIN_MAPPING.md` and
`../ED-AIC3000_DEVELOPER_GUIDE.md`, which any SDK-free driver relies on.

Already confirmed on the unit:
- The light MCU answers `D-\r\n` with `ff 15 01 0d 0a` (board 0x15, firmware 0x01).
- The lens reads back over raw I2C.

## Live view

Both scripts open a **live camera window on the camera's desktop**, with a yellow banner
showing the current step (light commands; lens code and sharpness). This works when started from
the camera's own terminal **and** over SSH: the scripts find the desktop by themselves.
Watch it over VNC (`xtigervncviewer 192.168.1.10::5900`). Add `--no-preview` to run without it.

## Copy to the camera

From this PC:

```bash
scp -r ~/Desktop/EDA-smartCam/camera-tests pi@192.168.1.10:~/
ssh pi@192.168.1.10          # or open a terminal on the camera desktop over VNC
cd ~/camera-tests
```

**Before running, stop anything that uses the SDK or the camera**, for example
`autoFocus.py`: those take over the light port, the GPIOs and the camera. The
light test warns you if the light port is still in use.

## 1. Lights: `test_lights.py`

```bash
python3 test_lights.py                # guided: pauses before each step and asks what you saw
python3 test_lights.py --auto         # same steps, no pauses
python3 test_lights.py --only zones   # one group: version rgb zones levels flash camera gpio
python3 test_lights.py --send "A-1"   # one raw command (RGB red); "\xNN" for raw bytes, e.g. "5-\x05"
```

| Step | Sends | You should see |
|---|---|---|
| version | `D-` | A printed reply: board 0x15, firmware 0x01 |
| rgb | `A-1/2/0/3/5`, then `A-4` | Side lights red → green → blue → yellow → white → off |
| zones | `5-` mode 5, `1-1`…`4-1`, `9-` on/off | All 4 area lights for 1 s, then TopLeft, TopRight, BottomLeft, BottomRight one at a time |
| levels | `C-` 15 / 50 / 100 % | Three 1 s flashes, dim → bright |
| flash | `7-` count 5, `8-` 10 ms, `6-1` in modes 5 and 1 | A short burst of flashes (shows which mode the flash command works in) |
| camera | mode 0 while the camera streams for 2 s | Area lights lit or strobing only while the camera runs |
| gpio | GPIO 13 / 16 / 7 / 21 | Laser spot, green status LED, red status LED, fault LED, 1 s each |

Every byte sent and every reply is printed. At the end the script restores the
state EDATEC's `setup()` leaves (light off, all zones enabled, brightness 90, RGB
off) and lists your y/n answers.

**Safety:**
- The area LEDs are only switched on manually for 1 s at a time.
- Don't look into the laser.
- The DO outputs (GPIO22/27) are never touched.

## 2. Focus: `test_autofocus.py`

Put something with fine detail (printed text, a checkerboard) in front of the
camera at your working distance first. The camera currently sees a blank
surface, which gives a flat curve.

```bash
python3 test_autofocus.py read                 # current lens code
python3 test_autofocus.py set 30000            # write and read back
python3 test_autofocus.py view                 # live view + manual focus: type a code, +500, -500, a = autofocus, p = photo, q = quit
python3 test_autofocus.py sweep                # sharpness at codes 0..46000 -> proves the lens focuses
python3 test_autofocus.py autofocus            # coarse 2000 + fine 200 search, keeps the best focus
python3 test_autofocus.py buttons              # TUNE = autofocus, TRIG = full-res photo, Ctrl+C quits
```

Options:
- `--start/--stop/--step` (sweep)
- `--lo/--hi/--coarse/--fine` (autofocus and buttons)
- `--settle` (default 0.12 s)
- `--roi` (default 0.5, the centre half of the image)

Results go to `./af_results/`: a CSV of each sweep, the sharpest and blurriest
frames, the autofocus result image, and photos. The sweep prints a verdict at
the end: *"the I2C lens code changes optical focus"* or *"flat curve"*. If
anything fails or you press Ctrl+C, the lens goes back to its starting code.

## Send back

Paste the terminal output from both scripts, your y/n answers from the light
test, and the sweep CSV (or the "VERDICT" line). That confirms or corrects each
line of the pin-mapping document before any driver depends on it.
