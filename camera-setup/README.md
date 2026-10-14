# Files to install on a fresh camera OS

To ship many cameras, set up one and clone it: see
[`../ED-AIC3000_GOLDEN_IMAGE.md`](../ED-AIC3000_GOLDEN_IMAGE.md) and [`golden-image/`](golden-image/).

Copy this folder to the camera, then run the commands from inside it.

| File | Install to | What it does |
|---|---|---|
| `98-com.rules` | `/etc/udev/rules.d/` | Creates `/dev/com1` (UART2) and `/dev/com2` (UART3, light MCU), as EDATEC's package did. |
| `50-aic-fixed-ip` | `/etc/NetworkManager/dispatcher.d/` | Keeps the fixed 192.168.1.10 out of `.local` answers while a DHCP address exists. See [`../ED-AIC3000_NETWORK_SETUP.md`](../ED-AIC3000_NETWORK_SETUP.md). |
| `99-password-store-basic` | `/etc/chromium.d/` | Stops Chromium opening a keyring password prompt at every start (with auto-login no keyring is unlocked, and Chromium blocks on the prompt). Saved browser passwords are then stored unencrypted in the profile. |

```bash
sudo cp 98-com.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=tty
sudo install -o root -g root -m 755 50-aic-fixed-ip /etc/NetworkManager/dispatcher.d/
sudo nmcli connection modify "Wired connection 1" +ipv4.addresses 192.168.1.10/24 ipv4.dhcp-timeout infinity
sudo nmcli connection up "Wired connection 1"
sudo install -o root -g root -m 644 99-password-store-basic /etc/chromium.d/
```
