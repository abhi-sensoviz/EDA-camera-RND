# Plan: move the ED-AIC3000 from Bookworm to Trixie

## Why, and the decision

- **Our application needs Trixie.** It requires Qt ≥ 6.8; Trixie ships Qt 6.8,
  while Bookworm ships 6.4.
- **The camera can run it.** The CM5 is supported by Raspberry Pi OS Trixie, and
  the camera-specific setup is stock overlays plus one udev rule, all backed up in
  `../aic3000-backup/`.
- **EDATEC does not support it yet.** Their install page says Trixie is
  "temporarily not supported". Their package has no dependencies and will most
  likely install, but nobody has tested it on Trixie.
- **Flash fresh; don't clone.** Cloning an SD card from another device carries
  over its `config.txt`, SSH keys, machine ID and network settings. A typical
  "32 GB" card is also larger than the 29.1 GiB eMMC, so the image may not fit.
  Raspberry Pi also recommends a clean image over a major in-place upgrade.
  The step-0 image keeps everything reversible.

## Progress (2026-10-14)

| Step | Status |
|---|---|
| 0. eMMC image | **Done.** Verified image in `os-backup/` (local only). |
| 1. Flash Trixie | **Done.** `2026-10-06` image written with Imager over `rpiboot`. |
| 2. `config.txt` | **Done.** Overlays appended, plus an empty `ssh` file on the boot partition. |
| 3. Network and clock | **Done.** Fixed 192.168.1.10 plus DHCP from `AIC3000-Share` (192.168.1.1); NTP synced, internet works. |
| 4. Hardware check | **Done.** IMX477 listed; `/dev/com1`, `/dev/com2`, `/dev/i2c-1` present once the udev rule is in; lens write/read-back OK; light MCU replies `ff 15 01 0d 0a`. |
| `apt full-upgrade` | **Done.** 54 upgraded, 12 new, RC=0. VNC enabled (`wayvnc`, port 5900). After a reboot, every step-4 check passed again. |
| 5. Install your application | Not started. |
| 7. Finish | Not started. The login set in Imager is still weak: change it. Also rename the camera: the hostname set in Imager is already used by another device on the office network, so `<name>.local` can reach the wrong machine (wrong-password and changed-host-key errors). |

## 0. Full eMMC image of the current camera (needs physical access)

This is the only way back to the exact factory state. It is automated by `../tools/backup_emmc.sh` (run it with `sudo`), which writes to `../os-backup/`. The script checks it has the camera's disk, never writes to the eMMC, and verifies the image by checksum. The manual equivalent is below.

```bash
# On the PC (Ubuntu 20.04: git, make and libusb-1.0-0-dev are already present)
git clone --recurse-submodules --shallow-submodules --depth=1 https://github.com/raspberrypi/usbboot
cd usbboot && make
# Camera: power off, connect USB-C to the PC, HOLD TRIG, power on
sudo ./rpiboot -d mass-storage-gadget64
lsblk -d -o NAME,SIZE,TRAN,MODEL        # the ~29.1G USB disk. NEVER /dev/sda (the PC's own disk)
sudo dd if=/dev/sdX bs=4M status=progress | gzip -1 > /path/to/aic3000-bookworm-factory.img.gz
```

Only 22 GB is free on the PC, so an external drive is safer. To restore later,
enter `rpiboot` mode the same way and run:

```bash
gunzip -c aic3000-bookworm-factory.img.gz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
```

## 1. Flash Trixie

