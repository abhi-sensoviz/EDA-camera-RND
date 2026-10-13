# Research programs: how the protocols were verified

These are the programs used on the live ED-AIC3000 to reverse-engineer and
verify the lens, light and live-view behaviour documented in
`../ED-AIC3000_DEVELOPER_GUIDE.md`. Measured results are in `../findings/`.

| Program | What it does | Needs | Result (2026-10-13) |
|---|---|---|---|
| `lens_probe.cpp` | Raw I2C read/write of lens register `0x0000` @0x18, cross-checked against EDATEC's `getLiquid()` / `setLiquid()` in both directions; restores the code | EDATEC's `ed-aic3x00-lib` (only for the cross-check) | Raw and vendor agree exactly (32500 / 32500, 29000 / 29000). Write ~0.68 ms, read ~0.84 ms. |
| `lens_latency.c` | Standalone C, raw i2c-dev: write → poll until the register matches, 30 writes; restores the code | nothing | Median 1.48 ms, max 2.3–3.1 ms; 3–4 of 30 first reads stale |
| `lens_optical_test.py` | Locks exposure, sweeps codes 0–46000, scores sharpness, saves the sharpest and blurriest frames; restores the code | picamera2, numpy | Inconclusive on a blank ceiling (flat). Proof came from `../camera-tests/test_autofocus.py sweep` with a target: 221–229× peak at codes 40000–42000. |
| `preview_probe.py` | Opens a picamera2 preview (QTGL or QT) for 4 s and screenshots it with `grim` | picamera2, grim | QTGL works with Qt's default and with `QT_QPA_PLATFORM=xcb`; native `wayland` aborts (EGL, exit 134) |

## Building and running (on the camera)

```bash
gcc -O2 -Wall lens_latency.c -o lens_latency && ./lens_latency
g++ -O2 -DENABLE_LIQUID lens_probe.cpp -leda_io2 -o lens_probe && ./lens_probe 32000
python3 lens_optical_test.py                 # put a detailed target in view first
XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 DISPLAY=:0 QT_QPA_PLATFORM=xcb \
    python3 preview_probe.py QTGL /tmp/shot.png
```

All of them leave the lens where it started. Stop any other program using the
camera or EDATEC's library first.

## How the protocols were found

1. **Listed the vendor package:** `dpkg -L ed-aic3x00-lib` gave a header, `libeda_io2.so`, a Python module, examples, and a `postinst` that writes `config.txt` lines and a udev rule (see `../aic3000-backup/`).
2. **Lens:**
   - `nm -DC` and `strings` on the library showed `setLiquidLens(int, unsigned char*)` and `/dev/i2c-1`.
   - `objdump -d` of `EdaIo::setLiquid` / `getLiquid` / `setLiquidLens` shows one `I2C_RDWR` to address `0x18`: register `0x0000` (16-bit, high byte first) plus a 32-bit little-endian value. Reads write the register, then read 4 bytes.
   - Values above 46000 are rejected; negative values are not.
3. **Buttons and DI:**
   - The callbacks use wiringPi `wiringPiISR(pin, INT_EDGE_BOTH)` on BCM 12 (TRIG), 20 (TUNE) and 17 (DI1).
   - They call the user's callback when the level changes; DI1 waits 100 ms first.
4. **Outputs:** `setup()` drives 13 (laser), 16/7 (status OK/NG), 21 (alarm), 22/27 (DO1/DO2). Each `open*` / `set*` call writes one of these pins.
5. **Lights:**
   - `setup()` opens `/dev/com2` at 115200 and sends `D-\r\n`.
   - Each light function builds a 4–6 byte frame `<cmd> '-' <arg> '\r' '\n'`: `1`–`4` zones, `5` work mode, `6`/`7`/`8` flash, `9` manual on/off, `A` RGB, `C` brightness, `D` version.
   - The reply parser accepts `FF board fw 0D 0A` (version) and `FF AA EE` (hardware trigger).
   - The brightness encoding switches on the firmware version, and a `.rodata` constant 9.99 gives the old encoding.
6. **Verified** each finding on the unit with the programs above and `../camera-tests/`.

The disassembly itself is kept private: it is EDATEC's code.
