# ED-AIC3000 backup (taken 2026-10-13, before the OS move)

**Source unit:** CM5 Rev 1.0, 32 GB eMMC, Raspberry Pi OS Bookworm (Debian 12),
kernel 6.12.25, `ed-aic3x00-lib` 1.20250915.1, `wiringpi` 3.14, factory IP
192.168.1.10.

**Related documents:**
- `../ED-AIC3000_PIN_MAPPING.md`: full pin map.
- `../ED-AIC3000_DEVELOPER_GUIDE.md`: protocols and code.
- `HARDWARE_REFERENCE.md` (in this folder): the first reverse-engineering notes.

| Folder | Contents | In the public repository? |
|---|---|---|
| `vendor-debs/` | `edatec-pubkey.gpg` (EDATEC repo signing key) and `repo-Packages-entries.txt` (repo index entries, including the SHA-256 of each `.deb`) | Yes. The `.deb` files themselves are **not** included (EDATEC's). |
| `installed-files/` | `MANIFEST.txt`: every file the two packages installed, with size and SHA-256 | Yes, the manifest only. The archive of the files is **not** included (EDATEC's). |
| `system-config/` | `config.txt`, `cmdline.txt`, udev rules (`98-com.rules` comes from EDATEC's package), apt sources | Yes |
| `hardware/` | Running device tree, decompiled stock overlays, all-pin `pinctrl` dump, I2C devices, `/dev` nodes, kernel log, cameras, board / EEPROM info | Yes; the serial number and MAC address are redacted |
| `inventory/` | OS release, full `dpkg -l`, manually installed packages, enabled services, NetworkManager profiles, `pip3 list` | Yes |
| `user-files/Desktop/` | `autoFocus.py` (the first SDK-based test script), `focus.txt` | Yes |
| `docs/` | The network-sharing setup guide as text (`.txt`, MAC redacted) | Yes. The PDFs, including EDATEC's manual and datasheet, are **not** included (links below). |

## Getting EDATEC's files back

Nothing EDATEC-owned is in this repository. Everything can be fetched again
from EDATEC and verified against the checksums kept here:

```bash
# Packages (exact versions used on this unit):
curl -O https://apt.edatec.cn/raspbian/pool/main/e/ed-aic3x00-lib/ed-aic3x00-lib_1.20250915.1_arm64.deb
curl -O https://apt.edatec.cn/raspbian/pool/main/w/wiringpi/wiringpi_3.14_arm64.deb
sha256sum *.deb        # compare with vendor-debs/repo-Packages-entries.txt

# Or through apt, on the camera:
curl -sS https://apt.edatec.cn/pubkey.gpg | sudo apt-key add -
echo "deb https://apt.edatec.cn/raspbian stable main" | sudo tee /etc/apt/sources.list.d/edatec.list
sudo apt update && sudo apt install ed-aic3x00-lib=1.20250915.1
```

- **User manual:** https://edatec.cn/docs/assets/aic3000/ED-AIC3000-usermanual-en.pdf
- **Datasheet and other docs:** https://edatec.cn/docs/aic3000/
- **Verify installed files** against `installed-files/MANIFEST.txt` (`sha256sum`).

## Setting the camera up again, with or without EDATEC's package

```bash
# With EDATEC's package (Bookworm is EDATEC-supported; on Trixie it installs,
# since it declares no dependencies, but EDATEC doesn't support that yet):
sudo apt install ./ed-aic3x00-lib_1.20250915.1_arm64.deb
sudo apt install ./wiringpi_3.14_arm64.deb     # only if WiringPi is not installed yet
sudo reboot
```

The package's `postinst` writes the udev rule and the `config.txt` lines. SDK-free
software (see the developer guide) needs only these two settings, not the library:

```bash
sudo cp system-config/etc/udev/rules.d/98-com.rules /etc/udev/rules.d/
sudo tee -a /boot/firmware/config.txt <<'EOF'
[all]
dtparam=i2c_arm=on
dtoverlay=imx477,cam0
dtoverlay=uart2-pi5
dtoverlay=uart3-pi5
dtoverlay=i2c1-pi5,pins_10_11
EOF
sudo reboot
```

After the reboot, check:
- `rpicam-hello --list-cameras` lists the IMX477.
- `ls -l /dev/com1 /dev/com2 /dev/i2c-1` shows all three.
- `python3 ../camera-tests/test_autofocus.py read` reads the lens.
