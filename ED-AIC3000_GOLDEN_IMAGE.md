# ED-AIC3000 golden image: set up one camera, flash the rest

Set up one camera exactly as it should ship, seal it, capture its eMMC as a
**golden image**, and give every new camera that image in one flash. On its first
boot each new camera gives itself its own name and keys, so it is ready to use
and does not clash with the others.

Status: the scripts are written and their safety checks and write/verify
pipeline are tested; **the full cycle (seal → capture → flash → first boot) still
needs a first trial run** on a camera before production use.

## How it works

| Step | Where | What happens |
|---|---|---|
| 1. Prepare the master | One camera | Install and configure everything the product ships with, and test it. |
| 2. Pre-seal backup | PC | Full image of the master as it is, kept for future updates. |
| 3. Seal | Master | Removes per-unit identity, test data, history and anything that must not ship; arms the first-boot service; powers off. |
| 4. Capture | PC | The golden image, read over USB-C with the camera in flashing mode. |
| 5. Flash | PC, per new camera | One command writes the golden image and verifies it. |
| 6. First boot | Each new camera | Names itself `<prefix>-xxxxxx` (from its serial number) and creates its own keys. |

**What a new camera gets from the image, and what it makes itself:**

| From the image (same on every unit) | Made on its first boot (unique per unit) |
|---|---|
| OS, packages, kernel and boot settings (`config.txt`) | Hostname `<prefix>-<last 6 hex digits of the serial>` |
| Your application, its configuration and the program or data it ships with | SSH host keys |
| udev rule, network setup (fixed 192.168.1.10 + DHCP) | VNC keys and certificate |
| Device settings: focus and light drives, status LED | Your application's HTTPS certificate (if `APP_TLS_CERT`/`APP_TLS_KEY` are set) |
| User accounts **and their passwords** | Machine ID (systemd) |
| | Network secret key and DHCP lease |

## Files

| File | Runs on | Purpose |
|---|---|---|
| [`camera-setup/golden-image/seal-golden.sh`](camera-setup/golden-image/seal-golden.sh) | Master camera | Seals it for cloning (step 3). |
| [`camera-setup/golden-image/aic3000-firstboot.sh`](camera-setup/golden-image/aic3000-firstboot.sh) + [`.service`](camera-setup/golden-image/aic3000-firstboot.service) | Each new camera | Per-unit identity on first boot. Installed by the seal script. |
| [`camera-setup/golden-image/golden.conf.example`](camera-setup/golden-image/golden.conf.example) | Master camera | Settings: hostname prefix, application certificate, data to reset, files to remove. |
| [`tools/backup_emmc.sh`](tools/backup_emmc.sh) `[name]` | PC | Captures a full eMMC image (steps 2 and 4). |
| [`tools/flash_emmc.sh`](tools/flash_emmc.sh) `<image>` | PC | Writes an image to a camera and verifies it (step 5). |

Both PC tools need `rpiboot` built once (`cd tools/usbboot && make`) and put the
camera in flashing mode the same way: power off, connect its USB-C port to the
PC, **hold TRIG** while powering on, release after about 3 s.

## 1. Prepare the master

Use one camera (or a spare unit kept for this) and set it up completely:
- Raspberry Pi OS and the camera settings ([`ai/OS_MIGRATION_PLAN.md`](ai/OS_MIGRATION_PLAN.md),
  [`camera-setup/README.md`](camera-setup/README.md)).
- Your application, installed as a service and enabled at boot, with the
  configuration and the program or data it should ship with.
- Networking: fixed 192.168.1.10 plus DHCP
  ([`ED-AIC3000_NETWORK_SETUP.md`](ED-AIC3000_NETWORK_SETUP.md)).
- Decide the **credentials** every unit will ship with (see "Before you sell").
- Test it as a customer would: camera, focus, lights, I/O, the application, a
  reboot, and power loss.

## 2. Pre-seal backup

```bash
sudo tools/backup_emmc.sh master-v1.0
```

Sealing deletes things you need for development (see step 3), so this image is
what you go back to for the next version. It lands in `os-backup/` (not in git)
with its checksums: move them into `master-os-backup/`, where the master images
are kept. Keep a second copy somewhere safe.

Without physical access it can also be taken live over the network, with the
camera's filesystem frozen while it streams (`master-os-backup/README.md`).

## 3. Seal the master

Copy `camera-setup/golden-image/` to the master, create the settings file from
the example, then run the seal script on the master:

```bash
cp golden.conf.example golden.conf     # then edit golden.conf
sudo ./seal-golden.sh golden.conf
```

