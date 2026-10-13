# ED-AIC3000 full eMMC backups

These are full images of the camera's 32 GB eMMC, made by
`../tools/backup_emmc.sh` (rpiboot, read-only), to restore the camera exactly.

| File | What it is |
|---|---|
| `aic3000-emmc-bookworm-<date>.img.zst` | The compressed image of the whole eMMC (zstd) |
| `….img.zst.sha256` | Checksum of the compressed file |
| `….raw.sha256` | Checksum of the raw eMMC contents. The script checked the decompressed image against it. |
| `….partitions.sfdisk`, `….lsblk.txt` | Partition table and disk layout at backup time |

## Restore

1. Power the camera off and connect its USB-C port to this PC.
2. Hold **TRIG** while powering it on.
3. Run:

```bash
cd ~/Desktop/EDA-smartCam/tools/usbboot && sudo ./rpiboot -d mass-storage-gadget64
lsblk -d -o NAME,SIZE,TRAN,MODEL          # find the ~31 GB USB disk. NOT sda!
zstd -dc ../../os-backup/aic3000-emmc-bookworm-<date>.img.zst | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress
```

4. Power-cycle the camera without holding TRIG.

The image is the whole disk, so its contents and its network settings come back
as they were: Bookworm, static IP 192.168.1.10, EDATEC packages installed.
