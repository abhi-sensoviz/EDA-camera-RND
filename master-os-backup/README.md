# ED-AIC3000 master OS images

A master image is an exact clone of a fully set-up camera: Raspberry Pi OS
Trixie with every file, setting and account of the camera it was taken from.
Flash it onto a new camera to make that camera the same as the master, or onto
any camera to restore it. It is also the pre-seal master that golden images are
made from ([`ED-AIC3000_GOLDEN_IMAGE.md`](../ED-AIC3000_GOLDEN_IMAGE.md),
step 2).

**The image files are not in git:** each is about 3 GB (GitHub's limit is
100 MB per file), and they hold the application, password hashes and private
keys. Git tracks only their checksums and disk layout. The images are kept on
Google Drive (links below): download the one you need into this folder.

**Keep the Drive sharing restricted** to the people who need it. This repository
is public, so a link set to "Anyone with the link" would let anyone download the
image, keys included.

**All master images: [Google Drive folder](https://drive.google.com/drive/folders/1Nxu7gg8mGiuk3vCn4DAfbHc3ZIkwvXth?usp=sharing)** (sign-in required).

| Image | Download |
|---|---|
| `aic3000-emmc-trixie-master-v1.1-live-20261015-1315.img.zst` | In the [Drive folder](https://drive.google.com/drive/folders/1Nxu7gg8mGiuk3vCn4DAfbHc3ZIkwvXth?usp=sharing) |
| `aic3000-emmc-trixie-master-v1.0-live-20261015-1050.img.zst` | [Google Drive](https://drive.google.com/file/d/1H1_jW-n0x5iYW4B7IO8i6j-WDxykZzs7/view?usp=sharing), also in the folder |

## Images

| Image | Taken | Contents | Compressed | Verified |
|---|---|---|---|---|
| `aic3000-emmc-trixie-master-v1.1-live-20261015-1315.img.zst` | 2026-10-15 13:15, with `backup_master.sh` (application stopped, filesystem frozen 4 min 45 s) | As v1.0, with the application updated the same day | 3.07 GB | 31,268,536,320 bytes (= disk); raw SHA-256 `3340e063…e397` matches the decompressed image |
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
| `backup_master.sh` | yes | Makes a new master image of a running camera over SSH (see below) |

## Flash a new camera

### What you need

**Files**, in this folder, all with the same base name:

| File | Needed | Where from |
|---|---|---|
| `<name>.img.zst` | Yes: the image | The [Drive folder](https://drive.google.com/drive/folders/1Nxu7gg8mGiuk3vCn4DAfbHc3ZIkwvXth?usp=sharing). Take the newest (v1.1) unless you need an older one. |
| `<name>.raw.sha256` | Yes: after writing, `flash_emmc.sh` reads the camera's eMMC back and compares it with this. Without it the script stops (`no ….raw.sha256 to verify against`) unless you add `--no-verify`. | Already here, from git |
| `<name>.img.zst.sha256` | Only to check the download (step 1) | Already here, from git |

**On the PC, once** (Ubuntu or Debian):

```bash
sudo apt install git zstd build-essential pkg-config libusb-1.0-0-dev
git clone --recurse-submodules https://github.com/abhi-sensoviz/EDA-camera-RND.git ~/Desktop/EDA-smartCam
cd ~/Desktop/EDA-smartCam/tools/usbboot && make      # builds rpiboot
```

`flash_emmc.sh` uses `tools/usbboot/rpiboot` and
`tools/usbboot/mass-storage-gadget64/` from the submodule (so clone with
`--recurse-submodules`, or run `git submodule update --init` afterwards), and
`zstd` to decompress the image while writing. It runs with `sudo` because it
writes to the camera's disk. It can be started from any folder: it finds
`rpiboot` next to itself.

**Hardware:** a USB-C data cable and the camera's 24 V supply. The camera must
be an ED-AIC3000 with the 32 GB eMMC; the script refuses other disk sizes.

### Steps

1. **Check the download:**
   ```bash
   cd ~/Desktop/EDA-smartCam/master-os-backup
   sha256sum -c aic3000-emmc-trixie-master-v1.1-live-20261015-1315.img.zst.sha256
   ```
2. **Power the camera off** (unplug the 24 V) and connect its **USB-C** port to
   the PC.
3. **Start the flash script** on the PC:
   ```bash
   cd ~/Desktop/EDA-smartCam
   sudo tools/flash_emmc.sh master-os-backup/aic3000-emmc-trixie-master-v1.1-live-20261015-1315.img.zst
   ```
   or, from this folder:
   `sudo ../tools/flash_emmc.sh aic3000-emmc-trixie-master-v1.1-live-20261015-1315.img.zst`
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
2. **Back it up with [`backup_master.sh`](backup_master.sh)**, from this folder.
   The image and its checksums land next to the script:

   ```bash
   cd ~/Desktop/EDA-smartCam/master-os-backup
   ./backup_master.sh --stop <app-service> <user>@192.168.1.10 aic3000-emmc-trixie-master-v1.1
   ```

   It needs no physical access, no TRIG/flash mode and no sudo on the PC (it
   asks for the camera's sudo password once). It:
   1. TRIMs the camera's free space, so the image compresses to about 3 GB;
   2. stops the services given with `--stop` (the application, so its data is
      closed cleanly);
   3. freezes the camera's root filesystem and streams the whole eMMC over SSH
      while this PC checksums and compresses it: about 5 minutes on gigabit
      Ethernet, during which the camera's writes wait;
   4. thaws the camera and starts the services again. It also thaws if the PC
      stops taking data for 60 s (crash, cable pulled), and by a safety timer
      after an hour (`--max-freeze`);
   5. checks that the image decompresses to the whole eMMC with the same
      checksum.

   `./backup_master.sh --help` lists the options. Offline instead: `sudo
   ../tools/backup_emmc.sh <name>` with the camera in TRIG/flash mode, then move
   the files here from `os-backup/`.
3. Optional deeper check: both filesystems check clean (Trixie's ext4 needs
   `e2fsck` 1.47 or newer, which Ubuntu 20.04 lacks; the camera has it).
4. Upload the `.img.zst` to Google Drive (restricted sharing), add its link and
   a row to the tables above, commit the checksum and layout files (git ignores
   the image and log), and keep the previous version.

## Troubleshooting

| Symptom | Fix |
|---|---|
| No new disk appears | The camera is not in flashing mode: power off, hold TRIG while powering on, keep holding about 3 s. |
| `no ….raw.sha256 to verify against` | Copy the image's `.raw.sha256` into this folder next to it. |
| `VERIFY FAILED` | USB error while writing: flash again; try another cable or port. |
| SSH warns "REMOTE HOST IDENTIFICATION HAS CHANGED" | The PC remembers a different camera at 192.168.1.10: `ssh-keygen -R 192.168.1.10`. |
