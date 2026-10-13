# Session log (2026-10-13)

A record of each request and its outcome, in order. Work on our internal
application is summarised here; its details are kept privately.

## 1. TRIG / TUNE buttons, autofocus, internet for the camera

**Asked:** how the TRIG and TUNE buttons and autofocus work, and how to get internet to the camera, which has no Wi-Fi.

**Found:**
- The datasheet says only that the buttons need an SDK callback.
- EDATEC's online user manual adds:
  - TUNE = GPIO20, intended for one-press autofocus; TRIG = GPIO12.
  - Holding TRIG at power-on enters eMMC flashing mode.
  - Focus is `eda.setLiquid(0..46000)`. There is **no autofocus routine**: you sweep and score sharpness yourself.
- **Internet:** `aic3000-backup/docs/ED-AIC3000_Ubuntu_Internet_Sharing_Setup_Guide.txt` describes NetworkManager "shared" mode on the PC.
- **Simpler alternative, recommended but not applied:** run the shared profile on 192.168.1.11/24, and give the camera's static profile gateway and DNS 192.168.1.11. The camera then keeps its address.

## 2. Image processing

**Asked:** whether the SDK includes image-processing algorithms.

**Answer:** no. The SDK is `ed-aic3x00-lib` (I/O, lights, lens) plus picamera2 (capture, exposure, gain).
- Bring your own OpenCV, barcode or AI library.
- The CM5 has no NPU.
- An OpenCV example was given: capture → threshold/contours → status LED / DO.

## 3. `autoFocus.py`

`aic3000-backup/user-files/Desktop/autoFocus.py` is an SDK-based script:
- **Preview:** a QTGL preview window.
- **TUNE:** coarse then fine `setLiquid` sweep with exposure locked.
- **TRIG:** full-resolution photo.

The user's first run of the earlier version reported `focus = 44000`.

## 4. Reverse-engineering EDATEC's library over SSH

- **Logged in** with the factory account from the EDATEC manual.
- **Disassembled** `libeda_io2.so` (`objdump`, `nm`, `strings`, on the camera). Findings:
  - `setLiquid` is one I2C transaction to 0x18 on `/dev/i2c-1`.
  - The buttons and DI1 are wiringPi interrupts on both edges.
  - `setup()` takes over GPIO 7/12/13/16/17/20/21/22/27 and the light MCU serial port.
- **Verified the lens protocol on hardware** (`research/lens_probe.cpp`): raw and vendor reads and writes agree in both directions.
- **Measured the write → read-back latency** (`research/lens_latency.c`): 1.5–3 ms.
- **Integration:** a liquid-lens focus mode was added to our internal vision application (private), and tested on the unit.

## 5–6. Application integration (private)

Further integration work and repository maintenance on the internal
application, kept in its private repository.

## 7. Trixie, cloning, and the firmware backup

**Asked:** does the camera support Trixie, should the OS be cloned or freshly flashed, plus back up EDATEC's files and give a plan.

**Camera:** CM5 Rev 1.0, 32 GB eMMC (29.1 GiB), Bookworm, kernel 6.12.25, bootloader 2026-05-26, `BOOT_ORDER=0xf2461`.

**EDATEC:**
- Trixie is "temporarily not supported".
- Their apt repo has one `stable` suite (codename buster) for every OS.
- `ed-aic3x00-lib` declares no dependencies.
- Its `postinst` only writes `98-com.rules`, appends stock overlays to `config.txt`, and copies an unused `ed-imx477.dtbo` (an old copy of the stock overlay).

**Backed up** into `aic3000-backup/`:
- system config and hardware dumps;
- inventory;
- checksums of every vendor file.

EDATEC's own files, plus the disassembly, are kept privately; see the backup
README for where to download them.

**Recommended:** a full eMMC image via `rpiboot`, then a fresh Trixie install rather than cloning. The plan is in `OS_MIGRATION_PLAN.md`; the imaging is automated in `tools/backup_emmc.sh`.

## 8. Pin mapping, this folder, the migration plan

- **Pin mapping:** `ED-AIC3000_PIN_MAPPING.md`. The manual confirmed DI1 17, DO1 22, DO2 27, fault 21, status 16 normal / 7 abnormal, TRIG 12 and TUNE 20, and supplied the M12 wire colours.
- **Trigger polarity:** the inputs read high when idle, so software that triggers on a rising edge may fire at the end of a pulse. To be checked.

## 9. "Is it really a liquid lens?" and the optical tests

- **First test** (`research/lens_optical_test.py`): the camera faced a blank ceiling, so the curve was flat and the result inconclusive.
- **Direct-control test scripts:** `camera-tests/test_lights.py` and `camera-tests/test_autofocus.py`, with no SDK, using pyserial, smbus2, gpiozero and picamera2.
- **Light MCU without the SDK:** answered `D-\r\n` with `ff 15 01 0d 0a`.
- **Live view added to both scripts:**
  - QTGL works through Xwayland (`QT_QPA_PLATFORM=xcb`); native Wayland crashes.
  - The GL preview rejects `RGB888`. This crashed the first live-view version; it was fixed with `XBGR8888`.
  - Over SSH, the scripts set `DISPLAY` and `XDG_RUNTIME_DIR` themselves.
  - Checked with `grim` screenshots on the unit.
- **User sweeps with a detailed target:** focus peaks at codes **42000** (221×) and **40000** (229×). The liquid lens is proven to work (`findings/`).
- **User report:** the light and focus test scripts work.

## 10. Developer guide

`ED-AIC3000_DEVELOPER_GUIDE.md`: everything needed to write software from
scratch without the SDK, with Python and C examples.
- **Python:** the `Lens` and `LightMcu` classes were run on the unit.
- **C:** the lens and serial examples compile with `-Wall -Wextra`. The libgpiod v2 example is untested (Bookworm ships v1).

## 11. This repository

Everything except the eMMC images and the sensitive items went into the public
repository `EDA-camera-RND`. The items kept local only:
- EDATEC binaries, `.deb` files, manuals and disassembly;
- the camera's serial number and MAC address;
- internal application details.

The excluded files stay locally as `*.private.*` copies and in ignored paths
(see `.gitignore`).
