# ED-AIC3000: building software without the EDATEC SDK

This guide covers everything needed to drive the EDATEC ED-AIC3000 smart camera
from your own code, with no EDATEC library:
- pin and interface map,
- GPIO,
- the liquid-lens focus protocol,
- the light-MCU protocol,
- the camera,
- a recommended start-up and shutdown sequence.

It was written on 2026-10-13 from a disassembly of `ed-aic3x00-lib`
1.20250915.1, EDATEC's manual, and tests on a live unit (CM5 Rev 1.0, board
`0x15`, light firmware `0x01`).

**Status tags used throughout:**
- **[V]** verified on the unit.
- **[U]** confirmed by a user test run (the `camera-tests/` scripts).
- **[D]** decoded from the vendor library and not independently tested yet.
- **[?]** unknown or inferred.

**Related files:**
- `ED-AIC3000_PIN_MAPPING.md`: full pin table, M12 wire colours, electrical limits.
- `camera-tests/test_lights.py`, `camera-tests/test_autofocus.py`: working reference implementations of everything below.
- `aic3000-backup/`: OS configuration, hardware dumps and inventory from the unit. EDATEC's own files are not in the public repository; see its README for where to download them.
- `research/`: the programs used to verify these protocols on the unit, with results.

---

## 1. System overview

```
                        ┌─ I2C1  /dev/i2c-1  GPIO10 SDA, GPIO11 SCL ──► lens driver @0x18 ──► liquid lens
                        │                                                (focus code 0..46000)
                        ├─ UART3 /dev/com2   GPIO8 TX, GPIO9 RX ──────► light MCU ──► 4 light zones (TL/TR/BL/BR)
                        │        115200 8N1, text "X-arg\r\n"             │            + 3 RGB side LEDs
  Raspberry Pi CM5 ─────┤                                                 └─ (Trigger/Strobe M12 pins, GS models [?])
  (your software)       ├─ GPIO  gpiochip0 (pinctrl-rp1), line = BCM number
                        │        out: 13 laser, 16 status OK, 7 status NG, 21 fault, 22 DO1, 27 DO2
                        │        in : 17 DI1, 12 TRIG button, 20 TUNE button
                        ├─ CSI cam0 ── IMX477 12 MP (control I2C on i2c-10 @0x1a; via libcamera)
                        └─ UART2 /dev/com1   GPIO4 TX, GPIO5 RX ──────► RS232 on the M12 power/IO cable [?]
```

There are three separate subsystems, and none depends on another:
- **Focus** is a register write to a lens-driver device on I2C.
- **Lights** are text commands to a microcontroller on a UART.
- **I/O** is plain GPIO.

The camera itself goes through libcamera.

---

## 2. OS prerequisites

These are exactly what EDATEC's package installs, with none of its library.
They apply to both Bookworm and Trixie.

**`/boot/firmware/config.txt`** (stock Raspberry Pi overlays only) [V]:

```ini
[all]
dtparam=i2c_arm=on
dtoverlay=imx477,cam0
dtoverlay=uart2-pi5
dtoverlay=uart3-pi5
dtoverlay=i2c1-pi5,pins_10_11
```

**`/etc/udev/rules.d/98-com.rules`** (stable names for the two UARTs) [V]:

```
KERNEL=="ttyAMA2", PROGRAM="/bin/sh -c 'echo 1'", SYMLINK+="com%c"
KERNEL=="ttyAMA3", PROGRAM="/bin/sh -c 'echo 2'", SYMLINK+="com%c"
```

**Groups** for the user your software runs as:

| Device | Owner group |
|---|---|
| `/dev/i2c-1` | `i2c` |
| `/dev/com2` (`ttyAMA3`) | `dialout` |
| `/dev/gpiochip0` | `gpio` |
| camera | `video` (and `render`) |

```bash
sudo usermod -aG i2c,dialout,gpio,video,render <user>
```

