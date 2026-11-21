# Updating DumbTube to a new SmartTube release

DumbTube = upstream SmartTube release tag + a stack of `[DumbTube]` commits on top
(see [FIXES.md](FIXES.md)). To update, **rebase that stack onto the new upstream tag**, fix the few
hook lines if they conflict, then build, release and install.

Upstream releases: https://github.com/yuliskov/SmartTube/releases. Stable tags end in `s`
(e.g. `32.80s` = "32.80 Stable"); tags without `s` are betas. DumbTube follows the **stable** tags.

---

## One-time setup

### Where the DumbTube code lives

The DumbTube commits are currently on branch `ccr-556d74fb-n3xrrs` of
`https://github.com/pringleprng/start`. Pick one:

- **A. Use that repository as your DumbTube repo (simplest).** Optionally rename it on GitHub
  (*Settings → General → Repository name*, e.g. `DumbTube`; GitHub redirects the old URLs).
  Make it **public** (needed by the in-app updater) and rename the branch to `dumbtube`
  (*Branches* page, or the commands below). If you rename the repository, update `repo=` in
  `dumbtube.properties` and `DEFAULT_REPO` in `scripts/install-dumbtube.sh` (or pass `--repo` once).
- **B. A real GitHub fork.** Open https://github.com/yuliskov/SmartTube, click **Fork**, untick
  *"Copy the master branch only"* if you want the tags, then push the DumbTube branch into it:

  ```bash
  git clone https://github.com/pringleprng/start dumbtube && cd dumbtube
  git checkout ccr-556d74fb-n3xrrs
  git remote add fork https://github.com/<you>/SmartTube.git
  git push fork ccr-556d74fb-n3xrrs:dumbtube
  ```
  Then edit `repo=` in `dumbtube.properties` and `DEFAULT_REPO` in the install script, and enable
  Actions on the fork (RELEASING.md §4). CI builds point the updater at whichever repo builds them,
  so release APKs are always right. The two values only matter for local builds and the script.

### Local clone with an `upstream` remote

On a PC (or in Termux: `pkg install git openjdk-17`):

```bash
git clone --recurse-submodules https://github.com/<you>/<repo>.git dumbtube
cd dumbtube
git checkout dumbtube                      # or ccr-556d74fb-n3xrrs if you haven't renamed it
git remote add upstream https://github.com/yuliskov/SmartTube.git
git fetch upstream --tags
```

(Renaming the branch: `git branch -m ccr-556d74fb-n3xrrs dumbtube && git push -u origin dumbtube`,
then make `dumbtube` the default branch on GitHub and delete the old one.)

---

## Every upstream release

### 1. Fetch upstream and pick the new tag

```bash
git fetch upstream --tags
git tag -l '*s' --sort=-creatordate | head -5     # newest stable tags, e.g. 32.81s
OLD=32.80s        # the base recorded in FIXES.md ("Base: ...")
NEW=32.81s        # the new stable tag
```

### 2. Rebase the `[DumbTube]` commits onto the new tag

```bash
git checkout dumbtube
git branch backup/dumbtube-$OLD              # safety copy of the current state
git rebase --onto "$NEW" "$OLD" dumbtube     # replays only the DumbTube commits
```

### 3. Resolve conflicts (if any)

Conflicts can only happen in the few upstream files that carry a hook. List them with
`grep -rn "\[DumbTube\]" --include=*.java --include=build.gradle .`:

