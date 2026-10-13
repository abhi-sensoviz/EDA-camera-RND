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
4. **RS232 on `/dev/com1`.** Confirm with a TX-to-RX loopback on M12 pins 11/12.
5. **Lens optical settle time.** 0.12 s plus 2 dropped frames works, but the real minimum is unmeasured. Measure it by stepping the code and capturing frames rapidly.
6. **libgpiod v2 C example** in the developer guide. Compile and run it on Trixie (Bookworm ships v1).

## Work not started

- **Light driver** for the MCU on `/dev/com2` (zones, brightness, work mode, flash, RGB), so no vendor library is needed.
- **Buttons:** TUNE → autofocus and TRIG → capture in the application (GPIO20 / GPIO12, idle high).
- **Pass/fail indication** through the laser, status LEDs and fault LED (GPIO 13 / 16 / 7 / 21).
- **Trixie migration:** see `OS_MIGRATION_PLAN.md`. Step 0, the full eMMC image, needs physical access (hold TRIG); run `tools/backup_emmc.sh`.
- **Internet for the camera:** the recommendation (run the PC's shared connection on 192.168.1.11, and give the camera gateway/DNS 192.168.1.11) has not been applied.
- **Lens driver identity:** ask EDATEC support for the part number, and the meaning of register `0x0028`.

## Risks and cautions

- **Vendor `setup()` vs your software.** Anything that calls EDATEC's `EdaIo::setup()` (`test_io`, the old `autoFocus.py`) takes over GPIO 7/12/13/16/17/20/21/22/27 and `/dev/com2`. Don't run it alongside your own code.
- **Pin maps from other cameras.** Pins commonly used elsewhere (7, 13, 16, 17, 27, 8–11) are LEDs, the laser, DI1, DO2, the light UART and the lens I2C here. Check every assignment against the pin map.
- **Trixie.** EDATEC does not support it officially. Keep the eMMC image until the camera passes every test.
- **Credentials.** The camera still uses the factory login. Change it.
