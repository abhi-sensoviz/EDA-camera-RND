# ED-AIC3000 network setup

How to connect the camera to a PC, give it internet, and reach it by SSH or VNC.
Covers the camera's own configuration (to rebuild it) and the usual problems.
Tested on 2026-10-14 with Raspberry Pi OS Trixie on the camera and Ubuntu 20.04
on the PC.

## How the camera's port behaves

The camera has one Ethernet port (`eth0`) and no Wi-Fi. It can be reached in three ways:

| | Address | Where it comes from | Use it for |
|---|---|---|---|
| **Fixed address** | **192.168.1.10/24** | Set on the camera. Present with or without a DHCP server. | Reaching the camera from any PC whose wired port is on 192.168.1.x |
| **DHCP address** | Whatever the PC or router hands out | DHCP. The camera never stops asking, so it picks one up whenever a server appears. | Internet: the gateway and DNS come with it |
| **Name** | **<hostname>.local** | mDNS (Avahi) | Reaching the camera without knowing its address |

- **The name points at the DHCP address** when there is one, and at 192.168.1.10 only when there's nothing else. A hook on the camera ([`camera-setup/50-aic-fixed-ip`](camera-setup/50-aic-fixed-ip)) marks 192.168.1.10 "deprecated". Avahi doesn't announce deprecated addresses while another address exists, and a deprecated address still accepts connections.
- **Internet comes only through DHCP.** The fixed address has no gateway, so with the fixed address alone the camera is reachable but offline.
- **The name must be unique** on every network the PC is on, including the PC's Wi-Fi. If another device has the same hostname, `<hostname>.local` can resolve to that device instead.

## Pick a setup

| Setup on the PC | Reach the camera at | Camera has internet |
|---|---|---|
| **A. Share on 192.168.1.1** (recommended) | 192.168.1.10 or <hostname>.local | Yes |
| B. Settings app "Shared to other computers" (10.42.0.1) | <hostname>.local, or its 10.42.0.x address | Yes |
| C. Fixed address 192.168.1.x, no sharing | 192.168.1.10 | No |
| D. Camera plugged into a router or switch | <hostname>.local, or the router's client list | Yes |
| E. Windows Internet Connection Sharing (192.168.137.1) | <hostname>.local, or `arp -a` | Yes (untested) |

### A. Share on 192.168.1.1 (recommended, Linux)

The PC shares its internet (Wi-Fi or another port) on the wired port, using the
same subnet as the camera's fixed address, so 192.168.1.10 always works.

**Terminal**, once per PC:

```bash
ip -br link                                   # find the wired port, e.g. enp7s0f1
nmcli connection add type ethernet ifname <wired-port> con-name AIC3000-Share \
      ipv4.method shared ipv4.addresses 192.168.1.1/24 \
      connection.autoconnect yes connection.autoconnect-priority 100
nmcli connection up AIC3000-Share
```

`autoconnect-priority 100` matters. When the camera reboots, the link drops for a
moment, and without it NetworkManager may switch the port to another wired profile.

**GUI:** Ubuntu's Settings app greys out the address field when sharing is selected; the advanced editor doesn't.
1. Run `nm-connection-editor`, or open "Advanced Network Configuration".
2. Select the wired connection and click the gear icon.
3. On the **IPv4 Settings** tab, set Method to **Shared to other computers**.
4. Under Addresses, click **Add**: address `192.168.1.1`, netmask `24`, gateway empty.
5. Click **Save**, then turn the wired connection off and on (or replug the cable).

**Check:** `ip -br addr show <wired-port>` shows `192.168.1.1/24`; then `ssh <user>@192.168.1.10`.

Ubuntu 20.04's NetworkManager (1.22) silently drops a second address on a shared
profile, so the share can't carry both 10.42.0.1 and 192.168.1.1. That is why
setup A moves the whole share to 192.168.1.1.

### B. Settings app sharing (10.42.0.1)

1. Open Settings → Network → Wired (gear icon) → IPv4 → **Shared to other computers** → Apply.
2. Replug the cable.

The camera gets a 10.42.0.x address. Connect with `ssh <user>@<hostname>.local`.
Tested: the name resolves to the 10.42.0.x address, and SSH and the camera's
internet both work. From this PC, 192.168.1.10 is **not** reachable in this mode.
To see the camera's address, run `ip neigh show dev <wired-port>`.

### C. No sharing

```bash
nmcli connection add type ethernet ifname <wired-port> con-name AIC3000-Direct \
      ipv4.method manual ipv4.addresses 192.168.1.11/24
nmcli connection up AIC3000-Direct
ssh <user>@192.168.1.10
```

The camera has no internet in this mode.

### D. Router or switch

Plug the camera in. It takes an address from the router. Use `<hostname>.local` from
any PC on that network, or look the camera up in the router's DHCP client list.
If the router's network is also 192.168.1.x, make sure nothing else on it uses
192.168.1.10.

### E. Windows (not tested)

1. Open Control Panel → Network Connections.
2. Right-click the adapter that has internet (usually Wi-Fi) → Properties → **Sharing**.
3. Tick "Allow other network users to connect…" and choose the Ethernet adapter.