**Libraries:**
- **Python:** `python3-serial`, `python3-smbus2`, `python3-gpiozero` (lgpio backend), `python3-picamera2`, `python3-numpy`.
- **C/C++:** kernel headers (`linux/i2c-dev.h`, `termios.h`), `libgpiod-dev` (v2 API on Trixie, v1.6 on Bookworm), `libcamera-dev`.

**Never run alongside your software:** anything calling EDATEC's `EdaIo::setup()`
(their `test_io` examples, the old `autoFocus.py`). It takes over
GPIO 7/12/13/16/17/20/21/22/27 through wiringPi and opens `/dev/com2`, which
fights with your code.

---

## 3. Pin and interface map

| Function | Interface | Pin / node | Direction and level | Status |
|---|---|---|---|---|
| Focus (liquid lens) | I2C1 | GPIO10 SDA, GPIO11 SCL, `/dev/i2c-1`, addr **0x18** | register write / read | [V] |
| Light zones, brightness, flash, RGB | UART3 | GPIO8 TX, GPIO9 RX, `/dev/com2` → `ttyAMA3` | 115200 8N1 | [V] link, [U] commands |
| RS232 (M12 pins 10 GND, 11 TX, 12 RX) | UART2 | GPIO4 TX, GPIO5 RX, `/dev/com1` → `ttyAMA2` | | [?] |
| Laser aiming spot | GPIO | **13** | out, high = on | [V] |
| Status LED "normal" (green) | GPIO | **16** | out, high = on | [V] |
| Status LED "abnormal" (red) | GPIO | **7** | out, high = on | [V] |
| System fault LED | GPIO | **21** | out, high = on | [V] |
| DO1 (M12 pin 8, black wire) | GPIO | **22** | out; vendor leaves it **high** | [V] pin, [?] polarity |
| DO2 (M12 pin 9, green wire) | GPIO | **27** | out; vendor leaves it **high** | [V] pin, [?] polarity |
| DI1 (M12 pin 4, white/brown) | GPIO | **17** | in, idle **high** | [V] idle, [?] active level |
| TRIG button | GPIO | **12** | in, idle high, pressed **low** | [V][U] |
| TUNE button | GPIO | **20** | in, idle high, pressed **low** | [V][U] |
| Camera | CSI cam0 | IMX477; control I2C `i2c-10` @0x1a | libcamera | [V] |

**GPIO chip:** on kernel 6.12, all of these are on **`gpiochip0` = `pinctrl-rp1`**,
and the line offset equals the BCM number [V]. Older Pi 5 kernels numbered RP1
as `gpiochip4`, so look the chip up by its label `pinctrl-rp1` rather than
hard-coding the number.

**Electrical (manual):**
- **Supply:** 24 V DC ±10 % (2 A adapter).
- **DO:** 0.25 A maximum per channel, 0.5 A total; fit a flyback diode on inductive loads; **never connect COMMON_OUT to +24 V**.
- **DI:** NPN or PNP sensors; EDATEC's example drives DI1 with 5 V against COMMON_IN.

The full 12-pin and 8-pin M12 tables are in `ED-AIC3000_PIN_MAPPING.md`.

---

## 4. GPIO

### 4.1 What EDATEC's `setup()` does (your reference starting state)

| Line | Mode | Initial value | Notes |
|---|---|---|---|
| 13, 16, 7, 21 | output | 0 | laser and LEDs off |
| 22, 27 | output | **1** | DO1 / DO2 |
| 17 | input, pull-down, both edges | – | vendor waits 100 ms after an edge, then reads the level |
| 12, 20 | input, pull-down, both edges | – | callback on every change (press and release) |

The inputs read **high when idle** even with the internal pull-down, so the
camera's board pulls them up externally. For the buttons, pressed = **low** [V].
For DI1, "active" is probably low as well (an opto-isolated input pulling the
line down), but that is not confirmed [?]. Check it with your sensor before
choosing which edge to trigger on.

### 4.2 Python (gpiozero, as used in the test scripts) [U]

