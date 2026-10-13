# ED-AIC3000 hardware reference

Reverse-engineered on 2026-10-13 from `ed-aic3x00-lib` 1.20250915.1
(`/usr/lib/libeda_io2.so`; the disassembly itself is kept private) and checked
against a live unit: CM5 Rev 1.0, 32 GB eMMC, Bookworm, EDATEC board `0x15`,
light-MCU firmware `0x01`.

"Verified" below means confirmed on the live unit. Everything else is read
from the vendor library's machine code: those are the exact bytes and pins the
vendor library uses, but they were not exercised from a separate program.

## GPIO (BCM numbering)

| GPIO | Dir | Function | Level | Vendor call | After `EdaIo::setup()` |
|---|---|---|---|---|---|
| 4 / 5 | UART2 TX/RX | `/dev/ttyAMA2` = `/dev/com1`, user RS232 (`writeAMA1`, `setAMA1Callback`) | | | verified (pinctrl, udev) |
| 8 / 9 | UART3 TX/RX | `/dev/ttyAMA3` = `/dev/com2`, **light MCU**, 115200 baud | | | verified (pinctrl, udev) |
| 10 / 11 | I2C1 SDA/SCL | `/dev/i2c-1`: **liquid lens driver at 0x18** | | `setLiquid` / `getLiquid` | verified (read/write tested) |
| 13 | out | Laser aiming spot | high = on | `openLaser` / `closeLaser` | low (verified) |
| 16 | out | Status LED, "good" side | high = on | `setScanStat(true)`: 16=1, 7=0 | low (verified) |
| 7 | out | Status LED, "not good" side | high = on | `setScanStat(false)`: 16=0, 7=1 | low (verified) |
| 21 | out | Alarm / fault indicator | high = on | `openAlarm` / `closeAlarm` | low (verified) |
| 22 | out | DO1 (12-pin M12) | `setDo1High(true)` = 1 | `setDo1High` | **high** (verified) |
| 27 | out | DO2 (12-pin M12) | `setDo2High(true)` = 1 | `setDo2High` | **high** (verified) |
| 17 | in | DI1 (12-pin M12) | pull-down; both edges; 100 ms delay, then level | `registerInput` | |
| 12 | in | TRIG button | idle high, pressed = 0; both edges | `registerTrigger` | verified idle high |
| 20 | in | TUNE button | idle high, pressed = 0; both edges | `registerTune` | verified idle high |

The camera is an IMX477 on CSI `cam0`. Its control I2C is `i2c-10` at 0x1a, so
it is separate from the lens bus.

The EDATEC manual confirms the status-LED pins: GPIO16 is "normal" (green) and
GPIO7 is "abnormal" (red).

This file is superseded by `../ED-AIC3000_PIN_MAPPING.md`, which adds the M12
wire colours, the electrical limits and application notes.

**For applications on this camera:** the lights are driven by the MCU (below),
not GPIO, so don't assign light pins. Use 17 (DI1) or 12 (TRIG) as the trigger
input, 22/27 (DO1/DO2) as outputs, and the I2C lens for focus. GPIO 17, 27
and 13 are DI1, DO2 and the laser, so pin maps copied from other cameras
collide here.

## Liquid lens (I2C 0x18 on `/dev/i2c-1`)

| | |
|---|---|
| Write focus | One `I2C_RDWR` message: `00 00 b0 b1 b2 b3` (register 0x0000, code little-endian, 0..46000) |
| Read focus | Write `00 00`, then read 4 bytes; code = `b0 + (b1 << 8)` |
| Timing | Write ≈ 0.7 ms. The register reads back the new code 1.5–3 ms later; earlier reads return the old code. |
| Vendor quirks | `setLiquid()` rejects values above 46000 but sends negative values unchecked. The C++ header hides the call unless built with `-DENABLE_LIQUID`. |
| Register 0x0028 | Vendor `openVTemp()` writes 1 here (probably temperature compensation). Never called by the vendor library. |