The camera gets a 192.168.137.x address. Use `<hostname>.local`; Windows 10 and 11
resolve `.local` names. Or run `arp -a` and look for a 192.168.137.x entry.

## Connecting

| What | How |
|---|---|
| SSH | `ssh <user>@192.168.1.10`, or `ssh <user>@<hostname>.local` |
| Copy files | `scp <file> <user>@192.168.1.10:~/Desktop/` |
| Desktop (VNC) | VNC viewer to `192.168.1.10` (port 5900), or `<hostname>.local`. Log in with the camera's user and password. The server is wayvnc (enabled with `sudo raspi-config nonint do_vnc 0`); Raspberry Pi recommends RealVNC Viewer. |

## Checks

On the PC:

```bash
ip -br addr show <wired-port>      # A: 192.168.1.1/24   B: 10.42.0.1/24
nmcli connection show --active     # the share profile is active on the wired port
ip neigh show dev <wired-port>     # the camera's addresses
getent hosts <hostname>.local          # what the name resolves to
ip route get <address>             # must leave through the wired port, not Wi-Fi
```

On the camera:

```bash
ip -4 -br addr show eth0           # 192.168.1.10 plus the DHCP address
ip route | head -1                 # default via the PC (192.168.1.1 or 10.42.0.1)
ping -c1 1.1.1.1 && curl -sI https://deb.debian.org | head -1
timedatectl show -p NTPSynchronized   # apt fails if the clock is wrong
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Permission denied" although the password is right | The name or address reaches a **different machine**. Either another device has the same hostname, or the PC's wired port isn't on 192.168.1.x, so 192.168.1.10 is routed out through Wi-Fi. | Run `getent hosts <hostname>.local` and `ip route get <address>`; the route must use the wired port. Give the camera a unique hostname. |
| "REMOTE HOST IDENTIFICATION HAS CHANGED" | `~/.ssh/known_hosts` holds an old key: the camera was reflashed, or the name used to reach another device. | First confirm the route uses the wired port, and compare `ssh-keyscan -t ecdsa <address> \| ssh-keygen -lf -` with the camera's key. Then run `ssh-keygen -R <address-or-name>`. |
| Camera unreachable after it rebooted | NetworkManager switched the PC's wired port to another profile while the link was down. | `nmcli connection up AIC3000-Share`, and give it `connection.autoconnect-priority 100`. |
| `<hostname>.local` hangs | The name gave an address the PC can't reach. | Check the hook is installed (below). Use the IP meanwhile. |
| No internet on the camera | The share isn't active, or the camera still holds a lease from another setup. | On the PC: `nmcli connection show --active`. On the camera: `sudo nmcli connection up "Wired connection 1"`. |
| `apt` says the lists are "not valid yet" | The camera's clock is wrong. | Wait for NTP (`timedatectl`), or set the date. |

## Camera-side configuration (to rebuild it)

On a fresh Raspberry Pi OS install, from a copy of [`camera-setup/`](camera-setup/):

```bash
sudo nmcli connection modify "Wired connection 1" +ipv4.addresses 192.168.1.10/24 ipv4.dhcp-timeout infinity
sudo install -o root -g root -m 755 50-aic-fixed-ip /etc/NetworkManager/dispatcher.d/
sudo nmcli connection up "Wired connection 1"
```

- `+ipv4.addresses` adds the fixed address next to DHCP; the method stays `auto`.
- `ipv4.dhcp-timeout infinity` is required. Without it, NetworkManager gives up on DHCP after 45 s and takes the fixed address down with it.
- `50-aic-fixed-ip` runs whenever `eth0` comes up or renews DHCP, and marks 192.168.1.10 deprecated. It must be owned by root and not group- or world-writable, or NetworkManager ignores it.
- **Hostname:** `sudo raspi-config nonint do_hostname <name>`, then reboot. Pick a name no other device uses.
- **Another fixed address:** `sudo nmcli connection modify "Wired connection 1" -ipv4.addresses 192.168.1.10/24 +ipv4.addresses <new>/24`, and change the address in the hook too.
- **Several cameras on one network:** give each its own fixed address and hostname.
- **Undo:** `sudo nmcli connection modify "Wired connection 1" -ipv4.addresses 192.168.1.10/24 ipv4.dhcp-timeout 0`, then delete the hook.

The same folder holds `98-com.rules`, the udev rule for `/dev/com1` and `/dev/com2`
(`sudo cp 98-com.rules /etc/udev/rules.d/`).

## Test record (2026-10-14)

| Test | Result |
|---|---|
| PC on plain 192.168.1.11 (no DHCP server); camera reconnects | 192.168.1.10 stayed up for 90 s while DHCP kept retrying in the background |
| Setup A | Camera at 192.168.1.10 + 192.168.1.107; internet OK; the name → 192.168.1.107 only |
| Setup B (PC on 10.42.0.1) | The name → 10.42.0.107; SSH and the camera's internet OK |
| DHCP address removed by hand | The name → 192.168.1.10 |
| Without the hook | The name announced both 192.168.1.107 and 192.168.1.10; with the PC on 10.42.0.1, `.local` sometimes gave the unreachable 192.168.1.10 |
| Setups D and E | Not tested |
