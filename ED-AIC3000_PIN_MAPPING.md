# ED-AIC3000 pin mapping

Every signal on the EDATEC ED-AIC3000 smart camera: which CM5 pin, bus or
connector it uses, how to drive it, and what an application has to watch out
for.

**Unit documented:** Compute Module 5 Rev 1.0, 32 GB eMMC, EDATEC board `0x15`, light-MCU firmware
`0x01`, Raspberry Pi OS Bookworm. Pin numbers are **BCM GPIO numbers on the CM5**,
not header pin positions; the camera has no 40-pin header.

**Sources, as tagged in the tables:**
- **[M]** EDATEC user manual. It is not included in this repository; download it from https://edatec.cn/docs/assets/aic3000/ED-AIC3000-usermanual-en.pdf.
- **[D]** Our disassembly of EDATEC's `libeda_io2.so` 1.20250915.1. The disassembly itself is kept private; only the findings are documented here.
- **[L]** Checked on the live unit (pin states, device tree, I2C read/write).
- **[I]** Inferred and not yet confirmed; see "Open questions" at the end.

## 1. Quick reference

| What | Where | How it is driven |
|---|---|---|
| **Focus** (liquid lens) | I2C1 on GPIO10/11, device `/dev/i2c-1`, address **0x18** | Write register 0x0000 = code 0–46000. No GPIO. [D][L] |
| **Light zones 1–4** (TL/TR/BL/BR) | Light MCU on UART3, GPIO8/9, `/dev/com2` | Serial text command `N-1\r\n` / `N-0\r\n`. No GPIO. [M][D] |
| **Light brightness, flash, mode** | Same light MCU, `/dev/com2` | Serial commands `C-`, `6-`/`7-`/`8-`, `5-`, `9-` (section 7) [D] |
| **RGB side lights** (group of 3) | Same light MCU, `/dev/com2` | Serial command `A-<digit>\r\n` [M][D] |
| **Laser aiming spot** (red dot) | **GPIO13** | Output, high = on [D][L] |
| **Status LED: normal** (green) | **GPIO16** | Output, high = on [M][D][L] |
| **Status LED: abnormal** (red) | **GPIO7** | Output, high = on [M][D][L] |
| **System fault LED** | **GPIO21** | Output, high = on [M][D][L] |
| **DO1 / DO2** (M12 pins 8 / 9) | **GPIO22 / GPIO27** | Outputs, high after vendor `setup()` [M][D][L] |
| **DI1** (M12 pin 4) | **GPIO17** | Input, idle high [M][D][L] |
| **TRIG button** | **GPIO12** | Input, idle high, pressed = low [M][D][L] |
| **TUNE button** | **GPIO20** | Input, idle high, pressed = low [M][D][L] |
| **RS232** (M12 pins 10–12) | UART2 on GPIO4/5, `/dev/com1` | Serial port [M][L], RS232 link [I] |
| **Camera** (IMX477, 12 MP) | CSI `cam0`; control I2C `i2c-10` at 0x1a | libcamera / picamera2 [L] |
| **Power LED, network LED** | Not on GPIO | Hard-wired / Ethernet PHY [M] |

## 2. CM5 GPIO 0–27

The "State" column is what the pin showed after EDATEC's `EdaIo::setup()` had
run (`aic3000-backup/hardware/pinctrl-all-pins.txt`). "Unused" means no EDATEC
software touches the pin. Whether such a pin is wired anywhere on the camera's
board is unknown, so don't assume you can reach it.

