#!/usr/bin/env bash
#
# Live backup of an ED-AIC3000 camera's whole eMMC over SSH, saved next to
# this script. The camera keeps running; no TRIG/flash mode, no sudo on this PC.
#
#   ./backup_master.sh [options] <user>@<camera> [name]
#
#   name                 file name prefix (default aic3000-emmc-trixie-master);
#                        the image is <name>-live-<date>-<time>.img.zst
#   -s, --stop SERVICE   stop this systemd service on the camera during the
#                        copy and start it again afterwards (repeatable). Use
#                        it for the application, so its data is closed cleanly.
#   -y, --yes            do not ask for confirmation
#       --no-verify      skip decompressing the image to check it afterwards
#       --max-freeze SEC safety limit: the camera thaws itself after this long
#                        even if this PC disappears (default 3600)
#
# How: the camera's free space is TRIMmed (so it compresses to almost
# nothing), its root filesystem is frozen with fsfreeze while dd streams
# /dev/mmcblk0 over SSH, and this PC checksums and compresses the stream with
# zstd. While frozen, programs on the camera that write to disk wait: about
# 5 minutes on gigabit Ethernet, longer on slower links. The camera always
# thaws: when the copy ends, when the connection drops, and by a safety timer.
#
# Output, next to this script:
#   <image>.img.zst                   the whole eMMC, compressed (not for git)
#   <image>.raw.sha256                checksum of the raw eMMC (flash_emmc.sh needs it)
#   <image>.img.zst.sha256            checksum of the compressed file
#   <image>.partitions.sfdisk, .lsblk.txt   disk layout
#   <image>.log                       what happened on the camera
# Flash it with ../tools/flash_emmc.sh (see README.md).
#
# The camera's sudo password is asked once (or set CAM_SUDO_PASSWORD). SSH
# logs in once and reuses the connection.
#
set -euo pipefail

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

HERE=$(cd "$(dirname "$0")" && pwd)
STOP=()
YES=0
VERIFY=1
MAX_FREEZE=3600
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        -s|--stop)     [ $# -ge 2 ] || die "$1 needs a service name"; STOP+=("$2"); shift 2 ;;
        -y|--yes)      YES=1; shift ;;
        --no-verify)   VERIFY=0; shift ;;
        --max-freeze)  [ $# -ge 2 ] || die "$1 needs a number of seconds"; MAX_FREEZE=$2; shift 2 ;;
        -h|--help)     sed -n '3,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
        -*)            die "unknown option $1 (see --help)" ;;
        *)             ARGS+=("$1"); shift ;;
    esac
