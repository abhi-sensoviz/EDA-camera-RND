#!/usr/bin/env bash
#
# Full eMMC backup of the ED-AIC3000 (CM5) into EDA-smartCam/os-backup/.
#
#   sudo ~/Desktop/EDA-smartCam/tools/backup_emmc.sh
#
# The camera is put in flashing mode (hold TRIG while powering on), rpiboot
# turns its eMMC into a USB disk on this PC, and that disk is read end to end,
# compressed with zstd, and checksum-verified. The eMMC is only ever READ.
#
set -euo pipefail

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

[ "$(id -u)" -eq 0 ] || die "run with sudo:  sudo $0"
USER_NAME=${SUDO_USER:-}
[ -n "$USER_NAME" ] && [ "$USER_NAME" != root ] || die "run via sudo from your normal user account"

TOOLS=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$TOOLS")                       # .../EDA-smartCam
RPIBOOT="$TOOLS/usbboot/rpiboot"
GADGET="$TOOLS/usbboot/mass-storage-gadget64"
OUT_DIR="$ROOT/os-backup"
NAME="aic3000-emmc-bookworm-$(date +%Y%m%d-%H%M)"

if   [ -x /home/linuxbrew/.linuxbrew/bin/zstd ]; then COMP=(/home/linuxbrew/.linuxbrew/bin/zstd -T0 -3 -q -c); EXT=img.zst; DECOMP=(/home/linuxbrew/.linuxbrew/bin/zstd -dc)
elif command -v zstd >/dev/null;                 then COMP=(zstd -T0 -3 -q -c); EXT=img.zst; DECOMP=(zstd -dc)
else                                                  COMP=(gzip -1 -c);        EXT=img.gz;  DECOMP=(gzip -dc)
fi
IMG="$OUT_DIR/$NAME.$EXT"

[ -x "$RPIBOOT" ] && [ -d "$GADGET" ] || die "rpiboot not built in $TOOLS/usbboot"

sudo -u "$USER_NAME" mkdir -p "$OUT_DIR"
avail_gb=$(( $(df --output=avail -B1 "$OUT_DIR" | tail -1) / 1000000000 ))
info "free space for the image: ${avail_gb} GB (expected compressed size: roughly 3-8 GB)"
[ "$avail_gb" -ge 8 ] || { read -r -p "Less than 8 GB free. Continue anyway? [y/N] " a; [ "$a" = y ] || exit 1; }

cat <<'EOF'

  On the camera:
    1. Shut it down cleanly first (from another terminal:
         ssh -t pi@192.168.1.10 'sudo poweroff'
       or Shutdown in its VNC desktop), wait ~15 s, then unplug the 24 V supply.
    2. Connect its USB-C port to this PC.
    3. HOLD the TRIG button, plug the 24 V back in, keep holding ~3 s, release.

EOF
read -r -p "Press Enter when that is done... " _

before=$(lsblk -dn -o NAME | sort)
info "starting rpiboot (waits for the camera)"
"$RPIBOOT" -d "$GADGET"

info "waiting for the eMMC to appear as a USB disk"
DEV=""
for _ in $(seq 90); do
    new=$(comm -13 <(echo "$before") <(lsblk -dn -o NAME | sort) | grep -v '^loop' | head -1 || true)
    if [ -n "$new" ]; then DEV="/dev/$new"; break; fi
    sleep 1
done
[ -n "$DEV" ] || die "no new disk appeared within 90 s"
sleep 3   # let the partitions settle (and the desktop auto-mount, which we undo)

# --- refuse anything that is not clearly the camera's eMMC ------------------
tran=$(lsblk -dn -o TRAN "$DEV" | tr -d ' ')
size=$(lsblk -bdn -o SIZE "$DEV" | tr -d ' ')
[ "$tran" = usb ] || die "$DEV is not a USB disk (transport '$tran')"
[ "$size" -ge 25000000000 ] && [ "$size" -le 40000000000 ] || die "$DEV is $size bytes; the camera eMMC is ~31 GB"
if lsblk -ln -o MOUNTPOINT "$DEV" | grep -qxE '/|/boot|/boot/efi|/home|/usr|/var'; then
    die "$DEV holds a system mount point of THIS PC - refusing"
fi

echo
lsblk -o NAME,SIZE,TRAN,MODEL,FSTYPE,LABEL,MOUNTPOINT "$DEV"
echo
read -r -p "Back up $DEV ($((size / 1000000)) MB) to $IMG ? Type YES: " ans
[ "$ans" = YES ] || die "cancelled"

for part in $(lsblk -ln -o NAME,MOUNTPOINT "$DEV" | awk 'NF==2 {print $1}'); do
    info "unmounting auto-mounted /dev/$part"
    umount "/dev/$part"
done

lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL,PARTUUID,MODEL "$DEV" > "$OUT_DIR/$NAME.lsblk.txt"
sfdisk -d "$DEV"                                        > "$OUT_DIR/$NAME.partitions.sfdisk"
chown "$USER_NAME:" "$OUT_DIR/$NAME".*

# --- read the whole eMMC once: compress it and checksum the raw stream ------
info "imaging $DEV -> $IMG  (USB 2 speed: expect 10-20 minutes)"
SHA_RAW="$OUT_DIR/$NAME.raw.sha256"
trap 'rm -f "$IMG"; echo "ERROR: imaging failed; partial file removed" >&2' ERR
dd if="$DEV" bs=4M iflag=fullblock status=progress \
    | tee >(sha256sum | cut -d' ' -f1 > "$SHA_RAW") \
    | sudo -u "$USER_NAME" "${COMP[@]}" > "$IMG"
trap - ERR
for _ in $(seq 60); do [ -s "$SHA_RAW" ] && break; sleep 1; done
chown "$USER_NAME:" "$IMG" "$SHA_RAW"

info "verifying: decompress the image and compare with the checksum taken while reading"
check=$(sudo -u "$USER_NAME" "${DECOMP[@]}" "$IMG" | sha256sum | cut -d' ' -f1)
raw=$(cat "$SHA_RAW")
[ -n "$raw" ] && [ "$check" = "$raw" ] || die "VERIFY FAILED: image $check vs read $raw"

sudo -u "$USER_NAME" sha256sum "$IMG" > "$IMG.sha256"
sync
echo
info "DONE - verified backup:"
ls -la "$OUT_DIR"/"$NAME"*
cat <<EOF

  Next: power-cycle the camera WITHOUT holding TRIG. It boots its normal OS
  (it should answer at 192.168.1.10 again). The USB-C cable can stay or go.

  To restore later (camera in TRIG/rpiboot mode again, check /dev/sdX carefully):
    ${DECOMP[*]} "$IMG" | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress
EOF