| File | Hook |
|------|------|
| `smarttubetv/build.gradle` | last line: `apply from: "dumbtube.gradle"` |
| `common/.../misc/AppDataSourceManager.java` | import + `settingItems.add(0, DumbTubeSettingsPresenter...)` |
| `common/.../controllers/VideoStateController.java` | `ChannelCaptions...resolve(...)` before `getPlayer().setFormat(result)` in `restoreSubtitleFormat()` |
| `common/.../controllers/PlayerUIController.java` | 5 `ChannelCaptions...` lines in `onSubtitleClicked()` / `onSubtitleLongClicked()` |
| `common/.../controllers/ErrorFixerController.java` | `ChannelCaptions...suspendFor(...)` in `disableSubtitles()` |
| `common/.../app/models/data/Video.java` | first line of `isSectionPlaylistEnabled()` |
| `common/.../misc/MotherActivity.java` | `TextDimmer.attach(this)` + `OledNeonTheme.attach(this)` in `onResume()` |
| `common/.../exoplayer/other/SubtitleManager.java` | `TextDimmer.dimCaptionStyle(...)` before both `mSubtitleView.setStyle(style)` |
| `common/.../prefs/MainUIData.java` | one line at the top of `getColorSchemes()`, `getColorScheme()`, `setColorScheme()` |
| `.gitignore` | 4 lines at the end |

For each conflict: **take upstream's version of the code, then re-add the one `// [DumbTube]` line**
at the equivalent place. Hooks never replace upstream lines; they're only added. Then:

```bash
git add <file>
git rebase --continue
```

If upstream moved or renamed a hooked method, find its new equivalent and put the hook there. If you
get stuck: `git rebase --abort` returns everything to how it was.

After the rebase, update the submodules (upstream bumps them on almost every release):

```bash
git submodule update --init --recursive
```

### 4. Check that every hook survived

```bash
grep -rn "\[DumbTube\]" --include=*.java --include=build.gradle . | grep -v "/dumbtube/\|/build/" | wc -l
# expected: 18  (PlayerUIController 5, MainUIData 3, AppDataSourceManager 2, MotherActivity 2,
#                SubtitleManager 2, VideoStateController 1, ErrorFixerController 1, Video 1, build.gradle 1)
git diff --stat "$NEW" HEAD -- $(git diff --name-only "$NEW" HEAD | grep -vi dumbtube)
# expected: only the files from the table above, only added lines
```

### 5. Check FIXES.md: has upstream fixed anything natively?

For each section in FIXES.md, read **"Drop it when"** and check the new upstream code and release
notes. If a feature is now in upstream:

```bash
git log --oneline --grep='^\[DumbTube\]'       # find the commit
git revert <commit>                            # or drop it with an interactive rebase
```

and remove its section from FIXES.md (plus its line in `DumbTubeSettingsPresenter.show()`).
Update **Base** and the **"Last applied to"** column in FIXES.md to `$NEW`, and commit:

```bash
git commit -am "[DumbTube] FIXES.md: applied to $NEW"
```

### 6. Build (optional local check)

```bash
./gradlew :smarttubetv:assembleStdumbtubeDebug       # needs JDK 17 + Android SDK
```

Or just push. The **DumbTube Check** workflow builds and runs the DumbTube unit tests on every push.

### 7. Push

A rebase rewrites the branch, so force-push (with lease, so you never overwrite something you
haven't seen):

```bash
git push --force-with-lease origin dumbtube
```

### 8. Release

GitHub → **Actions → DumbTube Release → Run workflow** (branch `dumbtube`, revision empty).
The new release is e.g. `v32.81-dt1`: the revision restarts at 1 and versionCode is
`<new upstream code> × 100 + 1`, higher than any 32.80 build. Details and troubleshooting: RELEASING.md.

### 9. Install on the TV

On the phone, in Termux:

```bash
bash ~/install-dumbtube.sh
```

or let the in-app updater find it (DumbTube › Settings › About › *Check for updates*). See TERMUX.md.

### 10. Clean up

When the new build works, delete the safety branch: `git branch -D backup/dumbtube-$OLD`.

---

## Releasing a DumbTube-only fix (no upstream change)

Commit it as a new `[DumbTube] ...` commit, add or update its FIXES.md entry, push, and run the
release workflow. The revision goes up (`dt1` → `dt2`) and so does versionCode.
