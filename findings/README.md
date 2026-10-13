# Findings: measured results on the ED-AIC3000 (2026-10-13)

Results measured on the live unit (CM5 Rev 1.0, board `0x15`, light firmware
`0x01`). The programs that produced them are in `../research/` and
`../camera-tests/`.

## 1. Liquid lens changes optical focus

Source: `autofocus-sweeps/*.csv`, produced by `camera-tests/test_autofocus.py sweep`.
Each sweep has exposure and white balance locked; sharpness is Tenengrad over
the centre half of a 1014×760 frame.

| Sweep | Scene | Peak (code → sharpness) | Floor | Ratio | Reading |
|---|---|---|---|---|---|
| `20260629_203257` | blank ceiling | 30000 → 7 | ~5–7 | 1.3× | flat: no detail in view |
| `20260629_203855` | scene changing during the sweep (brightness 29–75) | 6000 → 39 | 3 | 12.8× | unreliable: lighting moved |
| `20260629_203911` | target near the end of the range | 46000 → 82 | 18 | 4.5× | peak at or beyond the top of the range |
| `20260629_203943` | **detailed target** | **42000 → 1287** | ~6 | **221×** | clear focus peak |
| `20260629_204006` | **detailed target** | **40000 → 2132** | ~9 | **229×** | clear focus peak |

Curve for the last sweep:

```
code   20000 24000 28000 30000 32000 34000 36000 38000 40000 42000 44000 46000
sharp      9    12    17    26    40    64   182   839  2132   836   235   127
```

**Conclusions:**
- The I2C register `0x0000` on device `0x18` controls optical focus.
- At this working distance, focus is at about code 40000–42000.
- The peak is about ±2000 codes wide at half height, which suits a 2000-code coarse step and a 200-code fine step.
- With no detail in view, the curve is flat: a max/min ratio below 1.5 means "no signal".

## 2. Lens protocol and timing

Source: `research/lens_probe.cpp`, `research/lens_latency.c`, and a driver test run on the unit.

| Check | Result |
|---|---|
| Raw I2C read vs EDATEC `getLiquid()` | identical (32500 / 32500) |
| Raw write 32000 → vendor read | 32000; vendor `setLiquid(32500)` → raw read 32500 |
| Write transaction | ~0.68–0.7 ms |
| Read transaction | ~0.8 ms |
| Write → register reflects it | **1.5 ms median, 3.1 ms worst** of 30; 3/30 first reads after back-to-back writes were stale |
| Burst | 200 increasing writes in 136 ms, ending exactly at the last commanded code |
| Holding | the code stays after the bus device is closed and across process restarts |
| Clamping | a driver must clamp: the vendor sends negative values unchecked |

## 3. Light MCU

| Check | Result |
|---|---|
| `D-\r\n` sent with no SDK (pyserial on `/dev/com2`) | reply `ff 15 01 0d 0a` = board 0x15, firmware 0x01, the same as the SDK reports |
| Full command set (`test_lights.py`) | reported working by the user. Which mode the flash commands need, and the camera-synced behaviour, are still to be recorded. |

## 4. GPIO and buttons

- **Idle levels:** GPIO12 (TRIG), GPIO20 (TUNE) and GPIO17 (DI1) read **high** with the internal pull-down, so the board pulls them up externally. The buttons read **low** when pressed.
- **After the vendor's `setup()`:** 7/13/16/21 are outputs at low, and 22/27 are outputs at **high**.
- **Linux numbering:** all of these are on `gpiochip0` = `pinctrl-rp1`, and the line offset equals the BCM number (kernel 6.12).

## 5. Camera, live view and tooling

- **Live view:**
  - The picamera2 `Preview.QTGL` works on the camera's labwc desktop through Xwayland (`QT_QPA_PLATFORM=xcb`).
  - Native Wayland crashes with an EGL error (exit 134).
  - Starting over SSH works after setting `DISPLAY=:0` and `XDG_RUNTIME_DIR=/run/user/1000`.
- **Frame format:** the GL preview **rejects `RGB888`** ("Format RGB888 not supported by QGlPicamera2 preview"); `XBGR8888` works.
- **Python on the camera:** version 3.11 does not allow backslashes inside f-string expressions, which breaks code written for 3.12.
- **Camera clock:** about 106 days behind (no NTP without internet). Fix it before running `apt`.

## 6. OS and vendor packaging

- **Our application needs Trixie:** it requires Qt ≥ 6.8, and Bookworm ships 6.4.
- **EDATEC and Trixie:** EDATEC currently supports Bookworm only ("Trixie temporarily not supported").
- **What EDATEC's package actually does:**
  - Adds stock overlays to `config.txt`.
  - Writes one udev rule.
  - Copies an unused, older copy of the stock `imx477` overlay.
  - Ships a library that declares **no** package dependencies and links `libwiringPi.so` with no version.
- **EDATEC repository:** a single `stable` suite (codename buster) serves every OS.
