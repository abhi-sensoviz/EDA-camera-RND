#!/bin/bash
#
# ED-AIC3000 golden image: give this unit its own identity on its first boot.
#
# Installed by seal-golden.sh as /usr/local/sbin/aic3000-firstboot.sh and run
# once by aic3000-firstboot.service, before any network service starts, on the
# first boot after the image was flashed (systemd "first boot": /etc/machine-id
# reads "uninitialized"). Every clone of the image would otherwise share the
# master's hostname, SSH/VNC keys and TLS certificate.
#
# Settings come from /etc/aic3000-golden.conf (see golden.conf.example).
#
set -u

CONF=/etc/aic3000-golden.conf
HOSTNAME_PREFIX=aic3000
FIXED_IP=192.168.1.10
APP_TLS_CERT=""
APP_TLS_KEY=""
APP_TLS_GROUP=root
# shellcheck disable=SC1090
[ -r "$CONF" ] && . "$CONF"

log() { echo "[aic3000-firstboot] $*"; }

# --- hostname from the CM5 serial number: <prefix>-<last 6 hex digits> -------
serial=$(tr -d '\0' < /proc/device-tree/serial-number 2>/dev/null || true)
suffix=$(printf '%s' "$serial" | tr -cd '0-9a-fA-F' | tail -c 6 | tr 'A-F' 'a-f')
[ ${#suffix} -eq 6 ] || suffix=$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')
name="${HOSTNAME_PREFIX}-${suffix}"

echo "$name" > /etc/hostname
hostname "$name"
if grep -q '^127\.0\.1\.1' /etc/hosts; then
    sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$name/" /etc/hosts
else
    printf '127.0.1.1\t%s\n' "$name" >> /etc/hosts
fi
log "hostname $name"

# --- SSH host keys (Raspberry Pi OS also does this on first boot; harmless) --
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A >/dev/null 2>&1 && log "new SSH host keys"

# --- VNC (wayvnc) keys; its script names the certificate after the hostname -
if [ -x /usr/sbin/wayvnc-generate-keys.sh ] || [ -f /usr/sbin/wayvnc-generate-keys.sh ]; then
    rm -f /etc/wayvnc/rsa_key.pem /etc/wayvnc/tls_key.pem /etc/wayvnc/tls_cert.pem
    sh /usr/sbin/wayvnc-generate-keys.sh >/dev/null 2>&1 && log "new VNC keys"
fi

# --- application HTTPS certificate (self-signed, for this unit's names) ------
if [ -n "$APP_TLS_CERT" ] && [ -n "$APP_TLS_KEY" ]; then
    mkdir -p "$(dirname "$APP_TLS_CERT")" "$(dirname "$APP_TLS_KEY")"
    if openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 3650 \
           -keyout "$APP_TLS_KEY" -out "$APP_TLS_CERT" \
           -subj "/CN=$name.local" \
           -addext "subjectAltName=DNS:$name.local,DNS:$name,IP:$FIXED_IP,IP:127.0.0.1" \
           >/dev/null 2>&1; then
        chown "root:$APP_TLS_GROUP" "$APP_TLS_KEY"
        chmod 0640 "$APP_TLS_KEY"
        chmod 0644 "$APP_TLS_CERT"
        log "new application certificate for $name.local"
    else
        log "WARNING: could not create the application certificate"
    fi
fi

# --- record what this unit became ------------------------------------------
mkdir -p /var/lib/aic3000
printf '%s first boot: hostname %s (serial ...%s)\n' "$(date -Is)" "$name" "$suffix" \
    >> /var/lib/aic3000/identity.log

systemctl disable aic3000-firstboot.service >/dev/null 2>&1 || true
log "done"
exit 0
