# ai/: context for picking this work up again

This folder records what was worked out about the EDATEC **ED-AIC3000** smart
camera, so a person or an AI assistant can continue without redoing the
investigation. It was written on 2026-10-13, at the end of a long working session.

| File | What it holds |
|---|---|
| `SESSION_LOG.md` | What was asked, what was done and what came out, in order |
| `KNOWLEDGE.md` | Facts learned: hardware, vendor SDK internals, protocols, camera and live view, network, tooling |
| `OS_MIGRATION_PLAN.md` | Step-by-step plan to move the camera from Bookworm to Trixie |
| `OPEN_ITEMS.md` | Unfinished work, things to verify on the bench, risks |

Related material elsewhere in the repository:

| Path | What it is |
|---|---|
| `../ED-AIC3000_DEVELOPER_GUIDE.md` | **Build software without the SDK**: pin map, GPIO, lens and light protocols with Python and C |
| `../ED-AIC3000_PIN_MAPPING.md` | **Every pin and connector**: focus, lights, I/O, buttons, LEDs, buses, M12 wiring |
| `../camera-tests/` | Working SDK-free test scripts with a live view (lights; focus / autofocus) |
| `../research/` | The programs that verified the protocols, and how they were found |
| `../findings/` | Measured results (autofocus sweeps, timings) |
| `../aic3000-backup/` | OS config, hardware dumps and inventory from the unit (EDATEC's own files are excluded; see its README) |
| `../tools/` | `backup_emmc.sh` (full eMMC image via rpiboot) and the `usbboot` submodule |

## Ten-line summary

1. The ED-AIC3000 is a Raspberry Pi **CM5** camera: 32 GB eMMC, IMX477 sensor, M12 lens behind a **liquid lens**, 4 light zones plus RGB side lights, and 24 V I/O on an M12 connector.
2. **Focus** is a lens-driver device on I2C `/dev/i2c-1` at **0x18**: write code 0–46000 to register 0x0000. **Verified**, including optically (sharp peak at 40000–42000 for the test target).
3. **Lights** are not on GPIO. A microcontroller on `/dev/com2` (UART3, 115200) takes text commands such as `1-1\r\n`. The version reply was verified without the SDK, and the command set was reported working.
4. **GPIO** (`gpiochip0` = `pinctrl-rp1`, line = BCM): laser 13; status LED 16 (OK) / 7 (NG); fault LED 21; DO1 22; DO2 27; DI1 17; TRIG 12; TUNE 20.
5. The EDATEC SDK (`ed-aic3x00-lib`) provides **no image processing and no autofocus algorithm**, only I/O and `setLiquid()`. Everything it does can be done directly (developer guide).
6. Our internal vision application gained a liquid-lens focus mode based on these findings. Its details are kept in a private repository.
7. That application needs **Trixie** (Qt ≥ 6.8). The camera runs Bookworm. EDATEC says Trixie is "temporarily not supported", but its board support is five stock-overlay lines in `config.txt` plus one udev rule.
8. The camera's **factory network setting** is static 192.168.1.10. It has no Wi-Fi; internet comes through a PC sharing its connection.
9. The live view works through Xwayland (`QT_QPA_PLATFORM=xcb`). The GL preview rejects `RGB888`; use `XBGR8888`.
10. **Next steps:** check trigger and DO polarity on the bench, write a light driver for the MCU, then the Trixie migration. See `OPEN_ITEMS.md`.