done
[ ${#ARGS[@]} -ge 1 ] && [ ${#ARGS[@]} -le 2 ] ||
    die "usage: $0 [options] <user>@<camera> [name]   (see --help)"
TARGET=${ARGS[0]}
PREFIX=${ARGS[1]:-aic3000-emmc-trixie-master}
[[ "$PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "the name must be a plain file name"
[[ "$MAX_FREEZE" =~ ^[0-9]+$ ]] && [ "$MAX_FREEZE" -ge 300 ] || die "--max-freeze must be at least 300 seconds"
for s in "${STOP[@]}"; do
    [[ "$s" =~ ^[A-Za-z0-9@._-]+$ ]] || die "bad service name '$s'"
done

if command -v zstd >/dev/null; then ZSTD=$(command -v zstd)
elif [ -x /home/linuxbrew/.linuxbrew/bin/zstd ]; then ZSTD=/home/linuxbrew/.linuxbrew/bin/zstd
else die "zstd is not installed (sudo apt install zstd)"
fi

NAME="$PREFIX-live-$(date +%Y%m%d-%H%M)"
IMG="$HERE/$NAME.img.zst"
RAW_SHA="$HERE/$NAME.raw.sha256"
LOG="$HERE/$NAME.log"
[ ! -e "$IMG" ] || die "$IMG already exists"
HELPER="/tmp/aic3000-live-dd-$$.sh"

# --- one SSH login, reused by every step ------------------------------------
CTL_DIR=$(mktemp -d)
SSH=(ssh -o ControlMaster=auto -o "ControlPath=$CTL_DIR/c" -o ControlPersist=900
     -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o ConnectTimeout=10)
remote() { "${SSH[@]}" "$TARGET" "$@"; }

CAP=""
DONE_OK=0
cleanup() {
    if [ -n "$CAP" ] && kill -0 "$CAP" 2>/dev/null; then
        pkill -P "$CAP" 2>/dev/null || true      # closing the stream thaws the camera
    fi
    if "${SSH[@]}" -O check "$TARGET" >/dev/null 2>&1; then   # only over the open login
        remote "rm -f $HELPER" </dev/null >/dev/null 2>&1 || true
        "${SSH[@]}" -O exit "$TARGET" >/dev/null 2>&1 || true
    fi
    rm -rf "$CTL_DIR"
    if [ "$DONE_OK" != 1 ] && [ -e "$IMG" ]; then
        rm -f "$IMG" "$RAW_SHA"
        echo "Partial image removed. The camera thaws itself; if it seems stuck, run" >&2
        echo "'sudo fsfreeze -u /' on it." >&2
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

info "connecting to $TARGET"
"${SSH[@]}" -fN "$TARGET" </dev/null || die "cannot connect to $TARGET"
remote 'PATH=$PATH:/usr/sbin:/sbin; command -v fsfreeze && command -v fstrim && [ -b /dev/mmcblk0 ]' </dev/null >/dev/null ||
    die "the camera has no /dev/mmcblk0, fsfreeze or fstrim"
ROOTDEV=$(remote 'findmnt -no SOURCE /' </dev/null)
[ "$ROOTDEV" = /dev/mmcblk0p2 ] || die "the camera's root filesystem is on '$ROOTDEV', not /dev/mmcblk0p2"
DISK_BYTES=$(remote 'lsblk -bdn -o SIZE /dev/mmcblk0' </dev/null | tr -d ' ')
USED_BYTES=$(remote 'df -B1 --output=used / | tail -1' </dev/null | tr -d ' ')
CAM_HOST=$(remote hostname </dev/null)
for s in "${STOP[@]}"; do
    remote "systemctl cat $s >/dev/null 2>&1" </dev/null || die "no service '$s' on the camera"
done

# --- root on the camera -----------------------------------------------------
if remote 'sudo -n true' </dev/null >/dev/null 2>&1; then
    SUDO_PW=""
    SUDO_CMD="sudo -n"
else
    SUDO_PW=${CAM_SUDO_PASSWORD:-}
    if [ -z "$SUDO_PW" ]; then
        read -rs -p "sudo password for $TARGET: " SUDO_PW </dev/tty
        echo
    fi
    SUDO_CMD="sudo -S -p ''"
    printf '%s\n' "$SUDO_PW" | remote "$SUDO_CMD true" >/dev/null 2>&1 ||
        die "sudo on the camera failed (wrong password?)"
fi
rsudo() { printf '%s\n' "$SUDO_PW" | remote "$SUDO_CMD $1"; }

# --- room for the image -----------------------------------------------------
AVAIL=$(df --output=avail -B1 "$HERE" | tail -1)
EST=$(( USED_BYTES / 2 ))          # v1.0: 9.6 GB used -> 3.1 GB compressed
[ "$AVAIL" -gt $(( EST + 2000000000 )) ] ||
    die "only $(( AVAIL / 1000000000 )) GB free in $HERE; allow $(( EST / 1000000000 + 2 )) GB"

cat <<EOF

  Camera   $TARGET ($CAM_HOST): eMMC $(( DISK_BYTES / 1000000000 )) GB, $(( USED_BYTES / 1000000000 )) GB in use
  Image    $IMG
  Stops    ${STOP[*]:-nothing} (started again afterwards)

  The camera's root filesystem is frozen while its eMMC is copied: about
  5 minutes on gigabit Ethernet. Programs on it that write to disk wait.

EOF
if [ "$YES" != 1 ]; then
    read -r -p "Continue? [y/N] " answer </dev/tty
    [ "$answer" = y ] || [ "$answer" = Y ] || die "cancelled"
fi

echo "start $(date -Is) $TARGET ($CAM_HOST)" >> "$LOG"

info "TRIM the camera's free space (so it compresses to almost nothing)"
rsudo "fstrim -av" | tee -a "$LOG"

info "saving the partition table and layout"
rsudo "sfdisk -d /dev/mmcblk0" > "$HERE/$NAME.partitions.sfdisk"
remote 'lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL,PARTUUID,MOUNTPOINT /dev/mmcblk0; grep PRETTY_NAME /etc/os-release; uname -r' \
    </dev/null > "$HERE/$NAME.lsblk.txt"

# Runs as root on the camera: streams /dev/mmcblk0 to stdout with / frozen.
remote "umask 077; cat > $HELPER" <<EOF
#!/bin/sh
SERVICES="${STOP[*]}"
MARK=/run/aic3000-live-dd.early-thaw
rm -f "\$MARK"
for s in \$SERVICES; do systemctl stop "\$s"; done
sync
echo 3 > /proc/sys/vm/drop_caches
BOOT_RO=0
if mountpoint -q /boot/firmware && mount -o remount,ro /boot/firmware 2>/dev/null; then BOOT_RO=1; fi

# Last resort if this PC disappears: thaw and restart after $MAX_FREEZE s.
( sleep $MAX_FREEZE; touch "\$MARK"; fsfreeze -u /; mount -o remount,rw /boot/firmware
  for s in \$SERVICES; do systemctl start "\$s"; done ) </dev/null >/dev/null 2>&1 &
WD=\$!
DD=""

thaw() {
    kill "\$WD" \$DD 2>/dev/null
    fsfreeze -u / 2>/dev/null
    [ "\$BOOT_RO" = 1 ] && mount -o remount,rw /boot/firmware 2>/dev/null
    BOOT_RO=0
    echo "THAWED \$(date +%T)" >&2
    for s in \$SERVICES; do
        systemctl start "\$s"
        echo "SERVICE \$s \$(systemctl is-active "\$s")" >&2
    done
}
trap thaw EXIT
trap 'exit 1' INT TERM HUP PIPE

fsfreeze -f / || exit 1
echo "FROZEN \$(date +%T) boot_ro=\$BOOT_RO" >&2
# If this PC stops taking data (it crashed, the cable was pulled), dd blocks
# on the network; stop after 60 s without progress so the camera thaws.
dd if=/dev/mmcblk0 bs=4M status=none &
DD=\$!
last=-1
still=0
while kill -0 \$DD 2>/dev/null; do
    sleep 5
    now=\$(awk '/^rchar/ {print \$2}' /proc/\$DD/io 2>/dev/null)
    if [ "\$now" = "\$last" ]; then still=\$((still + 5)); else still=0; last=\$now; fi
    if [ \$still -ge 60 ]; then
        echo "STALLED: no progress for 60 s; stopping the copy" >&2
        kill \$DD
        break
    fi
done
wait \$DD
rc=\$?
DD=""
if [ -e "\$MARK" ]; then
    echo "EARLY_THAW: the safety timer thawed the camera during the copy" >&2
    rc=3
fi
echo "DD_RC=\$rc" >&2
exit \$rc
EOF

# --- the copy -----------------------------------------------------------------
info "copying the eMMC ($(( DISK_BYTES / 1000000000 )) GB); the camera is frozen until this ends"
capture() {
    set +e
    printf '%s\n' "$SUDO_PW" \
        | "${SSH[@]}" "$TARGET" "$SUDO_CMD sh $HELPER" 2>>"$LOG" \
        | dd bs=4M status=progress \
        | tee >(sha256sum | cut -d' ' -f1 > "$RAW_SHA") \
        | "$ZSTD" -T0 -3 -q -c > "$IMG"
    echo "${PIPESTATUS[*]}" > "$CTL_DIR/status"
}
capture &
CAP=$!
while kill -0 "$CAP" 2>/dev/null; do
    if [ "$(df --output=avail -B1 "$HERE" | tail -1)" -lt 2000000000 ]; then
        echo >&2
        die "less than 2 GB left in $HERE; copy stopped"
    fi
    sleep 5
done
wait "$CAP" || true
CAP=""
for _ in $(seq 60); do [ -s "$RAW_SHA" ] && break; sleep 1; done
echo "pipeline $(cat "$CTL_DIR/status" 2>/dev/null) end $(date -Is)" >> "$LOG"

read -r -a status < "$CTL_DIR/status" || status=(1)
for rc in "${status[@]}"; do
    [ "$rc" = 0 ] || die "the copy failed (exit codes ${status[*]}); see $LOG"
done
grep -q '^DD_RC=0$' "$LOG" || die "dd on the camera did not finish cleanly; see $LOG"
[ -s "$RAW_SHA" ] || die "no checksum of the raw stream"

# --- the camera is back -------------------------------------------------------
if remote 'f=/var/tmp/.aic3000-thaw-test; timeout 15 touch "$f" && rm -f "$f"' </dev/null; then
    info "camera thawed: its root filesystem is writable again"
else
    echo "WARNING: the camera's root filesystem is not writable yet; run 'sudo fsfreeze -u /' on it" >&2
fi
for s in "${STOP[@]}"; do
    info "service $s: $(remote "systemctl is-active $s" </dev/null || true)"
done

# --- check the image ------------------------------------------------------------
if [ "$VERIFY" = 1 ]; then
    info "verifying: decompressing the image and comparing it with the raw checksum"
    SIZE_FILE="$CTL_DIR/size"
    got=$("$ZSTD" -dc "$IMG" | tee >(wc -c > "$SIZE_FILE") | sha256sum | cut -d' ' -f1)
    for _ in $(seq 30); do [ -s "$SIZE_FILE" ] && break; sleep 1; done
    size=$(tr -d ' ' < "$SIZE_FILE")
    [ "$got" = "$(cat "$RAW_SHA")" ] || die "VERIFY FAILED: image $got vs stream $(cat "$RAW_SHA")"
    [ "$size" = "$DISK_BYTES" ] || die "VERIFY FAILED: image is $size bytes, the eMMC $DISK_BYTES"
    info "verified: $size bytes (the whole eMMC), checksum matches"
    echo "verified $(date -Is) size=$size sha256=$got" >> "$LOG"
fi
(cd "$HERE" && sha256sum "$NAME.img.zst" > "$NAME.img.zst.sha256")
DONE_OK=1

echo
info "DONE: $(du -h "$IMG" | cut -f1) in $IMG"
cat <<EOF

  Next:
    - Upload $NAME.img.zst to Google Drive (restricted sharing) and add its
      link and a row to README.md.
    - Commit the checksums and layout files (git ignores the image and log):
        git add $NAME.raw.sha256 $NAME.img.zst.sha256 \\
                $NAME.partitions.sfdisk $NAME.lsblk.txt
    - Flash a camera with it:  sudo ../tools/flash_emmc.sh $NAME.img.zst
EOF
