# What was learned

The detailed pin and connector map is in `../ED-AIC3000_PIN_MAPPING.md`, and the
protocols with code are in `../ED-AIC3000_DEVELOPER_GUIDE.md`.

## 1. The camera: EDATEC ED-AIC3000

| | |
|---|---|
| Compute | Raspberry Pi **CM5 Rev 1.0**, quad Cortex-A76 at 2.4 GHz. No NPU or AI accelerator. |
| Storage | **32 GB eMMC** (29.1 GiB): `mmcblk0p1` 512 MB vfat `/boot/firmware`, `mmcblk0p2` 28.6 GB ext4 `/`. No SD slot. |
| OS at handover | Raspberry Pi OS **Bookworm** (Debian 12) 64-bit, kernel `6.12.25+rpt-rpi-2712` |
| Bootloader | 2026-05-26, `BOOT_ORDER=0xf2461` (eMMC → NVMe → USB → network) |
| Sensor | **IMX477** (Raspberry Pi HQ sensor), 4056×3040, CSI `cam0`. Modes: 1332×990 @120, 2028×1080 @50, 2028×1520 @40, 4056×3040 @10 fps. |
| Lens | M12 12 mm fixed-focus lens behind a **liquid lens**; focus code 0–46000 over I2C |
| Lights | 4 zones (TL/TR/BL/BR) plus 3 RGB side LEDs, all driven by a light MCU on `/dev/com2` |
| I/O | 24 V supply, 1 DI, 2 DO, RS232 on a 12-pin M12; Gigabit Ethernet on an 8-pin M12; USB-C for flashing |
| Buttons / LEDs | TRIG, TUNE, power, fault, working status (green/red), network; laser aiming spot |
| Board IDs | EDATEC board `0x15`, light-MCU firmware `0x01` (from the `D-` query) |
| Network at handover | `eth0` static **192.168.1.10/24**, MAC on the device label / `ip link show eth0` (redacted here), no gateway. WayVNC on port 5900 (use `xtigervncviewer`). |
| Clock | About 106 days behind real time (no NTP without internet). Fix it before running `apt`. |
| Tools on the camera | g++, gdb, objdump, dtc, pinctrl, python3-picamera2, rpicam-apps, OpenCV 4.6 runtime libraries. No cmake, qmake or i2c-tools. |

## 2. The EDATEC SDK (`ed-aic3x00-lib` 1.20250915.1)

- **Repo:** `deb https://apt.edatec.cn/raspbian stable main` (key: `https://apt.edatec.cn/pubkey.gpg`). The single `stable` suite (codename buster) serves every OS. There is no Bookworm- or Trixie-specific build.
- **Files:**
  - `/usr/include/eda/eda-io.h`
  - `/usr/lib/libeda_io2.so` (C++)
  - `/usr/lib/python3/dist-packages/libedaio2.so` (Python)
  - `/usr/share/eda-aic-lib/examples/` (`test_io.cpp`, `test_io.py`, `CMakeLists.txt`)
- **Links to:** `libwiringPi.so` with no version, plus `libstdc++`, `libgcc_s`, `libc`. The package declares **no dependencies**. `wiringpi` 3.14 comes from the same repo.
- **What it provides:** I/O (laser, status/alarm LEDs, DO, DI/TRIG/TUNE callbacks, RGB side light, light zones, brightness, work modes, flash) and `setLiquid` / `getLiquid`. It has **no image processing and no autofocus algorithm**. Capture goes through picamera2.
- **API quirks:**
  - `setLiquid` / `getLiquid` only exist with `-DENABLE_LIQUID`.
  - `open_light` / `close_light` need `-DSUPPORT_LIGHT_CUSTOM`.
  - The flash calls need `-DENABLE_LIGHT_TIGGER` (sic).
  - The example `CMakeLists` sets all three via `-DENABLE_HQ=ON`.
  - Callbacks are plain `void(*)(int)` function pointers with no user-data argument, so a C++ class needs static trampolines.
- **What `EdaIo::setup()` does:**
  - Runs `wiringPiSetupGpio()`.
  - Makes outputs of 13, 16, 7, 21 (set low) and 22, 27 (set high).
  - Puts interrupts on both edges of 17, 12 and 20.
  - Opens `/dev/com2` at 115200, sets brightness 90 and queries the MCU version.

  This clashes with any other GPIO owner, including your own application.
- **Optional `/etc/ed-aic3000.ini`:** keys `dido_on`, `button_on`, `led_on`, `laser_on` (each defaults to 1). Absent on this unit.
- **`postinst`:**
  - Writes `/etc/udev/rules.d/98-com.rules` (`ttyAMA2` → `/dev/com1`, `ttyAMA3` → `/dev/com2`).
  - Appends stock overlays to `config.txt` (`imx477,cam0`, `uart2-pi5`, `uart3-pi5`, `i2c1-pi5,pins_10_11`, `i2c_arm`, camera/display auto-detect).
  - Copies `ed-imx477.dtbo`. That file is an older copy of the stock `imx477` overlay, and nothing uses it.
- **Trixie:** EDATEC's install page says Trixie is "temporarily not supported" and recommends the 2024-11-19 Bookworm image. Technically the board support is stock overlays plus one udev rule, so Trixie is feasible but untested by EDATEC.

## 3. Liquid-lens protocol (verified on hardware)