```python
from gpiozero import LED, DigitalOutputDevice, Button

laser    = LED(13)
ok_led   = LED(16)
ng_led   = LED(7)
fault    = LED(21)
do1      = DigitalOutputDevice(22, initial_value=True)   # match the vendor default until polarity is known
do2      = DigitalOutputDevice(27, initial_value=True)

trig = Button(12, pull_up=None, active_state=False, bounce_time=0.02)  # external pull-up, active low
tune = Button(20, pull_up=None, active_state=False, bounce_time=0.02)
di1  = Button(17, pull_up=None, active_state=False, bounce_time=0.005) # active level: verify!

trig.when_pressed = lambda: print("TRIG")
tune.when_pressed = lambda: print("TUNE")

def show_result(good: bool):
    ok_led.value, ng_led.value = good, not good          # vendor setScanStat(good)
```

### 4.3 C, libgpiod v2 (Trixie)

```c
#include <gpiod.h>
#include <stdio.h>

int main(void) {
    struct gpiod_chip *chip = gpiod_chip_open("/dev/gpiochip0");      /* label "pinctrl-rp1" */

    /* outputs: laser, status OK/NG, fault -> 0 */
    unsigned int outs[] = {13, 16, 7, 21};
    struct gpiod_line_settings *out = gpiod_line_settings_new();
    gpiod_line_settings_set_direction(out, GPIOD_LINE_DIRECTION_OUTPUT);
    gpiod_line_settings_set_output_value(out, GPIOD_LINE_VALUE_INACTIVE);

    /* inputs: TRIG, TUNE, DI1 - both edges, kernel debounce 5 ms */
    unsigned int ins[] = {12, 20, 17};
    struct gpiod_line_settings *in = gpiod_line_settings_new();
    gpiod_line_settings_set_direction(in, GPIOD_LINE_DIRECTION_INPUT);
    gpiod_line_settings_set_edge_detection(in, GPIOD_LINE_EDGE_BOTH);
    gpiod_line_settings_set_debounce_period_us(in, 5000);

    struct gpiod_line_config *lc = gpiod_line_config_new();
    gpiod_line_config_add_line_settings(lc, outs, 4, out);
    gpiod_line_config_add_line_settings(lc, ins, 3, in);
    struct gpiod_request_config *rc = gpiod_request_config_new();
    gpiod_request_config_set_consumer(rc, "aic3000-app");
    struct gpiod_line_request *req = gpiod_chip_request_lines(chip, rc, lc);

    gpiod_line_request_set_value(req, 16, GPIOD_LINE_VALUE_ACTIVE);   /* green status LED on */

    struct gpiod_edge_event_buffer *buf = gpiod_edge_event_buffer_new(16);
    while (gpiod_line_request_wait_edge_events(req, -1) > 0) {
        int n = gpiod_line_request_read_edge_events(req, buf, 16);
        for (int i = 0; i < n; i++) {
            struct gpiod_edge_event *ev = gpiod_edge_event_buffer_get_event(buf, i);
            unsigned int line = gpiod_edge_event_get_line_offset(ev);
            int falling = gpiod_edge_event_get_event_type(ev) == GPIOD_EDGE_EVENT_FALLING_EDGE;
            if ((line == 12 || line == 20) && falling)
                printf("%s pressed\n", line == 12 ? "TRIG" : "TUNE");
        }
    }
    /* cleanup: gpiod_line_request_release, *_free, gpiod_chip_close */
    return 0;
}
```

Build with `gcc app.c -lgpiod`. *This example has not been compiled yet: neither this PC nor the camera's Bookworm has libgpiod v2. Check it on Trixie.* Bookworm ships the libgpiod **v1.6** API
(`gpiod_chip_get_line`, `gpiod_line_request_output`, …), which differs; use
Python there, or build against v2.

Keep the lines requested for the whole lifetime of the application. A
released line goes back to an input, which leaves the laser and LEDs
undriven.

---

## 5. Focus: liquid-lens protocol

### 5.1 Transport [V]

| | |
|---|---|
| Bus | `/dev/i2c-1` (I2C1 on GPIO10/11, `i2c1-pi5,pins_10_11`) |
| Device | 7-bit address **0x18**. No kernel driver binds it; use raw `I2C_RDWR`. |
| Register addressing | 16-bit, **high byte first** |
| Register width | 32-bit value, **little-endian** |
| Device type | Unknown lens-driver controller (behaves like an MCU); it produces the lens's drive voltage [?] |