This protocol has been verified on the live unit (see `../research/`).

## Light MCU protocol (`/dev/com2` → ttyAMA3, 115200, raw)

Each command is: command character, `-`, argument, `\r\n`. Where the table
says "raw byte", the argument is a binary value, not an ASCII digit.

| Bytes sent | Vendor call | Meaning |
|---|---|---|
| `1-1\r\n` … `4-1\r\n` | `enableLightSection(1..4)` | Enable light zone 1–4 (ASCII `'1'`) |
| `1-0\r\n` … `4-0\r\n` | `disableLightSection(1..4)` | Disable light zone 1–4 (ASCII `'0'`) |
| `5-` raw byte `\r\n` | `setWorkMode(m)` | 0 continuous, 1 software trigger, 2 external rising, 3 external falling, 4 external level, 5 custom (manual on/off) |
| `6-1\r\n` | `callLightFlash()` | Fire a flash |
| `7-` raw byte `\r\n` | `setLightFlashCount(n)` | Flash count |
| `8-` raw byte `\r\n` | `setLightFlashTime(ms)` | Flash time |
| `9-` raw `01` / `00` `\r\n` | `open_light()` / `close_light()` / `setStrobeManual(v)` | Manual light on/off. `open_light()` first switches to mode 5 if needed. |
| `A-` ASCII digit `\r\n` | `setRgbLight(c)` | RGB side light. Wire digit: `0` blue, `1` red, `2` green, `3` yellow, `4` off, `5` white. The API colour numbers (0 off, 1 red, 2 green, 3 blue, 4 yellow, 5 white) are remapped to these. |
| `C-` hi lo `\r\n` | `setBrightnessValue(v)` | 16-bit big-endian. MCU firmware 0: `(100 − v) × 9.99` (inverted, 0..999). Firmware ≥ 1 (this unit): `v` as is, 0..100. |
| `D-\r\n` | `svQueryVersion()` | Version query |

**What the MCU sends back:**
- `FF <board> <firmware> 0D 0A`: the version reply. It sets `G_BOARD_VERSION` and `G_FIRMWARE_VERSION`, which in turn select the brightness encoding.
- `FF AA EE`: a hardware trigger event, which fires the `registerHardware` callback (global-shutter models).

**What `setup()` sends:** it opens `/dev/com2` at 115200, sets brightness to 90 and
queries the version. Area lights only switch on while their zone is enabled
**and** the camera or strobe fires (see the manual).

**LED duty limit (from the manual, at 25 °C):** on for ≤ 25 ms, off for
≥ 330 ms, which is a duty cycle of 7 % or less.

## Optional `/etc/ed-aic3000.ini`

The keys are `dido_on`, `button_on`, `led_on` and `laser_on`, and each defaults
to 1 when the file is absent (it is absent on this unit). Setting one to 0 makes
the vendor library skip that group's GPIO setup and calls.

## What the vendor package changes on the OS (its `postinst`)

- **Writes `/etc/udev/rules.d/98-com.rules`:** `ttyAMA2` → `/dev/com1`, `ttyAMA3` → `/dev/com2`.
- **Appends these lines to `config.txt` if they are missing:** `camera_auto_detect=1`,
  `display_auto_detect=1`, `dtparam=i2c_arm=on`, `dtoverlay=imx477,cam0`,
  `dtoverlay=uart2-pi5`, `dtoverlay=uart3-pi5`, `dtoverlay=i2c1-pi5,pins_10_11`.
  All are stock Raspberry Pi overlays.
- **Copies `ed-imx477.dtbo` to `/boot/overlays/`.** Nothing uses it: it is an older
  copy of the stock `imx477` overlay, and `config.txt` loads the stock one.

The library needs `libwiringPi.so` (no version tied), `libstdc++6` and `libc6`.
The package declares no dependencies.
