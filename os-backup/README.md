# ED-AIC3000 full eMMC backups

These are full images of the camera's 32 GB eMMC, used to restore a camera
exactly. Master images of the set-up Trixie camera are in
[`../master-os-backup/`](../master-os-backup/README.md). There are two ways to
make an image:

- **Offline:** `../tools/backup_emmc.sh` (rpiboot, camera in TRIG/flash mode, read-only).
- **Live over the network:** the camera keeps running. Its unused blocks are
  TRIMmed first, the root filesystem is frozen with `fsfreeze` while `dd` streams
  `/dev/mmcblk0` over SSH, and a safety timer always thaws it. This gives a
  consistent snapshot without physical access.

## Backups taken

| File | Taken | Method | Compressed | Verified |
|---|---|---|---|---|
| `aic3000-emmc-bookworm-live-20261014-1036.img.zst` | 2026-10-14 (camera frozen 4.5 min) | live, `fsfreeze` + `dd` over SSH | 1.74 GB | 31,268,536,320 bytes (= disk); raw SHA-256 `6abb4508…ffc4` matches the read; `zstd -t` OK; `e2fsck -fn` on rootfs: clean, 147,269 files |

**Contents:** the factory OS: Bookworm (Debian 12), kernel 6.12.25,
`ed-aic3x00-lib` 1.20250915.1, static IP 192.168.1.10, all user files. The
partition table is `dos`, `0x8d94522e`: p1 vfat 512 MB `bootfs`, p2 ext4
28.6 GB `rootfs`.

| File | What it is |
|---|---|
| `aic3000-emmc-<name>.img.zst` | The compressed image of the whole eMMC (zstd) |
| `….img.zst.sha256` | Checksum of the compressed file |
| `….raw.sha256` | Checksum of the raw eMMC contents, taken while reading. The decompressed image was checked against it, and `flash_emmc.sh` checks the camera against it after writing. |
| `….partitions.sfdisk`, `….lsblk.txt` | Partition table and disk layout at backup time |
| `….log` | Live backups: when the camera was frozen and thawed, and the result |

## Restore

1. Power the camera off and connect its USB-C port to this PC.
2. Hold **TRIG** while powering it on, release after about 3 s.
3. Run (it asks you to confirm the disk, writes the image, then reads it back
   and compares it with the `.raw.sha256`):

```bash
cd ~/Desktop/EDA-smartCam
sudo tools/flash_emmc.sh os-backup/aic3000-emmc-<name>.img.zst
```

   The manual equivalent:

```bash
cd ~/Desktop/EDA-smartCam/tools/usbboot && sudo ./rpiboot -d mass-storage-gadget64
lsblk -d -o NAME,SIZE,TRAN,MODEL          # find the ~31 GB USB disk. NOT sda!
zstd -dc ../../os-backup/aic3000-emmc-<name>.img.zst | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress
```

4. Power-cycle the camera without holding TRIG.

The image is the whole disk, so everything comes back as it was, including the
network settings.

**Keep a second copy of each `.img.zst` somewhere private** (NAS, external
drive). They are not in git: they are large, and they contain EDATEC's software,
password hashes and SSH host keys.