### 5.2 Registers

| Register | Access | Meaning | Status |
|---|---|---|---|
| `0x0000` | R/W | **Focus code**, 0–46000. Only the low 16 bits are used; write the upper 2 bytes as 0. | [V] |
| `0x0028` | W | EDATEC's `openVTemp()` writes `1` (probably temperature compensation). Never called by the vendor library. | [D] |

Values above 46000 are rejected by EDATEC's code. **Clamp to 0–46000 yourself**:
the vendor sends negative values unchecked, which become huge codes. A
plausible but unconfirmed reading is that the code is the drive voltage in mV
(0–46 V) [?].

### 5.3 Transactions

**Set focus:** one write message of 6 bytes.

```
S 0x18+W  0x00 0x00  c0 c1 0x00 0x00  P         c0 = code & 0xFF, c1 = code >> 8
example 32500:  00 00 f4 7e 00 00
```

**Read focus:** a 2-byte register write, then a repeated-start 4-byte read.

```
S 0x18+W  0x00 0x00  Sr 0x18+R  v0 v1 v2 v3  P   code = v0 | v1 << 8
```

### 5.4 Timing [V]

| | Measured |
|---|---|
| Write transaction | ~0.7 ms |
| Read transaction | ~0.8 ms |
| Write → register reads back the new code | **1.5–3 ms** (earlier reads return the old code) |
| Optical settle (liquid shape) | not measured; **0.12 s** settle plus 2 dropped frames works [U] |
| Holding | the lens keeps its code after the bus closes and across process restarts |

### 5.5 Optical behaviour (measured, user target, 2026-10-13) [U]

Sharpness (Tenengrad, centre half of a 1014×760 frame) against focus code:

```
code   20000 24000 28000 30000 32000 34000 36000 38000 40000 42000 44000 46000
sharp      9    12    17    26    40    64   182   839  2132   836   235   127
```

- The peak is sharp, about 230× the noise floor.
- It is roughly ±2000 codes wide at half height, so a 2000-code coarse step can't jump over it, and 200-code fine steps resolve it.
- Codes far from focus sit at the noise floor (about 5–30), so check for "no signal" with max/min < 1.5 before trusting a result.

### 5.6 Python [V] (this exact class was run on the unit)

```python
from smbus2 import SMBus, i2c_msg
import time

ADDR = 0x18

class Lens:
    def __init__(self, bus=1):
        self.bus, self.t_write = SMBus(bus), 0.0
    def write(self, code):
        code = max(0, min(46000, int(code)))
        self.bus.i2c_rdwr(i2c_msg.write(ADDR, [0, 0, code & 0xFF, code >> 8, 0, 0]))
        self.t_write = time.monotonic()
        return code
    def read(self):
        time.sleep(max(0.0, self.t_write + 0.005 - time.monotonic()))   # write -> read-back latency
        w, r = i2c_msg.write(ADDR, [0, 0]), i2c_msg.read(ADDR, 4)
        self.bus.i2c_rdwr(w, r)
        b = list(r)
        return b[0] | b[1] << 8
```

### 5.7 C (Linux i2c-dev) [V] (compiles with `-Wall -Wextra`; the same transfers as the verified test programs)