| GPIO | ED-AIC3000 use | Dir | Pull | State | Source |
|---|---|---|---|---|---|
| 0 | ID_SDA (CM5 ID EEPROM bus) | in | up | hi | [L] |
| 1 | ID_SCL | in | up | hi | [L] |
| 2 | unused | – | up | – | [L] |
| 3 | unused | – | up | – | [L] |
| 4 | UART2 TXD, `/dev/ttyAMA2` = `/dev/com1` (RS232) | alt2 | none | hi | [L] |
| 5 | UART2 RXD | alt2 | up | hi | [L] |
| 6 | unused | – | up | – | [L] |
| **7** | **Status LED "abnormal" (red)** | out | up | lo | [M][D][L] |
| 8 | UART3 TXD, `/dev/ttyAMA3` = `/dev/com2` (light MCU) | alt2 | none | hi | [L] |
| 9 | UART3 RXD | alt2 | up | hi | [L] |
| **10** | **I2C1 SDA (liquid lens 0x18)** | alt3 | up | hi | [L] |
| **11** | **I2C1 SCL** | alt3 | up | hi | [L] |
| **12** | **TRIG button** | in | down | hi | [M][D][L] |
| **13** | **Laser aiming spot** | out | down | lo | [D][L] |
| 14 | unused (Pi UART0 default; console is on the debug UART `ttyAMA10`) | – | down | – | [L] |
| 15 | unused | – | down | – | [L] |
| **16** | **Status LED "normal" (green)** | out | down | lo | [M][D][L] |
| **17** | **DI1** (M12 pin 4) | in | down | hi | [M][D][L] |
| 18 | unused | – | down | – | [L] |
| 19 | unused | – | down | – | [L] |
| **20** | **TUNE button** | in | down | hi | [M][D][L] |
| **21** | **System fault LED** | out | down | lo | [M][D][L] |
| **22** | **DO1** (M12 pin 8) | out | down | **hi** | [M][D][L] |
| 23 | unused | – | down | – | [L] |
| 24 | unused | – | down | – | [L] |
| 25 | unused | – | down | – | [L] |
| 26 | unused | – | down | – | [L] |
| **27** | **DO2** (M12 pin 9) | out | down | **hi** | [M][D][L] |
| 28 | PCIE_PWR_EN (CM5 internal) | out | down | hi | [L] |
| 29 | FAN_TACH (CM5 internal) | – | up | hi | [L] |

How EDATEC's library drives the inputs [D]:
- **DI1 (GPIO17):** pull-down, interrupt on both edges, then a 100 ms delay before reading the level.
- **TRIG (12) and TUNE (20):** pull-down, interrupt on both edges, and the callback fires on every level change (press and release).

The idle-high reading on all three, despite their pull-downs, means the camera's
board pulls these lines high.

## 3. Buses and device nodes

| Bus / node | Pins | Device | Overlay or rule |
|---|---|---|---|
| `/dev/i2c-1` (I2C1) | GPIO10 SDA, GPIO11 SCL | Liquid-lens driver at **0x18**. No kernel driver binds it; access is raw `I2C_RDWR`. | `dtoverlay=i2c1-pi5,pins_10_11` |
| `i2c-10` (RP1 `i2c@88000`) | CSI cam0 control | IMX477 at 0x1a | `dtoverlay=imx477,cam0` |
| `/dev/ttyAMA2` → `/dev/com1` | GPIO4 TX, GPIO5 RX | RS232 transceiver → M12 pins 10–12 [I] | `dtoverlay=uart2-pi5` + `98-com.rules` |
| `/dev/ttyAMA3` → `/dev/com2` | GPIO8 TX, GPIO9 RX | Light MCU, 115200 baud | `dtoverlay=uart3-pi5` + `98-com.rules` |
| `/dev/ttyAMA10` (`serial0`) | CM5 debug UART | Boot console | stock |
| CSI `cam0` | camera connector | IMX477 (Raspberry Pi HQ sensor), 4056×3040 | `dtoverlay=imx477,cam0` |

`98-com.rules` comes from EDATEC's package. It contains:

```
KERNEL=="ttyAMA2", PROGRAM="/bin/sh -c 'echo 1'", SYMLINK+="com%c"
KERNEL=="ttyAMA3", PROGRAM="/bin/sh -c 'echo 2'", SYMLINK+="com%c"
```

## 4. External connectors

### 4.1 Power & I/O: 12-pin M12 (cable ED-ACC-AIC-PWR-C-03, bare wires) [M]

