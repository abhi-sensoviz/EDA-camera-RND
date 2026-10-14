# Open items

## To verify on the bench

1. **Trigger polarity.**
   - DI1 (GPIO17) and the TRIG/TUNE buttons read **high when idle**. EDATEC drives DI1 by applying 5 V against COMMON_IN, so active is most likely **low**.
   - Software that triggers on a rising edge would fire at the **end** of each sensor pulse.
   - Confirm with a sensor and trigger on the correct edge.
2. **DO polarity.**
   - Vendor `setup()` leaves GPIO22 (DO1) and GPIO27 (DO2) **high**.
   - Measure DO_1 against COMMON_OUT with the pin at 0 and at 1 to learn which level switches the load on, before wiring outputs.
3. **Light-MCU details.**
   - The version query is verified, and the command set was reported working with `camera-tests/test_lights.py`.
   - Still to record: which work mode the flash commands (`6`/`7`/`8`) need (test step 5), and what the lights do in camera-synced modes 0–4 (step 6).
   - **Measured 2026-10-14 (IMX477 unit, Trixie):** the area light lights **only in manual mode** (work mode 5 + `9-\x01`): image brightness 22.6 → 29.6 on a distant scene at 60 %. Modes 0 (continuous) and 1 (software) with flash count 1, flash time 10 or 100 ms and `6-1` (sent as ASCII `'1'` or raw `0x01`) gave **no light at all** across 15 frames. The camera-linked modes evidently need the strobe signal that global-shutter models provide. With this sensor, lighting synchronised to capture has to be done in software with manual on/off, inside EDATEC's 25 ms / 330 ms (7 % duty) rating.
   - **First open after boot can miss.** On the fresh Trixie install, the first `D-` after boot got no reply; every query after that did. Send a bare `\r\n` or retry the version query once when the port is first opened.
4. **RS232 on `/dev/com1`.** Confirm with a TX-to-RX loopback on M12 pins 11/12.
5. **Lens optical settle time.** 0.12 s plus 2 dropped frames works, but the real minimum is unmeasured. Measure it by stepping the code and capturing frames rapidly.
6. **libgpiod v2 C example** in the developer guide. Compile and run it on Trixie (Bookworm ships v1).

## Work not started

- **Golden image trial run:** seal a master, capture, flash a second unit and check its first boot (`ED-AIC3000_GOLDEN_IMAGE.md`). The scripts' safety checks and the write/verify pipeline are tested; the full cycle is not yet.
- **Light driver** for the MCU on `/dev/com2` (zones, brightness, work mode, flash, RGB), so no vendor library is needed.
- **Buttons:** TUNE → autofocus and TRIG → capture in the application (GPIO20 / GPIO12, idle high).
- **Pass/fail indication** through the laser, status LEDs and fault LED (GPIO 13 / 16 / 7 / 21).
- **Trixie migration:** see `OS_MIGRATION_PLAN.md`. Steps 0–4 are **done** (Trixie is flashed, networked and hardware-checked; see the plan's progress table). The step-0 image in `os-backup/` is local only; keep a private second copy.
- **Internet for the camera:** done. `AIC3000-Share` on this PC now shares on 192.168.1.1; the camera keeps a fixed 192.168.1.10 and gets internet by DHCP.
- **Lens driver identity:** ask EDATEC support for the part number, and the meaning of register `0x0028`.

## Risks and cautions

- **Vendor `setup()` vs your software.** Anything that calls EDATEC's `EdaIo::setup()` (`test_io`, the old `autoFocus.py`) takes over GPIO 7/12/13/16/17/20/21/22/27 and `/dev/com2`. Don't run it alongside your own code.
- **Pin maps from other cameras.** Pins commonly used elsewhere (7, 13, 16, 17, 27, 8–11) are LEDs, the laser, DI1, DO2, the light UART and the lens I2C here. Check every assignment against the pin map.
- **Trixie.** EDATEC does not support it officially. Keep the eMMC image until the camera passes every test.
- **Credentials.** The camera still uses the factory login. Change it.