```c
#include <fcntl.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <stdint.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define LENS_ADDR 0x18

int lens_write(int fd, int code) {             /* fd = open("/dev/i2c-1", O_RDWR | O_CLOEXEC) */
    if (code < 0) code = 0;
    if (code > 46000) code = 46000;
    uint8_t b[6] = {0x00, 0x00, code & 0xFF, (code >> 8) & 0xFF, 0, 0};
    struct i2c_msg m = {.addr = LENS_ADDR, .flags = 0, .len = 6, .buf = b};
    struct i2c_rdwr_ioctl_data d = {.msgs = &m, .nmsgs = 1};
    return ioctl(fd, I2C_RDWR, &d) < 0 ? -1 : 0;
}

int lens_read(int fd) {                         /* wait >= 5 ms after a write */
    uint8_t reg[2] = {0x00, 0x00}, v[4] = {0};
    struct i2c_msg m[2] = {
        {.addr = LENS_ADDR, .flags = 0,        .len = 2, .buf = reg},
        {.addr = LENS_ADDR, .flags = I2C_M_RD, .len = 4, .buf = v},
    };
    struct i2c_rdwr_ioctl_data d = {.msgs = m, .nmsgs = 2};
    if (ioctl(fd, I2C_RDWR, &d) < 0) return -1;
    return v[0] | (v[1] << 8);
}
```

For production, wrap this in a class that probes the device on open (a read
must succeed), retries a failed transfer once, enforces the 5 ms write-to-read
wait, and serialises access with a mutex.

### 5.8 Autofocus recipe (what `test_autofocus.py` does) [U]

1. **Lock exposure and white balance** (`AeEnable=False`, `AwbEnable=False`, with the current `ExposureTime`, `AnalogueGain` and `ColourGains`), so brightness changes can't fake sharpness.
2. **Coarse sweep:** codes `lo..hi` in steps of **2000**. At each code: write it, wait **0.12 s**, drop **2 frames**, score the next frame.
3. **Check for a signal:** if max/min < **1.5**, stop and report "no detail in view" rather than picking noise.
4. **Fine sweep:** best coarse code ± 2000, in steps of **200**.
5. **Refine:** fit a parabola through the best fine point and its neighbours for the sub-step peak.
6. **Move and verify:** write the target, settle, re-score, and require ≥ **85 %** of the sweep's best.
7. **Restore** auto exposure. Keep the code (save it with the job), or restore the start code on failure.

**Sharpness metric (Tenengrad):** mean of `Sx² + Sy²`, where Sx and Sy are
Sobel gradients of the grey image over the centre ROI. Variance of the
Laplacian also works but is more noise-sensitive.

**Making it faster:**
- Search a smaller window around the last good code (focus barely moves for a fixed setup).
- Use a smaller ROI.
- Use a continuous sweep, writing the lens on a clock and matching frames to positions by sensor timestamp.
- At long exposures (the test scene ran at 66 ms), frame time dominates, so light the scene to shorten exposure.

---

## 6. Lights: light-MCU protocol

### 6.1 Transport [V]

| | |
|---|---|
| Port | `/dev/com2` → `/dev/ttyAMA3` (UART3, GPIO8 TX / GPIO9 RX) |
| Settings | **115200 baud, 8N1, raw** (no echo, no line discipline, no flow control) |
| Who talks first | the host. The MCU sends only the replies below. |

### 6.2 Frame format

```
<command char> '-' <argument> '\r' '\n'
```

The argument is either an **ASCII character** or a **raw binary byte** (or two),
depending on the command (see 6.3). Getting this wrong is the most likely bug.
For example, work mode 5 is the byte `0x05`, not the character `'5'` (`0x35`).

### 6.3 Command reference

| Purpose | Bytes on the wire (hex) | Argument | Vendor function | Status |
|---|---|---|---|---|
| **Query version** | `44 2d 0d 0a` (`"D-\r\n"`) | none | `svQueryVersion` | **[V]** reply `ff 15 01 0d 0a` |
| Enable zone *n* (1–4) | `3n 2d 31 0d 0a` (`"n-1\r\n"`) | ASCII `'1'` | `enableLightSection(n)` | [U] |
| Disable zone *n* | `3n 2d 30 0d 0a` (`"n-0\r\n"`) | ASCII `'0'` | `disableLightSection(n)` | [U] |
| Work mode *m* | `35 2d mm 0d 0a` | **raw byte** 0–5 | `setWorkMode(m)` | [U] |
| Manual light on | `39 2d 01 0d 0a` | **raw** `0x01` | `open_light()` / `setStrobeManual(1)` | [U] |
| Manual light off | `39 2d 00 0d 0a` | **raw** `0x00` | `close_light()` / `setStrobeManual(0)` | [U] |
| Brightness | `43 2d hh ll 0d 0a` | **raw 16-bit big-endian** | `setBrightnessValue(v)` | [U] |
| Flash count | `37 2d nn 0d 0a` | **raw byte** | `setLightFlashCount(n)` | [D] |
| Flash time (ms) | `38 2d tt 0d 0a` | **raw byte** | `setLightFlashTime(ms)` | [D] |
| Fire flash | `36 2d 31 0d 0a` (`"6-1\r\n"`) | ASCII `'1'` | `callLightFlash()` | [D] |
| RGB side LEDs | `41 2d 3d 0d 0a` (`"A-d\r\n"`) | ASCII digit (below) | `setRgbLight(c)` | [U] |

