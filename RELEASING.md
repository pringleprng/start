# Releasing DumbTube (signing key, GitHub Secrets, release workflow)

Releases are built by GitHub Actions (`.github/workflows/dumbtube-release.yml`). The workflow
signs the APK with **your** keystore, which it reads from GitHub Secrets, then publishes a GitHub
Release with:

| Asset | Purpose |
|-------|---------|
| `DumbTube-<version>.apk` | universal APK (armeabi-v7a + arm64-v8a), e.g. `DumbTube-32.80-dt1.apk` |
| `DumbTube-<version>.apk.sha256` | checksum |
| `dumbtube.json` | manifest read by the in-app update checker |

Versions: `versionName = <SmartTube version>-dt<revision>` and
`versionCode = <SmartTube versionCode> × 100 + revision` (e.g. `32.80-dt1` → `247001`).
Every new release has a higher versionCode, so the in-app updater offers it and
`adb install -r` accepts it. The workflow refuses to publish a release that isn't newer.

> ⚠️ **Keep the same keystore forever.** Android only installs an update over an app signed with
> the same key. If you lose the keystore or its password, you can never update DumbTube again. You
> would have to uninstall it, which deletes its settings, and install a build signed with a new key.
> Keep 2 copies, e.g. a password manager and an offline USB stick.
> **Never commit the keystore or passwords.** `.gitignore` already ignores `*.jks`, `*.keystore`
> and `keystore.properties`.

---

## 1. Generate the keystore (once)

You need `keytool`, which comes with any Java JDK.

- **On your phone (Termux):** `pkg install openjdk-17`
- **On a PC:** install a JDK (e.g. Temurin 17); `keytool` is in its `bin/` folder.

```bash
keytool -genkeypair -v \
  -keystore dumbtube-release.jks \
  -storetype PKCS12 \
  -alias dumbtube \
  -keyalg RSA -keysize 4096 \
  -validity 36500
```

- Choose a strong password. Use letters, digits and `-_.` only; that avoids quoting problems.
- With `PKCS12` the **key password is the same as the keystore password**. If keytool asks for a
  separate key password, use the same one.
- The name/organisation questions can be anything (e.g. just your first name). Answer `yes` at the end.

Check it:

```bash
keytool -list -v -keystore dumbtube-release.jks -alias dumbtube
```

Note the **SHA-256 fingerprint**. Each release's notes show the certificate SHA-256 they were
signed with, so you can compare.

## 2. Turn the keystore into text (base64)

```bash
# Linux / Termux
base64 -w0 dumbtube-release.jks > dumbtube-release.jks.b64
# macOS
base64 -i dumbtube-release.jks -o dumbtube-release.jks.b64
# Windows (PowerShell)
[Convert]::ToBase64String([IO.File]::ReadAllBytes("dumbtube-release.jks")) | Out-File -Encoding ascii dumbtube-release.jks.b64
```

## 3. Add the 4 secrets to your GitHub repository

On github.com, open your DumbTube repository and go to **Settings → Secrets and variables → Actions
→ New repository secret**. Add:

| Name | Value |
|------|-------|
| `DUMBTUBE_KEYSTORE_BASE64` | the whole content of `dumbtube-release.jks.b64` (one long line) |
| `DUMBTUBE_KEYSTORE_PASSWORD` | the keystore password |
| `DUMBTUBE_KEY_ALIAS` | `dumbtube` (the `-alias` you used) |
| `DUMBTUBE_KEY_PASSWORD` | the key password (same as the keystore password for PKCS12) |

Copying a long base64 string on a phone is fiddly. In Termux you can use the GitHub CLI instead:

```bash
pkg install gh
gh auth login                                   # once
cd <folder with the files>
gh secret set DUMBTUBE_KEYSTORE_BASE64 -R OWNER/REPO < dumbtube-release.jks.b64
gh secret set DUMBTUBE_KEYSTORE_PASSWORD -R OWNER/REPO   # prompts for the value
gh secret set DUMBTUBE_KEY_ALIAS -R OWNER/REPO --body dumbtube
gh secret set DUMBTUBE_KEY_PASSWORD -R OWNER/REPO        # prompts for the value
```

Then delete the `.b64` file (`rm dumbtube-release.jks.b64`) and move `dumbtube-release.jks` into
your backups. It never needs to be inside the repository folder.

## 4. One-time GitHub settings

1. **Make the repository public.** The in-app update checker downloads `dumbtube.json` and the APK
   without logging in, so it can't read releases of a private repository. (The Termux script can
   with a token, see TERMUX.md, but the in-app updater can't.)
2. **Enable Actions.** On a GitHub *fork*, open the **Actions** tab and click *"I understand my
   workflows, go ahead and enable them"*.
3. **Switch off upstream's workflows** (they build SmartTube, not DumbTube). In the **Actions** tab,
   open each of these, click **⋯ → Disable workflow**, and leave the files in the repo (that avoids
   merge conflicts):
   - *Build Debug APK* (`CI.yml`)
   - *VirusTotal Scan* (`virustotal_scan.yml`): it runs on every published release and fails without
     a VirusTotal key
   - *Cleanup old workflow runs* (`cleanup.yml`)
   - *Close stale issues* (`stale.yml`)
4. Settings → Actions → General → **Workflow permissions**: the release workflow asks for
   `contents: write` itself, so the default is fine. If your account/org forces read-only, set
   *Read and write permissions*.

## 5. Make a release

1. Push your DumbTube branch (see UPDATING.md).
2. **Actions → DumbTube Release → Run workflow**, choose your DumbTube branch, leave *revision*
   empty and click *Run workflow*.
   - *revision* empty → the next free one for this SmartTube version (`dt1`, `dt2`, …). Starts again
     at `dt1` when you move to a new SmartTube version; its versionCode is higher anyway.
   - *notes* → an optional line for the release notes and the in-app changelog.
3. After about 10 minutes the release appears under **Releases** as *Latest*. Then:
   - on the TV: DumbTube › Settings › About › *Check for updates*, or wait for the automatic check
   - or from Termux: `bash install-dumbtube.sh` (see TERMUX.md)

If the workflow fails:
- *Missing repository secrets* / *secrets don't match*: re-check step 3; alias and passwords are
  case-sensitive.
- *Tag … already exists* / *not higher than the latest release*: someone (you) already released that
  revision; leave *revision* empty.
- *APK is debug-signed*: the keystore wasn't picked up; check the secrets.

## Local signed build (optional)

Create `keystore.properties` in the repository root. It is ignored by git; never commit it.

```properties
storeFile=/absolute/path/to/dumbtube-release.jks
storePassword=...
keyAlias=dumbtube
keyPassword=...
```

```bash
./gradlew :smarttubetv:assembleStdumbtubeRelease -PdumbtubeRevision=1
# -> smarttubetv/build/outputs/apk/stdumbtube/release/DumbTube-32.80-dt1.apk
```

Don't add tasks with `Ststable`/`Stbeta` in their name to the same Gradle command. Upstream's
`build.gradle` then applies the Google Services plugin, which fails for `com.dumbtube.tv`.
