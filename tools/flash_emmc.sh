#!/usr/bin/env bash
#
# Flash an eMMC image (a golden image or a backup) onto an ED-AIC3000 (CM5).
#
#   sudo ~/Desktop/EDA-smartCam/tools/flash_emmc.sh <image> [--no-verify]
#
# <image> is a full-disk image from backup_emmc.sh: .img.zst, .img.gz or .img.
# The camera is put in flashing mode (hold TRIG while powering on), rpiboot
# turns its eMMC into a USB disk on this PC, the image is written to it, and -
# unless --no-verify - the eMMC is read back and compared with the checksum
# taken when the image was captured (<name>.raw.sha256 next to the image).
#
# Everything on the camera's eMMC is overwritten.
#
set -euo pipefail

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

[ "$(id -u)" -eq 0 ] || die "run with sudo:  sudo $0 <image>"
IMG=${1:-}
VERIFY=1
[ "${2:-}" = "--no-verify" ] && VERIFY=0
[ -n "$IMG" ] && [ -r "$IMG" ] || die "usage: sudo $0 <image.img.zst|.img.gz|.img> [--no-verify]"
IMG=$(readlink -f "$IMG")

TOOLS=$(cd "$(dirname "$0")" && pwd)
RPIBOOT="$TOOLS/usbboot/rpiboot"
GADGET="$TOOLS/usbboot/mass-storage-gadget64"
[ -x "$RPIBOOT" ] && [ -d "$GADGET" ] || die "rpiboot not built in $TOOLS/usbboot (see README)"

ZSTD=zstd
[ -x /home/linuxbrew/.linuxbrew/bin/zstd ] && ZSTD=/home/linuxbrew/.linuxbrew/bin/zstd
case "$IMG" in
    *.img.zst) DECOMP=("$ZSTD" -dc); BASE=${IMG%.img.zst} ;;
    *.img.gz)  DECOMP=(gzip -dc);    BASE=${IMG%.img.gz}  ;;
    *.img)     DECOMP=(cat);         BASE=${IMG%.img}     ;;
    *) die "unknown image type: $IMG" ;;
esac
RAW_SHA=""
[ -s "$BASE.raw.sha256" ] && RAW_SHA=$(cut -d' ' -f1 < "$BASE.raw.sha256")
if [ "$VERIFY" = 1 ] && [ -z "$RAW_SHA" ]; then
    die "no $BASE.raw.sha256 to verify against (use --no-verify to skip verification)"
fi

cat <<'EOF'

  On the camera:
    1. Power it off (unplug the 24 V supply).
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
read -r -p "ERASE $DEV ($((size / 1000000)) MB) and write $(basename "$IMG")? Type YES: " ans
[ "$ans" = YES ] || die "cancelled"

for part in $(lsblk -ln -o NAME,MOUNTPOINT "$DEV" | awk 'NF==2 {print $1}'); do
    info "unmounting auto-mounted /dev/$part"
    umount "/dev/$part"
done

# --- write ------------------------------------------------------------------
COUNT=$(mktemp)
trap 'rm -f "$COUNT"' EXIT
info "writing $(basename "$IMG") -> $DEV  (USB 2 speed: expect 10-20 minutes)"
"${DECOMP[@]}" "$IMG" \
    | tee >(wc -c > "$COUNT") \
    | dd of="$DEV" bs=4M iflag=fullblock oflag=direct conv=fsync status=progress
for _ in $(seq 30); do [ -s "$COUNT" ] && break; sleep 1; done
bytes=$(tr -d ' ' < "$COUNT")
[ "$bytes" -gt 0 ] || die "nothing was written"
[ "$bytes" -le "$size" ] || die "the image ($bytes bytes) is larger than the eMMC ($size bytes)"
sync
blockdev --flushbufs "$DEV" 2>/dev/null || true

# --- verify -----------------------------------------------------------------
if [ "$VERIFY" = 1 ]; then
    info "verifying: reading the eMMC back ($((bytes / 1000000)) MB)"
    echo 3 > /proc/sys/vm/drop_caches
    got=$(head -c "$bytes" "$DEV" | sha256sum | cut -d' ' -f1)
    [ "$got" = "$RAW_SHA" ] || die "VERIFY FAILED: eMMC $got vs image $RAW_SHA - flash again"
    info "verified: the eMMC matches the image"
else
    info "verification skipped"
fi

echo
info "DONE: $DEV now holds $(basename "$IMG")"
cat <<'EOF'

  Next: unplug the USB-C cable and power-cycle the camera WITHOUT holding TRIG.
  A golden image gives the unit its own name and keys on this first boot
  (allow a minute); see ED-AIC3000_GOLDEN_IMAGE.md for the checks.
EOF