**Zones:** 1 = TopLeft, 2 = TopRight, 3 = BottomLeft, 4 = BottomRight [M].

**Work modes** (from the vendor header):

| m | Mode |
|---|---|
| 0 | continuous trigger |
| 1 | software trigger |
| 2 | external IO, rising edge |
| 3 | external IO, falling edge |
| 4 | external IO, level |
| 5 | custom: manual on/off with the `9-` command |

**Brightness encoding** depends on the light firmware version from `D-`:
- **firmware ≥ 1** (this unit): send `v` = 0–100 as is.
- **firmware 0:** send `int((100 − v) × 9.99)` (inverted, 0–999).

**RGB wire digits:**

| Digit | Colour |
|---|---|
| `0` | blue |
| `1` | red |
| `2` | green |
| `3` | yellow |
| `4` | off |
| `5` | white |

The vendor API numbers colours differently (0 off, 1 red, 2 green, 3 blue,
4 yellow, 5 white) and translates them; send the wire digits.

### 6.4 Replies from the MCU (binary) [D][V]

| Bytes | Meaning |
|---|---|
| `ff BB FF 0d 0a` | Answer to `D-`: BB = board version (0x15), FF = light firmware (0x01) [V] |
| `ff aa ee` | Hardware trigger event, which the vendor passes to `registerHardware` (global-shutter models) [D] |

The other commands are fire-and-forget; no acknowledgement has been seen.
Read with a short timeout and treat unknown bytes as informational.

### 6.5 Behaviour and safe operation [M][U]

- **Two separate controls:** a zone must be **enabled** (`n-1`) **and** the light
  must be **fired**, either manually (mode 5 + `9-\x01`) or by the camera/strobe
  in modes 0–4. Enabling alone turns nothing on.
- **Manual on time:** EDATEC's library switches the light off automatically after **3 s**. Do the same, and keep manual-on pulses short (the test uses 1 s).
- **Continuous strobing:** at 25 °C keep each pulse **≤ 25 ms** with **≥ 330 ms** off between pulses (**duty cycle ≤ 7 %**).
- **What vendor start-up sends:** brightness 90, then `D-`. A sensible shutdown state is manual off, all zones enabled, brightness 90, RGB off (what `test_lights.py` restores).
- **Exclusive port:** only one process may own `/dev/com2`. A second writer interleaves frames.

### 6.6 Python (pyserial) [V] (`version()` run on the unit: board 0x15, fw 1)

```python
import serial

class LightMcu:
    RGB = {"blue": 0, "red": 1, "green": 2, "yellow": 3, "off": 4, "white": 5}

    def __init__(self, port="/dev/com2"):
        self.s = serial.Serial(port, 115200, timeout=0.2)    # 8N1 raw by default
        self.fw = None

    def _send(self, cmd: bytes, arg: bytes) -> None:
        self.s.write(cmd + b"-" + arg + b"\r\n")

    def version(self):
        self.s.reset_input_buffer()
        self._send(b"D", b"")
        r = self.s.read(5)                                    # ff board fw 0d 0a
        if len(r) == 5 and r[0] == 0xFF and r[3:] == b"\r\n":
            self.fw = r[2]
            return r[1], r[2]
        return None

    def zone(self, n, on):     self._send(str(n).encode(), b"1" if on else b"0")
    def mode(self, m):         self._send(b"5", bytes([m]))
    def light(self, on):       self._send(b"9", b"\x01" if on else b"\x00")
    def rgb(self, colour):     self._send(b"A", str(self.RGB[colour]).encode())
    def flash(self):           self._send(b"6", b"1")
    def flash_count(self, n):  self._send(b"7", bytes([n & 0xFF]))
    def flash_time(self, ms):  self._send(b"8", bytes([ms & 0xFF]))

    def brightness(self, pct):
        pct = max(0, min(100, int(pct)))
        v = pct if (self.fw is None or self.fw >= 1) else int((100 - pct) * 9.99)
        self._send(b"C", bytes([v >> 8 & 0xFF, v & 0xFF]))
```