**Image checked on 2026-10-14:** `2026-10-06-raspios-trixie-arm64.img.xz`
(https://downloads.raspberrypi.com/raspios_arm64/images/raspios_arm64-2026-10-06/).
- **Kernel:** 6.18.50.
- **First-boot setup:** cloud-init 25.2 + `rpi-cloud-init-mods`, so set the user and SSH with Raspberry Pi Imager (snap 1.9.6: `sudo snap install rpi-imager`). `userconf-pi` 0.19 is still present.
- **Already installed** (nothing extra needed for `camera-tests/`): Qt 6.8.2, `python3-picamera2` 0.3.37, `python3-smbus2`, `python3-serial`, `python3-gpiozero`, libgpiod 2.2.1 (v2 API), rpicam-apps 1.13, wayvnc 0.10.2.


1. Install Raspberry Pi Imager: `sudo snap install rpi-imager`.
2. Put the camera in `rpiboot` mode as in step 0.
3. In Imager, choose **Raspberry Pi OS (64-bit), Trixie, Desktop** and select the eMMC's USB disk.
4. In Imager's customisation screen, set:
   - hostname,
   - an admin user with a strong password,
   - SSH enabled,
   - time zone.

## 2. Camera settings, before the first boot

With the eMMC still showing as a USB disk, mount its FAT boot partition and
append the following to `config.txt`. This is exactly what EDATEC's `postinst`
adds; the stock overlays exist on Trixie.

```ini
[all]
dtparam=i2c_arm=on
dtoverlay=imx477,cam0
dtoverlay=uart2-pi5
dtoverlay=uart3-pi5
dtoverlay=i2c1-pi5,pins_10_11
```

## 3. Network and clock

- **Addressing:** the fresh OS uses DHCP on `eth0`, not 192.168.1.10.
- **Internet through this PC:** activate `AIC3000-Share` (NetworkManager shared mode). Since 2026-10-14 it runs on **192.168.1.1/24** (`nmcli connection modify AIC3000-Share ipv4.addresses 192.168.1.1/24`), so the camera's DHCP address and its fixed 192.168.1.10 share one subnet and both are reachable from the PC. On any other Linux PC: `nmcli connection add type ethernet ifname <port> con-name AIC3000-Share ipv4.method shared ipv4.addresses 192.168.1.1/24`.
- **NetworkManager 1.22 (Ubuntu 20.04)** silently drops a second address on a shared profile, so the share can't carry both 10.42.0.1 and 192.168.1.x; that is why the share was moved to 192.168.1.1.
- **Keep the share active across camera reboots:** `nmcli connection modify AIC3000-Share connection.autoconnect yes connection.autoconnect-priority 100`. Without it, NetworkManager falls back to the old 192.168.1.11 profile when the camera's link drops, and the camera loses its address.
- **Finding the camera:** `ip neigh show dev enp7s0f1`; look for the camera's MAC (on its label, or from `ip link show eth0` on the old system). Or `sudo arp-scan --interface=enp7s0f1 --localnet`.
- **Clock:** check `timedatectl` before running `apt`. A clock that is months behind makes `apt` reject the package lists as "not valid yet".
- **Fixed address (applied 2026-10-14):** keep DHCP and add 192.168.1.10/24 as a second address, so the camera is reachable from any PC set to 192.168.1.x, with or without a DHCP server:
  ```bash
  sudo nmcli connection modify "Wired connection 1" +ipv4.addresses 192.168.1.10/24 ipv4.dhcp-timeout infinity
  sudo nmcli connection up "Wired connection 1"
  ```
  `dhcp-timeout infinity` keeps DHCP retrying instead of failing after 45 s, so the fixed address stays up. Tested: with the PC on plain 192.168.1.11 (no DHCP) the camera kept 192.168.1.10 for 90 s while retrying; switching the PC back to `AIC3000-Share` gave it a 10.42.0.x lease and internet again.
  A NetworkManager hook ([`camera-setup/50-aic-fixed-ip`](../camera-setup/50-aic-fixed-ip)) marks 192.168.1.10 deprecated whenever a DHCP address exists, so `.local` names resolve to the DHCP address. Full guide: [`../ED-AIC3000_NETWORK_SETUP.md`](../ED-AIC3000_NETWORK_SETUP.md).

## 4. Check the hardware before installing your application

```bash
sudo cp 98-com.rules /etc/udev/rules.d/          # from aic3000-backup/system-config/etc/udev/rules.d/
sudo reboot
rpicam-hello --list-cameras                      # expect: imx477 4056x3040
ls -l /dev/com1 /dev/com2 /dev/i2c-1             # all three present
pinctrl get 12,17,20                             # TRIG, DI1, TUNE inputs
```

## 5. Install your application

1. Install your application and its dependencies.
2. Give its service user the device groups: `sudo usermod -aG video,render,gpio,dialout,i2c <user>`.
3. Use the ED-AIC3000 interfaces from `../ED-AIC3000_PIN_MAPPING.md` section 8:

   | Need | Use |
   |---|---|
   | Trigger | 17 (DI1) or 12 (TRIG) |
   | OK / reject outputs | 22 / 27 |
   | Lights | the MCU on `/dev/com2` (no light GPIOs) |
   | Focus | the I2C lens (no motor pins) |

4. Bench-check the trigger polarity first (open item 1). The inputs read high when idle.
5. Run `../camera-tests/test_autofocus.py read` and `test_lights.py --only version`, then autofocus on a textured part.

## 6. Optional: EDATEC library, for lights until your application has a light driver

```bash
sudo apt install ./ed-aic3x00-lib_1.20250915.1_arm64.deb   # download: see aic3000-backup/README.md
```

- **Skip EDATEC's `wiringpi` package** if WiringPi is already installed (any build providing `libwiringPi.so` works).
- **Never run vendor `setup()` code while your application is running.** Both take over the same GPIOs and `/dev/com2`.

## 7. Finish

- Change the default credentials.
- Prefer SSH keys and disable password login.
- Keep the step-0 image until the camera has passed camera, focus, I/O, Web UI and inspection tests.

## If cloning is still preferred

This only makes sense if the card is a working Trixie install of your application from a Pi 5 or CM5.

1. `sudo dd if=/dev/<sdcard> of=sd-card.img bs=4M status=progress`
2. Shrink it with PiShrink so it fits 29.1 GiB.
3. Write it to the eMMC in `rpiboot` mode.
4. Before booting, add the step-2 `config.txt` lines, the `98-com.rules` udev rule, and the step-3 network setup.
5. After booting:
   - regenerate SSH host keys: `sudo rm /etc/ssh/ssh_host_*`, then `sudo dpkg-reconfigure openssh-server`;
   - regenerate the machine ID: `sudo rm /etc/machine-id`, then `sudo systemd-machine-id-setup`;
   - change the hostname.
