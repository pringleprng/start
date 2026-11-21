#!/usr/bin/env bash
# [DumbTube] Download the latest DumbTube APK from GitHub Releases and install it on an
# Android TV over ADB (Wi-Fi). Made for Termux, works on any Linux/macOS with bash + curl + adb.
#
#   bash install-dumbtube.sh 192.168.1.50           # first run: TV IP is saved for next time
#   bash install-dumbtube.sh                        # later runs: uses the saved IP
#   bash install-dumbtube.sh 192.168.1.50:37123     # custom ADB port (Android 11+ wireless debugging)
#
# Options:
#   --repo OWNER/NAME   GitHub repo with the DumbTube releases (saved to the config)
#   --apk FILE          install a local APK instead of downloading
#   --tag TAG           install a specific release (e.g. v32.80-dt1) instead of the latest
#   --launch            start DumbTube on the TV after installing
#   --keep              keep the downloaded APK
#   -h, --help          this help
#
# Config file: ${XDG_CONFIG_HOME:-~/.config}/dumbtube/install.conf  (TV=..., REPO=...)
# Private repo? export GITHUB_TOKEN=<token with read access to the repo> before running.
# Needs: bash, curl, adb (Termux: pkg install curl android-tools). jq is used if present.

set -u
set -o pipefail

PACKAGE="com.dumbtube.tv"
DEFAULT_REPO="pringleprng/start"   # change if your fork lives elsewhere (or use --repo once)
DEFAULT_PORT=5555
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dumbtube"
CONFIG_FILE="$CONFIG_DIR/install.conf"

# ---------- output helpers ----------
if [ -t 1 ]; then
    C_RED=$'\e[31m'; C_GREEN=$'\e[32m'; C_YELLOW=$'\e[33m'; C_BOLD=$'\e[1m'; C_RESET=$'\e[0m'
else
    C_RED=""; C_GREEN=""; C_YELLOW=""; C_BOLD=""; C_RESET=""
fi
info()  { printf '%s==>%s %s\n' "$C_BOLD" "$C_RESET" "$*"; }
ok()    { printf '%s✔%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn()  { printf '%s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()   { local code="$1"; shift; printf '%sERROR:%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit "$code"; }
usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; }

# ---------- arguments ----------
TV_ARG=""; REPO_ARG=""; LOCAL_APK=""; TAG=""; LAUNCH=0; KEEP=0
while [ $# -gt 0 ]; do
    case "$1" in
        --repo)   [ $# -ge 2 ] || die 2 "--repo needs OWNER/NAME"; REPO_ARG="$2"; shift ;;
        --apk)    [ $# -ge 2 ] || die 2 "--apk needs a file"; LOCAL_APK="$2"; shift ;;
        --tag)    [ $# -ge 2 ] || die 2 "--tag needs a tag name"; TAG="$2"; shift ;;
        --launch) LAUNCH=1 ;;
        --keep)   KEEP=1 ;;
        -h|--help) usage; exit 0 ;;
        -*)       die 2 "Unknown option: $1 (see --help)" ;;
        *)        [ -z "$TV_ARG" ] || die 2 "Only one TV address expected"; TV_ARG="$1" ;;
    esac
    shift
done

# ---------- config ----------
TV=""; REPO=""
if [ -f "$CONFIG_FILE" ]; then
    # shellcheck disable=SC1090
    TV=$(sed -n 's/^TV=//p' "$CONFIG_FILE" | tail -1)
    REPO=$(sed -n 's/^REPO=//p' "$CONFIG_FILE" | tail -1)
fi
TV="${TV_ARG:-${DUMBTUBE_TV:-$TV}}"
REPO="${REPO_ARG:-${DUMBTUBE_REPO:-${REPO:-$DEFAULT_REPO}}}"