**Example: one 0.5 s manual flash of zones 1 and 2 at 60 %:**

```python
mcu = LightMcu(); mcu.version()
mcu.mode(5)
for n in (1, 2, 3, 4):
    mcu.zone(n, n in (1, 2))
mcu.brightness(60)
mcu.light(True); time.sleep(0.5); mcu.light(False)
```

### 6.7 C (termios) (compiles with `-Wall -Wextra`; not yet run on the unit)

```c
#include <fcntl.h>
#include <stdint.h>
#include <string.h>
#include <termios.h>
#include <unistd.h>

int mcu_open(const char *dev) {                  /* "/dev/com2" */
    int fd = open(dev, O_RDWR | O_NOCTTY | O_CLOEXEC);
    if (fd < 0) return -1;
    struct termios t;
    tcgetattr(fd, &t);
    cfmakeraw(&t);                               /* 8 bits, no parity, no echo */
    cfsetispeed(&t, B115200);
    cfsetospeed(&t, B115200);
    t.c_cflag |= CLOCAL | CREAD;
    t.c_cflag &= ~(CSTOPB | CRTSCTS);
    t.c_cc[VMIN] = 0;
    t.c_cc[VTIME] = 2;                           /* 200 ms read timeout */
    tcsetattr(fd, TCSANOW, &t);
    tcflush(fd, TCIOFLUSH);
    return fd;
}

int mcu_send(int fd, char cmd, const uint8_t *arg, size_t n) {
    uint8_t f[8] = {(uint8_t)cmd, '-'};
    if (n > 4) return -1;
    if (n) memcpy(f + 2, arg, n);
    f[2 + n] = '\r';
    f[3 + n] = '\n';
    return write(fd, f, 4 + n) == (ssize_t)(4 + n) ? 0 : -1;
}

/* examples */
static void light_examples(int fd) {
    mcu_send(fd, 'D', NULL, 0);                         /* version; then read 5 bytes */
    mcu_send(fd, '1', (const uint8_t *)"1", 1);         /* zone 1 enable   */
    uint8_t mode5 = 5;  mcu_send(fd, '5', &mode5, 1);    /* work mode 5     */
    uint8_t b[2] = {0, 60}; mcu_send(fd, 'C', b, 2);     /* brightness 60 % */
    uint8_t on = 1;     mcu_send(fd, '9', &on, 1);       /* manual on       */
    uint8_t off = 0;    mcu_send(fd, '9', &off, 1);      /* manual off      */
    mcu_send(fd, 'A', (const uint8_t *)"2", 1);         /* RGB green       */
}
```

---

## 7. Camera (IMX477 via libcamera) [V]

- **Sensor modes:**

  | Resolution | Max fps |
  |---|---|
  | 1332×990 | 120 |
  | 2028×1080 | 50 |
  | 2028×1520 | 40 |
  | 4056×3040 | 10 |

- **picamera2:** `Picamera2()`, then `create_preview_configuration(main={"size": (1014, 760), "format": "XBGR8888"})`, then `start()` and `capture_array()`.
- **Live view on the camera desktop:** use `Preview.QTGL` with `QT_QPA_PLATFORM=xcb`, and set `DISPLAY=:0` and `XDG_RUNTIME_DIR=/run/user/1000` when starting over SSH.
  - Native Wayland crashes the GL preview (EGL error).
  - The GL preview **rejects `RGB888`**. Use `XBGR8888`, and read the first 3 channels in numpy.