| M12 pin | Wire | Signal | Goes to |
|---|---|---|---|
| 1 | Yellow | DC− | 24 V supply − |
| 2 | White/Yellow | DC+ | 24 V supply + (24 V ±10 %, 2 A adapter recommended) |
| 3 | Brown | COMMON_IN | DI common |
| 4 | White/Brown | DI_1 | → **GPIO17** (isolated input [I]) |
| 5 | Purple | Trigger | Undefined with the HQ (IMX477) camera; light MCU on global-shutter models [I] |
| 6 | White/Purple | COMMON_OUT | DO common. **Never connect it to +24 V.** |
| 7 | Red | External Strobe | Undefined with the HQ camera; light MCU on global-shutter models [I] |
| 8 | Black | DO_1 | ← **GPIO22** |
| 9 | Green | DO_2 | ← **GPIO27** |
| 10 | Orange | RS232_GND | |
| 11 | Blue | RS232_TX | ← UART2 TX (GPIO4), `/dev/com1` [I] |
| 12 | Gray | RS232_RX | → UART2 RX (GPIO5) [I] |
| Shell | Black (thick) | PE | Earth |

**Electrical limits** [M]:
- **DI:** works with NPN or PNP sensors. The SDK manual's example drives DI1 with 5 V against COMMON_IN at ground.
- **DO:** 0.25 A maximum per channel, 0.5 A total. Fit a flyback diode on inductive loads (solenoids, relays).

### 4.2 Ethernet: 8-pin M12 A-coded (cable to RJ45) [M]

| Pin | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Signal | TRD0+ | TRD0− | TRD1+ | TRD2+ | TRD2− | TRD1− | TRD3+ | TRD3− |

The interface is `eth0`, with factory static address 192.168.1.10/24.

### 4.3 USB-C [M][L]

USB-C is used for flashing the eMMC. Hold **TRIG** while powering on to enter
`rpiboot` mass-storage mode. In normal running, `config.txt` sets
`[cm5] dtoverlay=dwc2,dr_mode=host`, so the port acts as a USB host.

## 5. Buttons and indicators [M][D][L]

| Item | Pin | Behaviour |
|---|---|---|
| TRIG button | GPIO12 | Idle high, pressed = low. Programmable. Held at power-on, it enters eMMC flashing mode. |
| TUNE button | GPIO20 | Idle high, pressed = low. Programmable (EDATEC intends it for one-press autofocus). |
| Working status LED | GPIO16 = green "normal", GPIO7 = red "abnormal" | Vendor `setScanStat(good)` drives exactly one of the two |
| System fault LED | GPIO21 | High = on (vendor `openAlarm` / `closeAlarm`) |
| Power LED | — | Red when powered |
| Network LED | — | Yellow when Ethernet is linked |
| Laser aiming spot | GPIO13 | High = on (red circular spot) |

## 6. Focus: liquid lens (no GPIO) [D][L]

| | |
|---|---|
| Bus | `/dev/i2c-1`, 7-bit address **0x18**, 16-bit register addresses, high byte first |
| Set focus | One `I2C_RDWR` message: `00 00 b0 b1 b2 b3` (register 0x0000; code as a 32-bit little-endian value; range 0–46000) |
| Read focus | Write `00 00`, then read 4 bytes; code = `b0 | b1 << 8` |
| Timing | A write takes about 0.7 ms on the bus. The register reads back the new code 1.5–3 ms later; earlier reads return the old code. The liquid itself settles optically after that; 0.12 s plus 2 dropped frames works. |
| Register 0x0028 | The vendor's `openVTemp()` writes 1 here (probably temperature compensation). It is never called during set-up. |
| Vendor quirks | `setLiquid()` rejects codes above 46000 but sends negative codes unchecked. The C++ header hides the call unless built with `-DENABLE_LIQUID`. |
| Optical proof | User sweeps with a target in view peak at code 40000–42000, 220–230× above the noise floor [L] |

## 7. Lights: light MCU on `/dev/com2` (no GPIO) [M][D]

The four light zones, their brightness and flash, and the RGB side lights are
all controlled by a microcontroller on UART3 at **115200 baud, raw mode**. Each
command is: command character, `-`, argument, `\r\n`. Where a row says **raw**,
the argument is a binary byte, not an ASCII digit.