- **Bus and register:** `/dev/i2c-1` (I2C1 on GPIO10/11), address **0x18**, 16-bit register addresses sent high byte first.
- **Write:** `[00 00 b0 b1 b2 b3]` sets register 0x0000 to the code (little-endian, 0–46000).
- **Read:** write `[00 00]`, read 4 bytes, code = `b0 | b1 << 8`.
- **Timing:** a write takes about 0.7 ms on the bus and a read about 0.8 ms. The register reflects a write **1.5–3 ms** later; earlier reads return the old code. A driver should wait 5 ms after a write before reading back.
- **Holding:** the lens keeps its code after the bus device is closed, and across process restarts.
- **Optical proof (2026-10-13):** with a target in view, Tenengrad sharpness peaked at code 42000 (1287) and 40000 (2132), 220–230× above the noise floor (~5–30). The peak is about ±2000 codes wide, so a 2000-code coarse step and a 200-code fine step suit it. Developer reference: `../ED-AIC3000_DEVELOPER_GUIDE.md`.
- **The architecture mirrors the lights.** The CM5 never drives the lens itself. It
  writes a setpoint over I2C to a **lens driver device at 0x18**, which produces the
  lens's high drive voltage, just as the lights go through a light MCU on UART3.
- **The driver's part number is unknown.** It doesn't identify itself and EDATEC
  doesn't document it.
  - It is probably a microcontroller rather than a fixed-function chip: a write
    takes 1.5–3 ms to show up in a read-back, and it uses 16-bit register
    addresses with 32-bit values.
  - **Unconfirmed guess:** the 0–46000 code is the drive voltage in mV (0–46 V).
    Observed focus values of 32500–44000 would then be about 32–44 V, plausible
    for an electrowetting liquid lens.
  - Register `0x0028` ("VTemp" in the SDK) is probably temperature compensation.
  - Whether it is the same MCU as the light controller is unknown.
  - To identify it, ask EDATEC support for the part, or read its other registers
    (not yet done; it is an undocumented device).
- **Vendor bugs:** `setLiquid` does not reject negative codes (−1 goes out as 0xFFFF). `openVTemp()` writes 1 to register 0x0028 and is never called.

## 4. Light-MCU protocol (decoded from the library; version reply verified without the SDK, full set reported working)

The full table is in the pin-mapping file, section 7.
- **Line settings:** `/dev/com2` = `ttyAMA3` (GPIO8/9), 115200, opened `O_RDWR|O_NOCTTY|O_NONBLOCK`.
- **Command format:** `<cmd>-<arg>\r\n`. Command characters: `1`–`4` zones, `5` work mode (raw byte), `6` flash, `7` flash count, `8` flash time, `9` manual on/off (raw byte), `A` RGB, `C` brightness (16-bit), `D` version.
- **Brightness encoding** depends on the MCU firmware: version 0 gets `(100−v)×9.99`; version ≥1 (this unit) gets `v` as is.
- **Replies from the MCU:**
  - `FF <board> <fw> 0D 0A`: the version reply.
  - `FF AA EE`: a hardware trigger event.
- **Duty limit at 25 °C:** ≤ 25 ms on, ≥ 330 ms off.

## 5. Camera, live view and tooling

- **Live view on the camera's labwc desktop:** picamera2 `Preview.QTGL` works through Xwayland (`QT_QPA_PLATFORM=xcb`). Native Wayland aborts with an EGL error.
  - Over SSH, also set `DISPLAY=:0` and `XDG_RUNTIME_DIR=/run/user/1000`. The `camera-tests` scripts do this themselves.
- **Frame format:** the GL preview **rejects `RGB888`**; use `XBGR8888` and read the first 3 channels.
- **Overlays:** `Picamera2.set_overlay(rgba_ndarray)` draws an overlay; the test scripts use it for a status banner (PIL is preinstalled).
- **Screenshots of the desktop:** `XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 grim shot.png`.
- **Python on the camera:** version 3.11 does not allow backslashes inside f-string expressions.
- **Preinstalled Python packages:** pyserial, smbus2, gpiozero/lgpio, picamera2, numpy, Pillow.
- **Tools on the camera:** g++, gdb, objdump, dtc, pinctrl and grim are present; cmake, qmake and i2c-tools are not.
- **ARM binaries:** analyse them on the camera itself. A typical x86 PC's binutils can't disassemble aarch64.

## 6. Network and access

- **Camera:** `eth0` static 192.168.1.10/24 (factory) and no Wi-Fi. SSH uses the factory account from EDATEC's manual; change it. VNC is WayVNC on port 5900 (use `xtigervncviewer`; Remmina failed to negotiate).
- **Lab PC:** reaches the camera from its wired port with a 192.168.1.11/24 address. For internet, share the PC's connection with NetworkManager "shared" mode (`docs/ED-AIC3000_Ubuntu_Internet_Sharing_Setup_Guide.txt` in the backup folder).
- **Camera clock:** about 106 days behind with no internet (no NTP), so `apt` rejects package lists until it syncs.
- **Full eMMC backup and flashing:** build `rpiboot` from `github.com/raspberrypi/usbboot` (`tools/usbboot`, pinned as a submodule). Run `sudo ./rpiboot -d mass-storage-gadget64` while holding **TRIG** at power-on; `tools/backup_emmc.sh` automates the backup.