[ -n "$TV" ] || { usage; echo; die 2 "No TV address. Run: bash $0 <TV_IP>   (see TERMUX.md to find the IP)"; }
case "$TV" in *:*) ;; *) TV="$TV:$DEFAULT_PORT" ;; esac
[[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die 2 "Bad repo '$REPO', expected OWNER/NAME"

if [ -n "$TV_ARG" ] || [ -n "$REPO_ARG" ]; then
    mkdir -p "$CONFIG_DIR" && printf 'TV=%s\nREPO=%s\n' "$TV" "$REPO" > "$CONFIG_FILE" \
        && info "Saved TV=$TV, REPO=$REPO to $CONFIG_FILE"
fi

# ---------- dependencies ----------
need() { command -v "$1" >/dev/null 2>&1 || die 3 "'$1' not found. $2"; }
need curl "Termux: pkg install curl"
need adb  "Termux: pkg install android-tools"
HAVE_JQ=0; command -v jq >/dev/null 2>&1 && HAVE_JQ=1

TMP_DIR="${TMPDIR:-${PREFIX:-}/tmp}"; [ -d "$TMP_DIR" ] || TMP_DIR="/tmp"
WORK_DIR=$(mktemp -d "$TMP_DIR/dumbtube.XXXXXX") || die 3 "Cannot create a temp dir in $TMP_DIR"
# shellcheck disable=SC2329 # called by the EXIT trap
cleanup() { if [ "$KEEP" -eq 0 ]; then rm -rf "$WORK_DIR"; fi; }
trap cleanup EXIT

CURL_AUTH=()
[ -n "${GITHUB_TOKEN:-}" ] && CURL_AUTH=(-H "Authorization: Bearer $GITHUB_TOKEN")

# ---------- find the APK ----------
APK=""
if [ -n "$LOCAL_APK" ]; then
    [ -f "$LOCAL_APK" ] || die 4 "APK not found: $LOCAL_APK"
    APK="$LOCAL_APK"
    info "Using local APK $APK"
else
    if [ -n "$TAG" ]; then api="https://api.github.com/repos/$REPO/releases/tags/$TAG"
    else api="https://api.github.com/repos/$REPO/releases/latest"; fi
    info "Looking up ${TAG:-the latest} DumbTube release of $REPO ..."
    http=$(curl -sS -L -o "$WORK_DIR/release.json" -w '%{http_code}' \
        -H "Accept: application/vnd.github+json" "${CURL_AUTH[@]}" "$api") \
        || die 4 "Cannot reach api.github.com. Check the phone's internet connection."
    case "$http" in
        200) ;;
        404) die 4 "No release found at $REPO${TAG:+ (tag $TAG)}. Wrong repo? Private repo (set GITHUB_TOKEN)? No release published yet (see RELEASING.md)?" ;;
        401|403) die 4 "GitHub refused the request (HTTP $http): rate limit or bad GITHUB_TOKEN. Try again later or set GITHUB_TOKEN." ;;
        *) die 4 "GitHub API returned HTTP $http" ;;
    esac

    # Universal APK: DumbTube-<version>.apk (per-ABI files, if any, have an extra -<abi> suffix)
    if [ "$HAVE_JQ" -eq 1 ]; then
        TAG_NAME=$(jq -r '.tag_name // empty' "$WORK_DIR/release.json")
        line=$(jq -r '.assets[] | select(.name | test("^DumbTube-[0-9][^/]*-dt[0-9]+\\.apk$")) | "\(.name) \(.url) \(.browser_download_url)"' "$WORK_DIR/release.json" | head -1)
    else
        compact=$(tr -d '\n' < "$WORK_DIR/release.json")
        TAG_NAME=$(printf '%s' "$compact" | grep -o '"tag_name": *"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
        # assets: take name/url/browser_download_url of the matching asset object
        line=$(printf '%s' "$compact" | grep -o '{[^{}]*"name": *"DumbTube-[0-9][^"]*-dt[0-9]*\.apk"[^{}]*}' | head -1 \
            | sed -E 's/.*"url": *"([^"]*)".*"name": *"([^"]*)".*"browser_download_url": *"([^"]*)".*/\2 \1 \3/')
    fi
    [ -n "$line" ] && [ "${line#* }" != "$line" ] || die 4 "Release ${TAG_NAME:-?} has no DumbTube-<version>.apk asset."
    APK_NAME=${line%% *}; rest=${line#* }; API_URL=${rest%% *}; DL_URL=${rest#* }
    APK="$WORK_DIR/$APK_NAME"

    info "Downloading $APK_NAME (release ${TAG_NAME:-?}) ..."
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        curl -fL --retry 3 --progress-bar -H "Accept: application/octet-stream" "${CURL_AUTH[@]}" -o "$APK" "$API_URL"
    else
        curl -fL --retry 3 --progress-bar -o "$APK" "$DL_URL"
    fi || die 4 "Download failed."

    size=$(wc -c < "$APK" | tr -d ' ')
    [ "${size:-0}" -gt 1000000 ] || die 4 "Downloaded file is too small ($size bytes), not an APK."
    head -c 2 "$APK" | grep -q "PK" || die 4 "Downloaded file is not an APK (zip) file."
    ok "Downloaded $(( size / 1024 / 1024 )) MB"
fi

# ---------- connect to the TV ----------
info "Connecting to the TV at $TV ..."
adb start-server >/dev/null 2>&1 || true
out=$(adb connect "$TV" 2>&1); rc=$?
case "$out" in
    *"connected to"*|*"already connected"*) ;;
    *"failed to authenticate"*) warn "Approve the 'Allow USB/network debugging?' prompt on the TV (tick 'Always allow')." ;;
    *"refused"*)
        die 5 "Connection refused by $TV. On the TV: enable Developer options > Network/ADB debugging (or Wireless debugging) and check the port. See TERMUX.md." ;;
    *"No route"*|*"unreachable"*|*"timed out"*|*"Timeout"*|*"cannot connect"*|*"failed to connect"*)
        die 5 "TV not reachable at $TV ($out). Is the TV on and on the same Wi-Fi? Did its IP change? Run again with the new IP." ;;
    *)
        [ $rc -eq 0 ] || die 5 "adb connect failed: $out" ;;