| Bytes sent | Vendor call | Effect |
|---|---|---|
| `1-1\r\n` `2-1\r\n` `3-1\r\n` `4-1\r\n` | `enableLightSection(1..4)` | Enable zone 1 TopLeft, 2 TopRight, 3 BottomLeft, 4 BottomRight |
| `1-0\r\n` … `4-0\r\n` | `disableLightSection(1..4)` | Disable that zone |
| `5-` raw `\r\n` | `setWorkMode(m)` | 0 continuous, 1 software trigger, 2 external rising, 3 external falling, 4 external level, 5 custom (manual on/off) |
| `6-1\r\n` | `callLightFlash()` | Fire a flash |
| `7-` raw `\r\n` | `setLightFlashCount(n)` | Flash count |
| `8-` raw `\r\n` | `setLightFlashTime(ms)` | Flash duration |
| `9-` raw `01` / `00` `\r\n` | `open_light()` / `close_light()` / `setStrobeManual(v)` | Manual light on/off. `open_light()` first switches to mode 5 if needed. |
| `A-` digit `\r\n` | `setRgbLight(c)` | RGB side lights. Wire digit: `0` blue, `1` red, `2` green, `3` yellow, `4` off, `5` white. |
| `C-` hi lo `\r\n` | `setBrightnessValue(v)` | 16-bit big-endian. MCU firmware ≥ 1 (this unit): `v` = 0–100 as is. Firmware 0: `(100 − v) × 9.99`. |
| `D-\r\n` | `svQueryVersion()` | MCU replies `FF <board> <firmware> 0D 0A`. **Verified without the SDK:** reply `ff 15 01 0d 0a`. [L] |

`setRgbLight()` takes its own colour numbers (0 off, 1 red, 2 green, 3 blue,
4 yellow, 5 white) and translates them to the wire digits above.

The MCU can also send `FF AA EE`, a hardware trigger event, which the vendor
library passes to its `registerHardware` callback (global-shutter models).

**What EDATEC's `setup()` sends:** brightness 90, then `D-`.

**Behaviour** [M]:
- A zone only lights while it is enabled **and** the camera or strobe fires.
- At 25 °C keep each light pulse ≤ 25 ms with ≥ 330 ms off between pulses (duty cycle ≤ 7 %).

## 8. Notes for applications

| Need | Use on the ED-AIC3000 | Why |
|---|---|---|
| Part-present / trigger input | GPIO17 (DI1) or GPIO12 (TRIG button) | See open question 1 about polarity |
| OK / reject outputs | GPIO22 (DO1) / GPIO27 (DO2) | The real opto outputs on the M12 cable |
| Illumination | Light MCU on `/dev/com2` (section 7) | The lights are not on GPIO; don't assign light pins |
| Focus | Lens on I2C `/dev/i2c-1` @0x18 (section 6) | There is no motor or STEP/DIR/ENA |
| Pass/fail indication | GPIO16 / GPIO7 status LED, GPIO21 fault, GPIO13 laser | Board LEDs |
| User groups | `i2c`, `dialout`, `gpio`, `video` | Device ownership |

**Don't reuse pin assignments from other Raspberry Pi cameras unchanged.** On
this board, common choices collide with functions:
- 7 is the red status LED, 13 the laser, 16 the green status LED.
- 17 is the DI1 *input*. An application driving it as an output fights the opto input.
- 27 is DO2.
- 8/9 are the light-MCU UART; 10/11 are the lens I2C.

**Don't run EDATEC's `setup()` alongside your own software.** That includes their
`test_io` examples and any script built on `libedaio2`. It reconfigures GPIO
7/12/13/16/17/20/21/22/27 and takes over `/dev/com2`.

## 9. Open questions (check on the bench)

1. **DI1 and button active level.** All three read high when idle. EDATEC drives
   DI1 by applying 5 V against COMMON_IN, so the input most likely reads **low
   when active**. Software that triggers on a *rising* edge would then fire at
   the **end** of each sensor pulse. Confirm with a sensor and trigger on the
   correct edge.
2. **DO polarity.** `setup()` leaves GPIO22/27 **high**. Measure DO_1 against
   COMMON_OUT with GPIO22 at 0 and at 1 to find which level switches the load on.
3. **Light MCU commands.** Section 7 is decoded from the vendor library. Test
   each command from a separate program, with EDATEC's library *not* running,
   before building a light driver on it.
4. **RS232 link.** That `/dev/com1` is the RS232 on M12 pins 10–12 comes from
   the API naming (`writeAMA1`) and the changelog ("Release rs232"). Loop TX to
   RX to confirm.
5. **Unused GPIOs** (2, 3, 6, 14, 15, 18, 19, 23–26). It is unknown whether any
   of these reach a connector.
