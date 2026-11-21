# Installing DumbTube on the TV from Termux (ADB over Wi-Fi)

You run `scripts/install-dumbtube.sh` in Termux on your phone. It downloads the latest DumbTube
APK from your fork's GitHub Releases, connects to the TV over Wi-Fi with `adb`, and runs
`adb install -r`. `-r` replaces the app and **keeps its settings**.

Phone and TV must be on the **same Wi-Fi/LAN**.

---

## 1. Termux (phone, once)

1. Install **Termux from F-Droid** (https://f-droid.org/packages/com.termux/) or from its GitHub
   releases. The Google Play version is outdated and its packages don't install.
2. Open Termux and install the tools:

   ```bash
   pkg update && pkg upgrade
   pkg install android-tools curl     # adb + curl
   pkg install jq                     # optional, the script works without it
   ```

   Check: `adb version` prints a version.
3. Get the script. Replace `OWNER/REPO/BRANCH` with your fork, e.g. `pringleprng/start/dumbtube`:

   ```bash
   curl -fLo ~/install-dumbtube.sh \
     https://raw.githubusercontent.com/OWNER/REPO/BRANCH/scripts/install-dumbtube.sh
   chmod +x ~/install-dumbtube.sh
   ```

   (Or `pkg install git && git clone https://github.com/OWNER/REPO` and use `scripts/install-dumbtube.sh`.)

## 2. Developer options and network debugging (TV, once)

The menu names differ a little between brands. Look for these:

1. **Unlock Developer options**
   - Android TV / Google TV: *Settings → System → About* (older: *Device Preferences → About*) →
     press OK on **Build** (or *Android TV OS build*) 7 times until it says "You are now a developer".
   - Fire TV: *Settings → My Fire TV → About* → press OK on the device name 7 times.
2. **Turn on ADB over the network.** Back in *Settings → System → Developer options*:
   - Most Android TVs: **USB debugging** → On. Many TVs also have **Network debugging** /
     **ADB over network**; turn that on too. ADB then listens on port **5555**.
   - Fire TV: *Developer options* → **ADB debugging** → On (port 5555).
   - Android TV 11+ / Google TV with **Wireless debugging** (no "network debugging" switch): turn on
     *Wireless debugging* and pair once, as below. Its port is random and can change after a TV reboot.

     ```bash
     # On the TV: Wireless debugging → "Pair device with pairing code"
     # it shows IP:PAIRPORT and a 6-digit code
     adb pair 192.168.1.50:41235          # enter the code
     # The Wireless debugging screen shows "IP address & Port", e.g. 192.168.1.50:37123
     ```
     Use that `IP:PORT` with the script (e.g. `bash ~/install-dumbtube.sh 192.168.1.50:37123`).
3. Optional, recommended: if *Verify apps over ADB/USB* exists, turn it off. Some TVs otherwise
   block or slow down ADB installs.

## 3. Find the TV's IP address

- Android TV / Google TV: *Settings → Network & Internet →* your Wi-Fi network → **IP address**
  (or *Settings → System → About → Status*).
- Fire TV: *Settings → My Fire TV → About → Network*.
- Or look at your router's list of connected devices.

Tip: give the TV a **fixed IP (DHCP reservation)** in your router so it never changes.

## 4. First connection (approve the phone on the TV)

```bash
adb connect 192.168.1.50:5555      # your TV's IP (port 5555 unless wireless debugging shows another)
```

The TV shows **"Allow USB/network debugging?"** with your phone's key fingerprint. Tick
**Always allow from this computer** and press **OK**. Check:

```bash
adb devices
# 192.168.1.50:5555   device        <- good
# 192.168.1.50:5555   unauthorized  <- accept the prompt on the TV
```

## 5. Install / update DumbTube

```bash
bash ~/install-dumbtube.sh 192.168.1.50      # first time: the IP is saved
bash ~/install-dumbtube.sh                   # every later update
bash ~/install-dumbtube.sh --launch          # ...and start DumbTube afterwards
```

The TV address and repository are saved in `~/.config/dumbtube/install.conf`. You can edit it, or
pass a new IP to overwrite it. Other options:

| Option | Meaning |
|--------|---------|
| `--repo OWNER/NAME` | your fork if it isn't the default `pringleprng/start` (saved for next time) |
| `--tag v32.80-dt1` | install a specific release instead of the latest |
| `--apk FILE` | install an APK you already have |
| `--keep` | keep the downloaded APK |

Private repository: `export GITHUB_TOKEN=<fine-grained token with "Contents: read" on the repo>` before
running. (The in-app updater can't use a token, so a public repo is recommended.)

One-tap updates: install **Termux:Widget**, then
`mkdir -p ~/.shortcuts && cp ~/install-dumbtube.sh ~/.shortcuts/Update-DumbTube` and add the widget
to your home screen. If it fails with "bad interpreter", run `termux-fix-shebang ~/.shortcuts/Update-DumbTube`.

## Troubleshooting

| Message | What to do |
|---------|------------|
| `TV not reachable` / `No route to host` / `timed out` | TV on and on the same Wi-Fi? IP changed (check step 3)? Phone on mobile data or a guest network? |
| `Connection refused` | Network/ADB debugging is off, or the port is wrong (wireless debugging uses a random port; read it on the TV). |
| `did not authorize this phone` / `unauthorized` | Accept the prompt on the TV. No prompt? Developer options → *Revoke USB debugging authorizations*, then `adb kill-server` in Termux and run again. |
| `Signature mismatch` | The DumbTube on the TV was signed with a different key (e.g. a build from another machine). Updates need the same keystore (see RELEASING.md). To switch: optionally make a backup in DumbTube settings, then `adb uninstall com.dumbtube.tv` (**deletes its settings**) and run the script again. |
| `newer DumbTube` (downgrade) | The TV already has a newer build. Use `adb install -r -d <apk>` if you really want to downgrade. |
| `Not enough free storage` | Free space on the TV (clear app caches / uninstall apps). |
| `has no DumbTube-<version>.apk asset` / `No release found` | No release published yet, or the wrong repo: run the *DumbTube Release* workflow (RELEASING.md), or use `--repo`. |
| `rate limit` | GitHub allows 60 anonymous API calls per hour. Wait, or set `GITHUB_TOKEN`. |

DumbTube installs **next to** official SmartTube (different package `com.dumbtube.tv`). Both can
stay installed.
