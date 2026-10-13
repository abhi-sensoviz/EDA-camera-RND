# EDA-camera-RND

Research and development notes, tools and verified findings for the **EDATEC
ED-AIC3000** industrial smart camera (Raspberry Pi CM5, IMX477 sensor, liquid
lens, MCU-driven lighting). The aims:
- drive the camera **without EDATEC's SDK**;
- be able to **rebuild its OS from scratch**;
- keep every finding in one place.

## Start here

| If you want to… | Read |
|---|---|
| Write software for the camera without the SDK | [`ED-AIC3000_DEVELOPER_GUIDE.md`](ED-AIC3000_DEVELOPER_GUIDE.md): pin map, GPIO, lens and light protocols, Python and C |
| Know what every pin and connector does | [`ED-AIC3000_PIN_MAPPING.md`](ED-AIC3000_PIN_MAPPING.md) |
| Test the lights and the focus on the camera | [`camera-tests/`](camera-tests/): SDK-free scripts with a live view |
| Rebuild or migrate the OS (Bookworm → Trixie) | [`ai/OS_MIGRATION_PLAN.md`](ai/OS_MIGRATION_PLAN.md), [`aic3000-backup/README.md`](aic3000-backup/README.md), [`tools/`](tools/) |
| See what was measured | [`findings/`](findings/) |
| See how the protocols were found and verified | [`research/`](research/) |
| Pick up the work where it was left | [`ai/`](ai/): session log, knowledge base, open items |

## The camera in brief

| Function | How it's driven | Status |
|---|---|---|
| **Focus** (liquid lens) | I2C `/dev/i2c-1`, device `0x18`, register `0x0000` = code 0–46000 (little-endian) | verified, including optically (sharp peak at 40000–42000) |
| **Lights** (4 zones, brightness, flash, RGB) | MCU on `/dev/com2` (UART3, 115200), text commands `X-arg\r\n` | version reply verified; command set reported working |
| **Laser, status LEDs, fault LED** | GPIO 13 / 16 (OK) / 7 (NG) / 21 | verified |
| **DO1 / DO2** | GPIO 22 / 27 | pins verified; polarity to confirm |
| **DI1, TRIG, TUNE** | GPIO 17 / 12 / 20 (idle high) | verified; DI1 active level to confirm |
| **Camera** | IMX477 on CSI `cam0`, libcamera / picamera2 | verified |
| **OS support** | `config.txt`: `i2c_arm`, `imx477,cam0`, `uart2-pi5`, `uart3-pi5`, `i2c1-pi5,pins_10_11`; udev rule `98-com.rules` | verified |

## Repository layout

```
ED-AIC3000_DEVELOPER_GUIDE.md   build software from scratch (protocols + code)
ED-AIC3000_PIN_MAPPING.md       pins, buses, connectors, application notes
camera-tests/                   test_lights.py, test_autofocus.py (live view; no SDK)
research/                       lens probe / latency / optical tests, preview probe, method
findings/                       measured results (autofocus sweep CSVs, timings)
ai/                             session log, knowledge base, OS migration plan, open items
aic3000-backup/                 OS config, hardware dumps, inventory, vendor file checksums
tools/backup_emmc.sh            full eMMC image via rpiboot (camera in TRIG/flash mode)
tools/usbboot/                  submodule: github.com/raspberrypi/usbboot (rpiboot)
os-backup/                      eMMC images (local only, not in git)
autoFocus.py                    first SDK-based experiment (kept for reference)
```

Clone with the submodule:

```bash
git clone --recurse-submodules git@github.com:abhi-sensoviz/EDA-camera-RND.git
cd EDA-camera-RND/tools/usbboot && make       # builds rpiboot
```

## What is not in this repository, and how to get it

| Item | Where |
|---|---|
| EDATEC packages `ed-aic3x00-lib` 1.20250915.1, `wiringpi` 3.14 | `https://apt.edatec.cn/raspbian` (exact URLs and SHA-256 in `aic3000-backup/README.md`) |
| EDATEC user manual and datasheet | https://edatec.cn/docs/aic3000/ |
| The disassembly of EDATEC's library | kept privately (EDATEC's code); the findings are fully documented here |
| eMMC images | local `os-backup/`; created with `tools/backup_emmc.sh` |
| Internal application integration | private repository |
| The camera's serial number and MAC address | redacted from the dumps and docs |

## Safety notes

- **Area LEDs:** keep pulses ≤ 25 ms with ≥ 330 ms off at 25 °C (duty cycle ≤ 7 %), and manual on-times short (EDATEC's library cuts off at 3 s).
- **DO outputs:** 0.25 A maximum per channel, 0.5 A total. Never connect COMMON_OUT to +24 V.
- **EDATEC's `setup()`:** don't run anything that calls it alongside your own software. It takes over the GPIOs and the light port.
- **Credentials:** change the camera's factory login.