It lists what it will delete and waits for you to type `SEAL`. Then it:

1. installs `aic3000-firstboot` and the settings (`/etc/aic3000-golden.conf`);
2. stops the application services;
3. resets application data (`APP_RESET_PATHS`) and deletes `REMOVE_PATHS` -
   anything shallower than three directory levels is refused;
4. deletes the SSH, VNC and application keys, the network secret key and DHCP
   lease, and sets `/etc/machine-id` to `uninitialized`, so systemd treats the
   next boot as the first;
5. turns cloud-init off - it would otherwise set the hostname back to the one
   from Raspberry Pi Imager on every boot;
6. clears shell history, caches, browser profiles and logs of every user;
7. fills free space with zeros (so the image compresses well) and **powers off**.

**Capture it before it boots again.** If the sealed master does boot, it gives
itself a new identity like any clone; seal it again before capturing.

## 4. Capture the golden image

With the sealed master in flashing mode:

```bash
sudo tools/backup_emmc.sh golden-v1.0
```

The image (about 2-4 GB compressed) and its checksums go to `os-backup/`.
Version the name and keep every released golden image.

## 5. Flash a new camera

With the new camera in flashing mode:

```bash
sudo tools/flash_emmc.sh os-backup/golden-v1.0-<date>.img.zst
```

The script refuses any disk that is not a ~31 GB USB disk or that this PC is
using, asks you to type `YES`, writes the image, and reads it back to compare
with the checksum taken at capture. Expect 10-20 minutes to write and the same
again to verify (`--no-verify` skips it). One camera at a time.

## 6. First boot and checks

Unplug the USB-C cable and power the camera on normally. On the first boot
(about a minute) `aic3000-firstboot` names it and creates its keys before any
network service starts. Then check:

| Check | How |
|---|---|
| It named itself | `ssh <user>@192.168.1.10 'hostname; cat /var/lib/aic3000/identity.log'` → `<prefix>-xxxxxx` |
| It has its own SSH key | The first SSH connection asks you to accept a new key (expected for every unit). |
| It is reachable by name | `<prefix>-xxxxxx.local` from a PC on the same network |
| Your application runs | Its web page or API answers and reports healthy. |
| Hardware | Camera detected, focus moves, lights test, status LED |

Record each unit's serial suffix, hostname and the image version it got.

## Updating the product

1. Flash the master with the latest **pre-seal** image (`tools/flash_emmc.sh`).
2. Update and test it.
3. Take a new pre-seal backup (`master-v1.1`), seal, capture `golden-v1.1`.

Never update by re-sealing a camera that came from a golden image: the pre-seal
image is the source of truth.

## Before you sell

| Topic | What to decide |
|---|---|
| **Credentials** | Every unit ships with the image's user accounts and passwords. Use strong ones, or have commissioning set a per-unit password; turn SSH password login off if you can use keys. The same goes for your application's own accounts. |
| **Fixed address** | Every unit keeps 192.168.1.10 as its fallback address. Two cameras on one network need different addresses: set it per installation (`ED-AIC3000_NETWORK_SETUP.md`). |
| **Certificates** | Each unit makes its own self-signed HTTPS certificate, so browsers warn once per unit. For customers who need trusted certificates, install CA-issued ones at commissioning. |
| **Licences** | Raspberry Pi OS is open-source software (GPL, LGPL and others). Shipping it on devices brings obligations - for example source offers for GPL parts and the LGPL terms for libraries such as Qt. Check with whoever handles licensing before selling. |
| **Hardware terms** | Replacing EDATEC's factory OS may matter for warranty and support; check your purchase or OEM terms with EDATEC. |
| **Bootloader** | The CM5 bootloader (EEPROM) is not on the eMMC, so it is not part of the image. Units may differ in bootloader version; update it with `rpi-eeprom-update` if a unit misbehaves. |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| A new camera still has the master's hostname | cloud-init still enabled, or the first-boot service did not run | `systemctl status aic3000-firstboot`, `ls /etc/cloud/cloud-init.disabled`; reseal and recapture. |
| SSH warns "REMOTE HOST IDENTIFICATION HAS CHANGED" | Each unit has its own key, and this PC remembers another unit at the same address | `ssh-keygen -R 192.168.1.10`, then connect again. |
| `flash_emmc.sh` verify fails | USB error while writing | Flash again; try another cable or port. |
| The sealed master booted before capture | It already gave itself an identity | Seal it again, then capture. |
| No new disk appears | Camera not in flashing mode | Power off, hold TRIG while powering on, keep holding about 3 s. |
