# DumbTube changes (FIXES.md)

DumbTube is a personal fork of [SmartTube](https://github.com/yuliskov/SmartTube) by yuliskov.
This file lists every DumbTube change on top of upstream. Each change is one commit whose subject
starts with `[DumbTube]`, so it can be rebased, inspected or dropped on its own:

```bash
git log --oneline --grep='^\[DumbTube\]'          # all DumbTube commits
grep -rn "\[DumbTube\]" --include=*.java .         # every hook inside upstream files
```

**Base:** all changes were last applied to upstream release **32.80s** ("32.80 Stable",
upstream commit `41fbc7c60`, versionCode 2470). Update the "Last applied to" column after each
upstream merge (see [UPDATING.md](UPDATING.md)).

Most code lives in new files: `common/.../common/dumbtube/*` (Java),
`dumbtube_*.xml` resources, `smarttubetv/dumbtube.gradle` and `smarttubetv/src/stdumbtube/`.
Upstream files only get short hooks. Each hook is one line ending in `// [DumbTube]` and uses the
fully qualified class name, so no import lines change.

| # | Change | Last applied to |
|---|--------|-----------------|
| 1 | [Rebrand + fork updater](#1-rebrand-to-dumbtube--fork-update-checker) | 32.80s |
| 2 | [Settings tile + prefs store](#2-dumbtube-settings-tile-and-prefs-store-infrastructure) (infrastructure) | 32.80s |
| 3 | [Per-channel captions / auto-translate](#3-per-channel-captions-and-auto-translate) | 32.80s |
| 4 | [Subscriptions feed autoplay order](#4-subscriptions-feed-autoplay-order) | 32.80s |
| 5 | [Text brightness + caption brightness](#5-text-brightness-and-caption-brightness) | 32.80s |
| 6 | [OLED theme (default), focus/accent colors](#6-oled-theme-default-with-focus-and-accent-colors) | 32.80s |
| 7 | [Release CI, Termux installer, docs](#7-release-ci-termux-installer-docs) | 32.80s |

---

## 1. Rebrand to DumbTube + fork update checker

**Commit:** `[DumbTube] Rebrand: stdumbtube flavor, com.dumbtube.tv, fork updater`

**What it does**
- Adds a separate product flavor, `stdumbtube`, with applicationId `com.dumbtube.tv` and the app
  name "DumbTube", so it installs next to official SmartTube (`org.smarttube.*`) without conflicts.
  The global-search content provider and `searchable.xml` use `com.dumbtube.tv` as their authority.
- Sets the version to versionCode = upstream versionCode × 100 + DumbTube revision. The versionName
  is `<upstream>-dt<revision>` (e.g. `32.80-dt1` → 247001). The APK is named `DumbTube-<versionName>.apk`.
- Points the built-in update checker at
  `https://github.com/<repo>/releases/latest/download/dumbtube.json` (the manifest the release
  workflow attaches). `<repo>` comes from `GITHUB_REPOSITORY` in CI, or from `dumbtube.properties`
  for local builds.
- Adds its own launcher icon and banner (neon TV outline with a "D") to tell the two apps apart.
- Library modules reuse their `ststable` variants (`matchingFallbacks`).

**Files**
- `smarttubetv/build.gradle`: **1 hook line at the very end** (`apply from: "dumbtube.gradle"`)
- new: `smarttubetv/dumbtube.gradle`, `dumbtube.properties`
- new: `smarttubetv/src/stdumbtube/res/` (`values/strings.xml`, `values/update_urls.xml`,
  `xml/searchable.xml`, `mipmap-*/app_*.png`)

**Drop it when:** never. This is what makes the fork a separate app. Re-check after merges:
- upstream renamed or added flavors (`productFlavors` in `smarttubetv/build.gradle`, library modules'
  `stbeta/ststable/stfdroid`) → adjust `matchingFallbacks`
- new provider authorities or `org.smarttube` strings in `leanbackassistant/src/ststable` → mirror
  them in `smarttubetv/src/stdumbtube/res`
- the update checker's JSON format (`SharedModules/appupdatechecker2/.../AppVersionChecker.java`) →
  keep the workflow's `dumbtube.json` in sync

## 2. DumbTube settings tile and prefs store (infrastructure)

**Commit:** `[DumbTube] Add DumbTube settings tile and prefs store`

**What it does:** adds a **DumbTube** tile as the first item in Settings. Every feature below puts
its options there. `DumbTubePrefs` is a small cached key/value store on top of SmartTube's `AppPrefs`
profile data, so DumbTube settings follow the account profile and are included in SmartTube's
built-in backup/restore.

**Files**
- `common/.../misc/AppDataSourceManager.java`: 1 import + 1 hook line (`settingItems.add(0, ...)`)
- new: `common/.../dumbtube/DumbTubePrefs.java`, `DumbTubeSettingsPresenter.java`,
  `common/src/main/res/values/dumbtube_strings.xml`, `drawable-nodpi/dumbtube_settings.png`

**Drop it when:** all features that use it are gone.

## 3. Per-channel captions and auto-translate

**Commit:** `[DumbTube] Per-channel captions and auto-translate`

**What it does**
- Remembers per channel whether captions are on or off, plus the caption track picked for it. A normal
  track gives the **caption language** (e.g. `English`). One of SmartTube's auto/translated tracks
  (marked `*`, e.g. `German*`) gives the **auto-translate target language**.
- When a video starts, the channel's saved captions are applied. Channels with nothing saved use the
  **DumbTube default**. It starts as SmartTube's own global subtitle setting, normally Off.
- Any caption change during playback (CC button toggle or CC dialog) updates that channel's saved
  settings. The CC toggle prefers the channel's saved track.
- The CC dialog (long-press CC) adds: an enable switch, "Forget captions for <channel>", and "Use
  current captions as default for other channels".
- Settings › DumbTube adds: an enable switch, the default captions (Off or recently used tracks), and
  "Forget all".
- If SmartTube's error fixer has to switch subtitles off (HTTP 429/500 subtitle errors), the channel
  setting is skipped for that one video, so playback can't get stuck in a loop.
- Storage: own `AppPrefs` keys (`dumbtube_channel_captions_*`). Up to 2000 channels are kept, oldest
  dropped first. Upstream's `PlayerData` subtitle settings are not changed.

**Why not reuse upstream's per-channel storage?** SmartTube only keeps a list of channel IDs with
subtitles on (`PlayerData.mEnabledSubtitlesPerChannel`). It has no language. Adding fields to
`PlayerData`'s positional storage string would conflict with every upstream change to it. DumbTube
reuses SmartTube's prefs storage (`AppPrefs`) and its subtitle matching (`FormatItem` /
`SubtitleTrack`) instead.

**Files** (all hooks are single lines)
- `common/.../playback/controllers/VideoStateController.java`: `restoreSubtitleFormat()` → `ChannelCaptions.resolve(...)`
- `common/.../playback/controllers/PlayerUIController.java`: CC toggle (`preferSaved`,
  `onUserSelected`), the two CC dialog lists (`onUserSelected`), dialog options (`appendPlayerOptions`)
- `common/.../playback/controllers/ErrorFixerController.java`: `disableSubtitles()` → `suspendFor(...)`
- new: `common/.../dumbtube/ChannelCaptions.java`, strings in `dumbtube_strings.xml`

**Not covered:** subtitle changes sent from the phone (casting/remote control) aren't saved.
Upstream doesn't persist those either.

**Drop it when:** upstream saves a subtitle **language** per channel, not just on/off. Check
`PlayerData` for a per-channel subtitle format map, and whether `VideoStateController.restoreSubtitleFormat()`
reads a per-channel format instead of `getLastSubtitleFormat()`.

## 4. Subscriptions feed autoplay order

**Commit:** `[DumbTube] Subscriptions feed autoplays in feed order`

**What it does:** when a video started from the **Subscriptions** feed ends, the next video in the
feed plays (newest → second newest → …), wherever you started. More of the feed is loaded when the
loaded part runs out. Under the hood it turns on SmartTube's own "section as playlist" logic
(`SuggestionsController.findNextSectionVideo` / `getNext`) **only** for videos whose group is the
Subscriptions feed. Every other section still follows the global *Player › section playlist* tweak,
so they behave as before. Videos casted from a phone are excluded. Switch: Settings › DumbTube
(on by default).

**Notes:** your playback mode still decides whether anything autoplays at all. Autoplay must be on
("play all"); the modes "pause/close after video" stop as before. Queue items (Playlist queue) still
come first. Upcoming/premiere items are skipped (upstream logic). After the very last video of the
feed, playback falls back to upstream behaviour (recommendation).

**Files**
- `common/.../app/models/data/Video.java`: first line of `isSectionPlaylistEnabled()` (1 hook)
- new: `common/.../dumbtube/SubscriptionsAutoplay.java`, string in `dumbtube_strings.xml`

**Drop it when:** upstream gets a per-section "continue with the next video of this section"
setting, or makes the section playlist the default for Subscriptions. Check `Video.isSectionPlaylistEnabled()`
and `PlayerTweaksData`.

## 5. Text brightness and caption brightness

**Commit:** `[DumbTube] Text brightness (dim all UI text) and caption brightness`

**What it does**
- Settings › DumbTube › **Text brightness**: 100 % down to 30 % in 10 % steps. Dims **all interface
  text**: browse/menus, card titles and descriptions, settings and other dialogs, and the player overlay
  (title, description, times). Each activity window gets a pre-draw listener that re-tints every
  `TextView` with a wrapped `ColorStateList`. RGB is scaled; alpha and focus/selected states are kept.
  It needs no per-screen changes and picks up colors that screens set later (e.g. focused cards).
- Settings › DumbTube › **Caption brightness**: same steps, applied to the subtitle text color of
  both SmartTube's caption styles and the system caption style.

**Not covered:** toasts, the player tooltip popup, and colored spans inside text (e.g. some badges).

**Files**
- `common/.../misc/MotherActivity.java`: `onResume()` → `TextDimmer.attach(this)` (1 hook)
- `common/.../exoplayer/other/SubtitleManager.java`: `applyStyle()` / `applySystemStyle()` →
  `TextDimmer.dimCaptionStyle(...)` (1 hook each)
- new: `common/.../dumbtube/TextDimmer.java`, `common/src/main/res/values/dumbtube_ids.xml`,
  test `common/src/test/.../dumbtube/TextDimmerTest.java`

**Drop it when:** upstream adds a UI text brightness/opacity setting. Check `MainUIData` /
`MainUISettingsPresenter`. Caption brightness can go when SmartTube's subtitle styles offer a
text opacity/brightness option (`AppDialogUtil.createSubtitleStylesCategory`, `SubtitleManager`).

## 6. OLED theme (default) with focus and accent colors

**Commits:** `[DumbTube] OLED (neon green) theme, selected by default` and
`[DumbTube] OLED theme: grey focus, choosable focus and accent colors`

**What it does**
- New color scheme **"OLED - DumbTube"**, listed first in Settings › Main UI › color scheme and
  active by default.
- Pure black `#000000`: window, browse rows, sidebar/headers, cards, settings and dialogs, and the
  player window. The app starts on a black window (flavor manifest), so there's no grey flash on launch.
- **Focus color** (default *light grey* `#BDBDBD`) is the background of the focused card or tile:
  video and channel cards, Settings tiles, and search tags. The text on it switches between dark and
  light automatically for contrast.
- **Accent color** (default *neon green* `#39FF14`) covers only the small accents: seek bar (buffered
  part in a darker shade), focused player icons, switches and radio buttons, card progress bars, and
  the search orb.
- Both are picked in **Settings › DumbTube** from a 19-color palette: greys, neon green and the usual
  colors. Restart the app after changing them.
- Opaque dark-grey panels that come from fixed library colors (e.g. the settings dialog list,
  `#202124`) are painted black at runtime while this theme is active. Your focus color is never
  painted over. The player's translucent gradients stay as they are.
- Text is kept off-white (white → `#E6E6E6`) through the text dimmer, on top of your text brightness.
- The theme selection is stored by DumbTube, not as an index into SmartTube's scheme list, so
  upstream adding schemes never changes your theme. Picking any other scheme switches the DumbTube
  theme off.

**How the colors are applied:** the accent is a theme overlay (`ThemeOverlay.DumbTube.Accent.<color>`
in `dumbtube_palette.xml`) applied right after the activity theme. The focus color is set at runtime
in the card presenters. Without the latter, Settings tiles and search tags would stay hard-coded white
and the focused text would stay hard-coded dark grey. To add a color, add it to `OledNeonTheme.PALETTE`
and add the matching `<color>`s and overlay `<style>` to `dumbtube_palette.xml`; both must use the same key.

**Files**
- `common/.../prefs/MainUIData.java`: `getColorSchemes()`, `getColorScheme()`, `setColorScheme()`
  (1 hook line each)
- `common/.../misc/MotherActivity.java`: `onCreate()` → `OledNeonTheme.applyColors(this)` and
  `onResume()` → `OledNeonTheme.attach(this)` (1 hook each)
- `smarttubetv/.../presenter/VideoCardPresenter.java`, `ChannelCardPresenter.java`,
  `SettingsCardPresenter.java`, `presenter/vineyard/TagPresenter.java`: 2 hook lines each
  (`focusBackground` / `focusText`) after the selected colors are set
- new: `common/.../dumbtube/OledNeonTheme.java`, `smarttubetv/src/main/res/values/dumbtube_styles.xml`,
  `dumbtube_colors.xml`, `dumbtube_palette.xml`, `drawable/dumbtube_progress_bar.xml`,
  `smarttubetv/src/stdumbtube/AndroidManifest.xml`, test `common/src/test/.../dumbtube/OledNeonThemeTest.java`
- `common/.../dumbtube/TextDimmer.java` (off-white cap)

**Drop it when:** upstream ships a pure-black theme with configurable accent/focus colors. Compare
upstream's OLED schemes in `MainUIData.initColorSchemes()` and `smarttubetv/src/main/res/values/styles.xml`.
Drop just the runtime panel painting if upstream's dialog/list layouts start using theme colors
instead of `lb_preference_decor_list_background`.

## 7. Release CI, Termux installer, docs

**Commit:** `[DumbTube] Release workflow, Termux installer and docs`

**What it does**
- `.github/workflows/dumbtube-release.yml`: manually started. It builds a signed release APK with the
  keystore from GitHub Secrets, verifies it, and publishes a GitHub Release `v<version>` with
  `DumbTube-<version>.apk`, a `.sha256` file and `dumbtube.json` (the in-app updater manifest).
- `.github/workflows/dumbtube-check.yml`: compile check and DumbTube unit tests on every push.
- `scripts/install-dumbtube.sh`: Termux installer (download latest release → `adb connect` →
  `adb install -r`).
- Docs: `FIXES.md` (this file), `RELEASING.md`, `TERMUX.md`, `UPDATING.md`.
- `.gitignore`: `keystore.properties`, `*.jks`, `*.keystore` (upstream doesn't ignore them).

**Files:** only new files, plus 4 lines at the end of `.gitignore`. Upstream's own workflows are left
untouched. Switch them off in the Actions tab (see RELEASING.md).

**Drop it when:** never (fork tooling).
