#!/bin/bash
#
# ED-AIC3000 golden image: seal the master camera for cloning.
#
#   sudo ./seal-golden.sh golden.conf          (on the master camera)
#
# The last step before capturing the golden image. It removes everything that
# must be unique per unit or must not ship, arms aic3000-firstboot.service so
# every clone gives itself a new identity on its first boot, and powers the
# camera off. Capture the image (tools/backup_emmc.sh) before it boots again.
#
# Take a pre-seal backup first: sealing deletes the paths in REMOVE_PATHS.
#
set -euo pipefail

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

HERE=$(cd "$(dirname "$0")" && pwd)
CONF_SRC=${1:-}
[ "$(id -u)" -eq 0 ] || die "run with sudo"
[ -n "$CONF_SRC" ] && [ -r "$CONF_SRC" ] || die "usage: sudo $0 <settings file> (start from golden.conf.example)"
for f in aic3000-firstboot.sh aic3000-firstboot.service; do
    [ -r "$HERE/$f" ] || die "missing $HERE/$f"
done

HOSTNAME_PREFIX=aic3000
APP_TLS_CERT=""
APP_TLS_KEY=""
APP_SERVICES=""
APP_RESET_PATHS=""
REMOVE_PATHS=""
# shellcheck disable=SC1090
. "$CONF_SRC"

# Paths from the settings file are deleted with rm -rf, so refuse anything
# shallower than three levels (/var/lib/app is fine, /var or /home/user is not).
# Runs in this shell (not a subshell), so a refusal stops the whole script.
RESET=()
REMOVE=()
collect() {                                            # collect <array> <patterns...>
    local -n into=$1
    shift
    local pattern path
    for pattern in "$@"; do
        for path in $pattern; do                       # unquoted: expand globs
            [ -e "$path" ] || [ -L "$path" ] || continue
            case "$path" in
                /*/*/*) ;;
                *) die "refusing to delete '$path': not at least three levels deep" ;;
            esac
            case "$path" in *..*) die "refusing to delete '$path': contains '..'" ;; esac
            into+=("$path")
        done
    done
}
# shellcheck disable=SC2086
collect RESET $APP_RESET_PATHS
# shellcheck disable=SC2086
collect REMOVE $REMOVE_PATHS

cat <<EOF

This seals THIS camera ($(hostname)) for cloning. It will:
  - install aic3000-firstboot (each clone renames itself ${HOSTNAME_PREFIX}-xxxxxx)
  - delete its SSH, VNC and application keys, machine ID, network secrets
  - reset application data (${#RESET[@]} paths)
  - DELETE (${#REMOVE[@]} paths):
$(printf '      %s\n' "${REMOVE[@]:-(none)}")
  - clear shell history, caches, browser profiles and logs of every user
  - turn cloud-init off (it would reset the hostname on every boot)
  - zero-fill free space, then POWER OFF

EOF
read -r -p "Pre-seal backup taken? Type SEAL to continue: " ans
[ "$ans" = SEAL ] || die "cancelled"

info "installing the first-boot service and its settings"
install -m 0755 "$HERE/aic3000-firstboot.sh" /usr/local/sbin/aic3000-firstboot.sh
install -m 0644 "$HERE/aic3000-firstboot.service" /etc/systemd/system/aic3000-firstboot.service
install -m 0644 "$CONF_SRC" /etc/aic3000-golden.conf
systemctl daemon-reload
systemctl enable aic3000-firstboot.service

info "stopping services"
for service in $APP_SERVICES wayvnc; do
    systemctl stop "$service" 2>/dev/null || true
done

info "application data and files that must not ship"
for path in "${RESET[@]}" "${REMOVE[@]}"; do
    [ -n "$path" ] && rm -rf -- "$path"
done

info "per-unit identity"
rm -f /etc/ssh/ssh_host_*
rm -f /etc/wayvnc/rsa_key.pem /etc/wayvnc/tls_key.pem /etc/wayvnc/tls_cert.pem
if [ -n "$APP_TLS_CERT" ]; then rm -f "$APP_TLS_CERT"; fi
if [ -n "$APP_TLS_KEY" ];  then rm -f "$APP_TLS_KEY";  fi
rm -f /var/lib/NetworkManager/secret_key /var/lib/NetworkManager/*.lease \
      /var/lib/NetworkManager/timestamps /var/lib/NetworkManager/seen-bssids
rm -f /var/lib/systemd/random-seed
rm -rf /var/lib/aic3000
# systemd treats the next boot as the first: new machine ID, and
# aic3000-firstboot.service (ConditionFirstBoot=yes) runs.
echo uninitialized > /etc/machine-id

info "cloud-init off"
touch /etc/cloud/cloud-init.disabled

info "history, caches and browser profiles"
for home in /root /home/*; do
    [ -d "$home" ] || continue
    rm -rf -- "$home/.bash_history" "$home/.python_history" "$home/.lesshst" \
              "$home/.cache" "$home/.npm" "$home/.config/chromium" \
              "$home/.xsession-errors" "$home/.xsession-errors.old" \
              "$home/.ssh/known_hosts" "$home/.ssh/known_hosts.old" \
              "$home/.local/share/recently-used.xbel" "$home/.sudo_as_admin_successful"
done

info "logs, package cache, temporary files"
apt-get clean
journalctl --rotate >/dev/null 2>&1 || true
journalctl --vacuum-time=1s >/dev/null 2>&1 || true
find /var/log -path /var/log/journal -prune -o -type f \
     \( -name '*.gz' -o -name '*.[0-9]' -o -name '*.old' \) -print0 | xargs -0r rm -f
find /var/log -path /var/log/journal -prune -o -type f -print0 | xargs -0r truncate -s 0
rm -rf /var/tmp/* /tmp/aic3000-* 2>/dev/null || true

info "zero-filling free space so the image compresses well (several minutes)"
dd if=/dev/zero of=/zero.fill bs=4M status=none 2>/dev/null || true
rm -f /zero.fill
sync

info "sealed. Powering off - capture the golden image before it boots again."
sleep 3
systemctl poweroff