esac

# Wait until the TV accepted this phone (prompt on the TV)
state=""
for i in $(seq 1 30); do
    state=$(adb -s "$TV" get-state 2>&1 | tr -d '\r')
    case "$state" in
        device) break ;;
        *unauthorized*)
            [ "$i" -eq 1 ] && warn "Waiting for you to accept the debugging prompt on the TV (30 s) ..." ;;
        *offline*)
            [ "$i" -eq 5 ] && { adb disconnect "$TV" >/dev/null 2>&1; adb connect "$TV" >/dev/null 2>&1; } ;;
    esac
    sleep 1
done
case "$state" in
    device) ok "Connected to $(adb -s "$TV" shell getprop ro.product.model 2>/dev/null | tr -d '\r') ($TV)" ;;
    *unauthorized*) die 6 "The TV did not authorize this phone. Accept the prompt on the TV and run the script again. If no prompt shows: TV Developer options > 'Revoke debugging authorizations', then retry." ;;
    *) die 6 "TV is not ready (state: ${state:-unknown}). Try: adb disconnect; then run again. Reboot the TV if it persists." ;;
esac

installed=$(adb -s "$TV" shell dumpsys package "$PACKAGE" 2>/dev/null | tr -d '\r' | sed -n 's/^ *versionName=//p' | head -1)
if [ -n "$installed" ]; then info "Installed on TV: DumbTube $installed"; else info "DumbTube is not installed on the TV yet."; fi

# ---------- install ----------
info "Installing (adb install -r keeps your DumbTube settings) ..."
result=$(adb -s "$TV" install -r "$APK" 2>&1 | tr -d '\r'); rc=$?
if [ $rc -eq 0 ] && printf '%s' "$result" | grep -q "Success"; then
    new=$(adb -s "$TV" shell dumpsys package "$PACKAGE" 2>/dev/null | tr -d '\r' | sed -n 's/^ *versionName=//p' | head -1)
    ok "DumbTube ${new:-?} installed."
else
    printf '%s\n' "$result" >&2
    case "$result" in
        *INSTALL_FAILED_UPDATE_INCOMPATIBLE*|*"signatures do not match"*|*INCONSISTENT_CERTIFICATES*)
            die 7 "Signature mismatch: the DumbTube on the TV was signed with a different key.
   Updates only install over a build signed with the SAME keystore (see RELEASING.md).
   To switch keys you must uninstall first, which DELETES DumbTube's settings on the TV:
       (optional) DumbTube > Settings > Backup to save settings first
       adb -s $TV uninstall $PACKAGE
   then run this script again." ;;
        *INSTALL_FAILED_VERSION_DOWNGRADE*)
            die 7 "The TV already has a newer DumbTube ($installed). To downgrade anyway: adb -s $TV install -r -d \"$APK\" (use --keep to keep the file)." ;;
        *INSTALL_FAILED_INSUFFICIENT_STORAGE*|*"not enough space"*)
            die 7 "Not enough free storage on the TV. Clear some app caches/apps and retry." ;;
        *INSTALL_FAILED_NO_MATCHING_ABIS*)
            die 7 "This APK has no native code for the TV's CPU (only armeabi-v7a/arm64-v8a are included)." ;;
        *INSTALL_PARSE_FAILED*|*INSTALL_FAILED_INVALID_APK*)
            die 7 "The APK is damaged or incomplete. Run the script again to re-download." ;;
        *INSTALL_FAILED_OLDER_SDK*)
            die 7 "The TV's Android version is too old for this build." ;;
        *INSTALL_FAILED_USER_RESTRICTED*|*INSTALL_FAILED_VERIFICATION_FAILURE*)
            die 7 "The TV blocked the install. Allow installs over ADB / disable 'Verify apps over ADB' in Developer options, and confirm any prompt on the TV." ;;
        *"device offline"*|*"device not found"*|*"no devices"*)
            die 6 "Lost the connection to the TV during install. Run the script again." ;;
        *)
            die 7 "Install failed (see adb output above)." ;;
    esac
fi

if [ "$LAUNCH" -eq 1 ]; then
    if adb -s "$TV" shell monkey -p "$PACKAGE" -c android.intent.category.LEANBACK_LAUNCHER 1 >/dev/null 2>&1; then
        ok "Started DumbTube on the TV."
    else
        warn "Could not start DumbTube automatically. Open it from the TV's app list."
    fi
fi

[ "$KEEP" -eq 1 ] && [ -z "$LOCAL_APK" ] && info "APK kept at $APK"
exit 0