- **Full-resolution stills:** `switch_mode_and_capture_file(create_still_configuration(), path)`.
- **Exposure lock for measuring:** read `capture_metadata()`, then set `AeEnable=False`, `ExposureTime`, `AnalogueGain`, `AwbEnable=False`, `ColourGains`.
- **One process at a time:** only one process can own the camera, so close it before another tool (rpicam, your application) opens it.
- **C++:** use the libcamera API directly.

---

## 8. RS232 (`/dev/com1`) [?]

`/dev/ttyAMA2` (GPIO4/5) is exposed as `/dev/com1`. EDATEC's API calls it
`AMA1` (`writeAMA1`, `setAMA1Callback`), and their 2025-09 release added
"rs232". It most likely drives the RS232 lines on M12 pins 10–12 (GND/TX/RX).
Confirm with a TX-to-RX loopback before relying on it. Use it like any serial
port (termios, as in 6.7) at whatever settings your device needs.

---

## 9. Recommended application structure

**Start-up:**
1. **Check devices exist:** `/dev/i2c-1`, `/dev/com2`, `/dev/gpiochip0`, the camera. Fail clearly if one is missing (wrong `config.txt` or udev rule) or busy (vendor script running).
2. **GPIO:** request lines 13/16/7/21 as outputs at 0, and 22/27 as outputs at your chosen DO idle level; request 12/20/17 as inputs with both-edge events and 5–20 ms debounce.
3. **Light MCU:** open at 115200 raw, send `D-`, parse the firmware version (selects the brightness encoding), then set brightness, zones and work mode for your application.
4. **Lens:** open `/dev/i2c-1`, read the current code, write your job's saved focus code, then wait ≥ 0.12 s before imaging.
5. **Camera:** configure and start, then lock exposure if you measure sharpness.

**Running:**
- **One owner per resource.** Lens, MCU port and GPIO lines each belong to one thread or module; serialise access with a mutex.
- **Light duty limits** (6.5) are enforced in software: there is no hardware guard visible to the host.

**Shutdown (mirrors what the test scripts restore):** manual light off, zones
enabled, brightness 90, RGB off; laser and LEDs off; release the camera. The
lens can stay where it is, because it holds its code.

---

## 10. Verification status and open questions

| Item | Status |
|---|---|
| Lens protocol (read/write), latency, holding | **[V]** measured; identical bytes to the vendor `setLiquid` / `getLiquid` |
| Lens changes optical focus | **[U]** sweeps show a peak at code 40000–42000, 220–230× above the noise floor |
| Light MCU link and `D-` version reply | **[V]** `ff 15 01 0d 0a` |
| Light zone, brightness, RGB, manual on/off commands | **[U]** reported working with `test_lights.py` |
| Flash commands (`6`/`7`/`8`) and the mode they need; camera-synced modes 0–4 | record from your `test_lights.py` run (steps 5–6) |
| GPIO pin assignment | **[V]** EDATEC manual + disassembly + live pin states |
| Button levels (idle high, pressed low) | **[V][U]** |
| DI1 active level | **[?]** check with a sensor (likely active low) |
| DO1 / DO2 polarity (which level switches the load) | **[?]** measure DO_x against COMMON_OUT |
| RS232 on `/dev/com1` | **[?]** loopback test |
| Lens driver part number, register `0x0028` | **[?]** ask EDATEC support |

---

## 11. References

- `camera-tests/test_lights.py`, `camera-tests/test_autofocus.py`: complete, working, SDK-free implementations with a live view.
- `ED-AIC3000_PIN_MAPPING.md`: full pin table, M12 connectors, application notes.
- `research/`: lens probe, latency and optical sweep programs, with results.
- `findings/`: measured data (autofocus sweeps).
- EDATEC user manual ([M] above): https://edatec.cn/docs/assets/aic3000/ED-AIC3000-usermanual-en.pdf
- EDATEC docs: https://edatec.cn/docs/aic3000/
