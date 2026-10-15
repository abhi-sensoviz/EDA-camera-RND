# ED-AIC3000 master OS images

A master image is an exact clone of a fully set-up camera: Raspberry Pi OS
Trixie with every file, setting and account of the camera it was taken from.
Flash it onto a new camera to make that camera the same as the master, or onto
any camera to restore it. It is also the pre-seal master that golden images are
made from ([`ED-AIC3000_GOLDEN_IMAGE.md`](../ED-AIC3000_GOLDEN_IMAGE.md),
step 2).

**The image files are not in git:** each is about 3 GB (GitHub's limit is
100 MB per file), and they hold the application, password hashes and private
keys. Git tracks only their checksums and disk layout. Keep the images in a
private store (NAS, external drive) and copy the one you need into this folder.

## Images

| Image | Taken | Contents | Compressed | Verified |
|---|---|---|---|---|
| `aic3000-emmc-trixie-master-v1.0-live-20261015-1050.img.zst` | 2026-10-15, live over SSH (application stopped, filesystem frozen 4 min 43 s) | Raspberry Pi OS Trixie (Debian 13), kernel 6.18.50; `config.txt` overlays, udev rule, network setup (DHCP + fixed 192.168.1.10), VNC; the application built, installed and configured as a service; all user files, accounts and keys | 3.07 GB | 31,268,536,320 bytes (= disk); raw SHA-256 `8a907781…2adf` matches the decompressed image; bootfs `fsck.fat -n`: clean; rootfs `e2fsck -fn` 1.47.2: clean, 192,710 files |

Disk layout: partition table `dos` `0xbe56c0c8`, p1 vfat 512 MB `bootfs`,
p2 ext4 28.6 GB `rootfs`.

| File | In git | What it is |
|---|---|---|
| `<name>.img.zst` | no | The compressed image of the whole eMMC (zstd) |
| `<name>.raw.sha256` | yes | Checksum of the raw eMMC contents. `flash_emmc.sh` needs it next to the image to verify a flash. |
| `<name>.img.zst.sha256` | yes | Checksum of the compressed file: `sha256sum -c` it after copying the image here |
| `<name>.partitions.sfdisk`, `<name>.lsblk.txt` | yes | Partition table and disk layout at capture time |
| `<name>.log` | no | Capture log: when the camera was frozen and thawed |

## Flash a new camera

**You need:** this repository on a Linux PC with `rpiboot` built once
(`cd tools/usbboot && make`), the image and its `.raw.sha256` in this folder, a
USB-C data cable, and the camera's 24 V supply. The camera must be an ED-AIC3000
with the 32 GB eMMC; the script refuses other disk sizes.

1. **Check the image** after copying it here:
   ```bash
   cd ~/Desktop/EDA-smartCam/master-os-backup
   sha256sum -c aic3000-emmc-trixie-master-v1.0-live-20261015-1050.img.zst.sha256
   ```
2. **Power the camera off** (unplug the 24 V) and connect its **USB-C** port to
   the PC.
3. **Start the flash script** on the PC:
   ```bash
   cd ~/Desktop/EDA-smartCam
   sudo tools/flash_emmc.sh master-os-backup/aic3000-emmc-trixie-master-v1.0-live-20261015-1050.img.zst
   ```
4. **Put the camera in flashing mode** when the script asks: **hold TRIG**,
   plug the 24 V back in, keep holding about 3 s, release. Then press Enter.
5. **Confirm the disk.** The script waits for the camera's eMMC to appear as a
   USB disk, refuses anything that is not a ~31 GB USB disk, and lists it. Check
   it is the camera (USB, about 31 GB, never `sda`) and type `YES`.
6. **Wait.** Writing takes 10-20 minutes at USB 2 speed; then the script reads
   the eMMC back and compares it with the checksum, another 10-20 minutes. It
   ends with `verified: the eMMC matches the image` and `DONE`.
7. **Boot the camera:** unplug the USB-C cable and power-cycle the camera
   **without** holding TRIG.
8. **Check it** (allow about a minute for the first boot):

   | Check | How |
   |---|---|
   | Reachable | Connect it to the PC as in [`ED-AIC3000_NETWORK_SETUP.md`](../ED-AIC3000_NETWORK_SETUP.md); `ping 192.168.1.10` |
   | SSH | `ssh <user>@192.168.1.10` with the master's login |
   | Application | `https://192.168.1.10` in a browser; log in with the master's application login |
   | Hardware | Live camera image, focus moves (run autofocus once: each unit's lens differs), light test, status LED green, a trigger is counted |

## Several cameras from one master

A clone keeps the master's identity: hostname, SSH host keys, machine ID,
certificates and the fixed address 192.168.1.10. One camera at a time is fine,
for example a replacement unit. Cameras that run side by side on one network
each need their own fixed address and hostname. Set them on each camera,
connected on its own, then reboot it:

```bash
sudo nmcli connection modify "Wired connection 1" -ipv4.addresses 192.168.1.10/24 +ipv4.addresses 192.168.1.11/24
sudo sed -i 's/192\.168\.1\.10/192.168.1.11/' /etc/NetworkManager/dispatcher.d/50-aic-fixed-ip
sudo raspi-config nonint do_hostname <new-name>
```

The keys and machine ID still match the master's. For cameras you ship, use a
sealed golden image instead: it gives every unit its own identity on its first
boot.

## Making a new master version

1. Update and test the master camera.
2. Capture it:
   - **Offline:** `sudo tools/backup_emmc.sh aic3000-emmc-trixie-master-v1.1`
     (camera in TRIG/flash mode). It writes to `os-backup/`; move the files
     here.
   - **Live over SSH** (how v1.0 was taken): `fstrim` the camera, stop the
     application, freeze the root filesystem with `fsfreeze` (with a safety
     timer that always thaws it), stream `/dev/mmcblk0` with `dd` over SSH into
     `zstd` on the PC while checksumming the raw stream, then thaw and restart
     the application. See [`os-backup/README.md`](../os-backup/README.md).
3. Verify: the decompressed image matches the `.raw.sha256`, and both
   filesystems check clean (Trixie's ext4 needs `e2fsck` 1.47 or newer).
4. Add a row to the table above and keep the previous version.

## Troubleshooting

| Symptom | Fix |
|---|---|
| No new disk appears | The camera is not in flashing mode: power off, hold TRIG while powering on, keep holding about 3 s. |
| `no ….raw.sha256 to verify against` | Copy the image's `.raw.sha256` into this folder next to it. |
| `VERIFY FAILED` | USB error while writing: flash again; try another cable or port. |
| SSH warns "REMOTE HOST IDENTIFICATION HAS CHANGED" | The PC remembers a different camera at 192.168.1.10: `ssh-keygen -R 192.168.1.10`. |
