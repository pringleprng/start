#!/usr/bin/env python3
"""Install TextGen + Inkling 2 Mini Uncensored (vision) + the H3 I2V Director on Bazzite.

Works on Bazzite and other x86-64 Linux systems with an NVIDIA GPU (made for an
RTX 5080). Everything goes into one folder in your home directory; nothing is
installed system-wide, so it suits Bazzite's read-only system.

    python3 install.py                       # everything, into ~/AI/textgen
    python3 install.py --vram-budget 7        # give Inkling more VRAM next to Fooocus
    python3 install.py --quant Q4_K_M          # a specific quant instead of the automatic choice
    python3 install.py --skip-model          # update the programs, keep the model

What it does:
  1. checks the NVIDIA driver and GPU (nvidia-smi)
  2. TextGen portable (CUDA build) from github.com/oobabooga/textgen
  3. llama.cpp (CUDA 12.x build + its CUDA runtime) from github.com/ggml-org/llama.cpp,
     new enough for Inkling 2, placed where the H3 tab makes TextGen use it
  4. Inkling 2 Mini Uncensored GGUF + its mmproj (vision) from Hugging Face; the quant is chosen
     by size so that it fits your RAM + VRAM next to Fooocus (about 10-11 GB with 16 GB RAM)
  5. the H3 I2V Director tab, Chat template and preset
  6. settings (auto-load within a VRAM budget, so it fits on the GPU next to Fooocus),
     CMD_FLAGS.txt, a start script and an app-menu entry

Run it again any time: finished downloads are skipped, broken ones resumed.
Optional environment variables: GITHUB_TOKEN (GitHub rate limit), HF_TOKEN (gated models).
"""

from __future__ import annotations

import argparse
import base64
import errno
import http.client
import io
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

GITHUB_API = os.environ.get("H3_GITHUB_API", "https://api.github.com")
GITHUB_RAW = os.environ.get("H3_GITHUB_RAW", "https://raw.githubusercontent.com")
HF = os.environ.get("H3_HF", "https://huggingface.co")
PYPI = os.environ.get("H3_PYPI", "https://pypi.org")

MIN_LLAMA_BUILD = 12653          # 23 Nov 2026: Inkling 2 tokenizer fix (#32799) and looped-MoE expert fix (#32807)
MIN_DRIVER_BLACKWELL = 570       # RTX 50-series / CUDA 12.8
MIN_DRIVER_CUDA13 = 580
DEFAULT_REPO = "Abiray/Inkling-2-Mini-Uncensored-GGUF"
# other uncensored GGUF uploads, searched in this order when --quant auto needs a size the first lacks
FALLBACK_REPOS = ["AtomicChat/Inkling-2-Mini-Uncensored-GGUF", "KookiesXy/Inkling-2-Mini-Uncensored-GGUF",
                  "ghost-actual/Inkling-2-Mini-Uncensored-GGUF"]
Q4_K_M_GB = 16.5           # never pick more than about a Q4_K_M automatically (speed)
DEFAULT_BUDGET_GB = 6.5    # VRAM for Inkling next to Fooocus on a 16 GB card
H3_SOURCE_REPO = "pringleprng/start"
H3_SOURCE_BRANCH = "ccr-df6920e9-t3vfcw"
H3_FILES = [
    "user_data/extensions/h3_i2v_director/script.py",
    "user_data/extensions/h3_i2v_director/h3_core.py",
    "user_data/extensions/h3_i2v_director/h3_system.py",
    "user_data/extensions/h3_i2v_director/h3_selftest.py",
    "user_data/extensions/h3_i2v_director/system_prompt.md",
    "user_data/instruction-templates/Inkling 2 - H3 Director.yaml",
    "user_data/presets/H3 Director.yaml",
]
EXTENSION = "h3_i2v_director"
USER_AGENT = "h3-i2v-director-installer"

# The one-file setup script (h3-director-setup.sh) carries the H3 files here as a base64 tar.gz,
# written by tools/build_setup_script.py. Empty in install.py itself, which uses the files next
# to it (or downloads them from GitHub when run on its own).
EMBEDDED_FILES = ""


# --------------------------------------------------------------------------------------
# output helpers
# --------------------------------------------------------------------------------------

def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(msg: str) -> None:
    say(f"\n==> {msg}")


def warn(msg: str) -> None:
    say(f"  ! {msg}")


class InstallError(Exception):
    pass


# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------

def _headers(url: str) -> dict:
    h = {"User-Agent": USER_AGENT}
    if url.startswith(GITHUB_API) and os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    if url.startswith(HF) and os.environ.get("HF_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['HF_TOKEN']}"
    return h


def get_json(url: str):
    req = urllib.request.Request(url, headers={**_headers(url), "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403 and "github" in url:
            raise InstallError(f"GitHub refused {url} (rate limit?). Wait an hour or set GITHUB_TOKEN.") from exc
        if exc.code in (401, 403) and url.startswith(HF):
            raise InstallError(f"Hugging Face refused {url}. If the model is gated, set HF_TOKEN.") from exc
        raise InstallError(f"{url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise InstallError(f"{url}: {exc.reason}") from exc


def download(url: str, dest: Path, size: int | None = None) -> Path:
    """Download with resume. Skips files that are already complete.

    A dropped connection usually just ends the response early (no exception), so a short file
    counts as an interruption too: the next try asks for the rest with a Range request. Tries that
    make progress don't count against the limit, so a slow, flaky line still gets there."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and size and dest.stat().st_size == size:
        say(f"  ✓ {dest.name} (already downloaded)")
        return dest
    part = dest.with_name(dest.name + ".part")
    if size and part.exists() and part.stat().st_size > size:
        part.unlink()
    failures = tries = 0
    while failures < 6 and tries < 100:
        tries += 1
        have = part.stat().st_size if part.exists() else 0
        if size and have == size:
            part.replace(dest)
            return dest
        headers = _headers(url)
        if have:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(url, headers=headers)
        reason, got = "", 0
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                if have and resp.status != 206:
                    have = 0  # server ignored the range: start over
                length = int(resp.headers.get("Content-Length") or 0)
                expected = size or (length + have if length else None)
                done, last = have, 0.0
                with open(part, "ab" if have else "wb") as out:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        got += len(chunk)
                        if time.time() - last > 1.0:
                            last = time.time()
                            pct = f"{done / expected * 100:5.1f}%" if expected else ""
                            print(f"\r  ↓ {dest.name}: {done / 1e9:6.2f} GB {pct}", end="", flush=True)
            print()
            now = part.stat().st_size
            if expected is None or now == expected:
                part.replace(dest)
                return dest
            if now > expected:
                part.unlink()
                raise InstallError(f"{dest.name}: got {now} bytes, expected {expected}; run the installer again")
            reason = f"connection closed at {now / 1e9:.2f} of {expected / 1e9:.2f} GB"
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            print()
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 416 and size and have == size:
                part.replace(dest)
                return dest
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 404):
                raise InstallError(f"{url}: HTTP {exc.code}") from exc
            if isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, errno.EDQUOT, errno.EACCES, errno.EROFS):
                raise InstallError(f"cannot write {part}: {exc.strerror}") from exc
            reason = str(exc)
        failures = 0 if got else failures + 1
        warn(f"download interrupted ({reason}); resuming" + (f" (try {failures + 1} of 6)" if failures else ""))
        time.sleep(min(30, 2 ** max(failures, 1)))
    raise InstallError(f"could not download {url}; run the installer again to resume")


# --------------------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------------------

def check_gpu() -> dict:
    step("Checking the NVIDIA GPU")
    info = {"name": "", "driver": "", "driver_major": 0, "compute_cap": "", "vram_gb": 0.0}
    exe = shutil.which("nvidia-smi")
    if not exe:
        warn("nvidia-smi not found: no NVIDIA driver. On Bazzite, switch to the NVIDIA image "
             "(the '-nvidia-open' variant for RTX 50-series cards) and run this again.")
        warn("Continuing anyway; llama.cpp will fall back to the CPU (slow).")
        return info
    try:
        out = subprocess.run([exe, "--query-gpu=name,driver_version,compute_cap,memory.total",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=20, check=True).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        warn(f"nvidia-smi failed: {exc}")
        return info
    first = out.strip().splitlines()[0] if out.strip() else ""
    parts = [p.strip() for p in first.split(",")]
    if len(parts) >= 3:
        info.update(name=parts[0], driver=parts[1], compute_cap=parts[2])
        try:
            info["driver_major"] = int(parts[1].split(".")[0])
        except ValueError:
            pass
        say(f"  ✓ {parts[0]} · driver {parts[1]} · compute {parts[2]}" + (f" · {parts[3]}" if len(parts) > 3 else ""))
        if len(parts) > 3:
            m = re.match(r"(\d+)", parts[3])
            info["vram_gb"] = int(m.group(1)) / 1024 if m else 0.0
    if info["compute_cap"].startswith("12") and 0 < info["driver_major"] < MIN_DRIVER_BLACKWELL:
        raise InstallError(f"RTX 50-series cards need NVIDIA driver {MIN_DRIVER_BLACKWELL} or newer "
                           f"(you have {info['driver']}). Update Bazzite (`ujust update`) and reboot.")
    return info


def check_space(base: Path, need_gb: float) -> None:
    base.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(base).free / 1e9
    if free < need_gb:
        raise InstallError(f"only {free:.0f} GB free in {base}; about {need_gb:.0f} GB are needed")
    say(f"  ✓ {free:.0f} GB free in {base}")


def check_ram() -> float:
    try:
        meminfo = Path("/proc/meminfo").read_text()
        total_gb = int(re.search(r"MemTotal:\s+(\d+)", meminfo).group(1)) / 1024 / 1024
    except (OSError, AttributeError):
        return 0.0
    say(f"  ✓ {total_gb:.0f} GB RAM")
    return total_gb


def auto_size_limit_gb(ram_gb: float) -> float:
    """Largest model file that still fits when Fooocus runs too.

    With the "fit" profile about 5 GB of the model sits in VRAM (6.5 GB budget minus vision file and
    context); the rest needs free system RAM, after roughly 10 GB for the desktop, Fooocus and TextGen.
    """
    if ram_gb <= 0:
        return 11.0
    return max(6.0, min(Q4_K_M_GB, ram_gb - 5.0))


# --------------------------------------------------------------------------------------
# GitHub releases
# --------------------------------------------------------------------------------------

def releases(repo: str, tag: str = "latest") -> list[dict]:
    """The given release, or the recent releases newest first (some releases lack some files)."""
    if tag != "latest":
        return [get_json(f"{GITHUB_API}/repos/{repo}/releases/tags/{tag}")]
    found = get_json(f"{GITHUB_API}/repos/{repo}/releases?per_page=30")
    return [r for r in found if not r.get("draft") and not r.get("prerelease")]


def pick_asset(release: dict, pattern: str) -> dict | None:
    rx = re.compile(pattern)
    matches = [a for a in release.get("assets", []) if rx.fullmatch(a["name"])]
    return sorted(matches, key=lambda a: a["name"])[-1] if matches else None


def pick_textgen_release(rels: list[dict], cuda: str) -> tuple[dict | None, dict | None]:
    """The newest release that has a Linux CUDA portable package (the wanted CUDA version first)."""
    for rel in rels:
        v = re.escape(rel["tag_name"].lstrip("v"))
        asset = (pick_asset(rel, rf"textgen-portable-{v}-linux-cuda{re.escape(cuda)}\.(?:tar\.gz|zip)")
                 or pick_asset(rel, rf"textgen-portable-{v}-linux-cuda[0-9.]+\.(?:tar\.gz|zip)"))
        if asset:
            return rel, asset
    return None, None


def install_textgen(base: Path, downloads: Path, gpu: dict, tag: str) -> Path:
    step("TextGen (portable, CUDA)")
    cuda = "13.1" if gpu["driver_major"] >= MIN_DRIVER_CUDA13 or not gpu["driver_major"] else "12.4"
    rel, asset = pick_textgen_release(releases("oobabooga/textgen", tag), cuda)
    if not asset:
        raise InstallError("no TextGen release with a Linux CUDA package found")
    version = rel["tag_name"].lstrip("v")
    target = base / f"textgen-{version}"
    done = target / ".h3-unpacked"
    if done.exists() and (target / "textgen").exists():
        say(f"  ✓ TextGen {version} already installed")
    else:
        archive = download(asset["browser_download_url"], downloads / asset["name"], asset.get("size"))
        say(f"  … unpacking {asset['name']}")
        if asset["name"].endswith(".zip"):
            extract_zip(archive, base)
        else:
            with tarfile.open(archive) as tar:
                safe_extract(tar, base)
        if not (target / "textgen").exists():
            raise InstallError(f"{asset['name']} did not contain textgen-{version}/textgen")
        done.write_text(asset["name"] + "\n", encoding="utf-8")
        say(f"  ✓ TextGen {version}")
    # One user_data next to the version folders: TextGen uses it when it exists, and it
    # survives TextGen updates (models, settings, extensions).
    shared_ud = base / "user_data"
    if not shared_ud.exists():
        shutil.copytree(target / "user_data", shared_ud)
        say(f"  ✓ created {shared_ud} (shared by all TextGen versions)")
    current = base / "textgen-current"
    if current.is_symlink() or current.exists():
        current.unlink()
    current.symlink_to(target.name)
    say(f"  ✓ {current} → {target.name}")
    return target


def extract_zip(archive: Path, dest: Path) -> None:
    """Unzip keeping the Unix permissions (zipfile drops them, and the launcher must stay executable)."""
    root = dest.resolve()
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(root):
                raise InstallError(f"unsafe path in archive: {info.filename}")
            mode = (info.external_attr >> 16) & 0o7777
            if stat.S_ISLNK(info.external_attr >> 16):
                target.parent.mkdir(parents=True, exist_ok=True)
                link = z.read(info).decode()
                if (target.parent / link).resolve().is_relative_to(root):
                    if target.is_symlink() or target.exists():
                        target.unlink()
                    target.symlink_to(link)
                continue
            z.extract(info, dest)
            if mode:
                target.chmod(mode)


def safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    if sys.version_info >= (3, 12):
        tar.extractall(dest, filter="tar")
        return
    root = dest.resolve()
    for member in tar.getmembers():
        if not (dest / member.name).resolve().is_relative_to(root):
            raise InstallError(f"unsafe path in archive: {member.name}")
    tar.extractall(dest)


def pick_llama_release(rels: list[dict]) -> tuple[str, dict | None, dict | None]:
    """The newest bNNNN release at or above MIN_LLAMA_BUILD that has both Linux CUDA 12 files
    (a release appears before its files are built, and some builds fail)."""
    for rel in rels:
        m = re.fullmatch(r"b(\d+)", rel.get("tag_name", ""))
        if not m or int(m.group(1)) < MIN_LLAMA_BUILD:
            continue
        name = rel["tag_name"]
        main = pick_asset(rel, rf"llama-{re.escape(name)}-bin-ubuntu-cuda-12\.\d+-x64\.tar\.gz")
        runtime = pick_asset(rel, rf"cudart-llama-{re.escape(name)}-bin-ubuntu-cuda-12\.\d+-x64\.tar\.gz")
        if main and runtime:
            return name, main, runtime
    return "", None, None


def install_llama(user_data: Path, downloads: Path, gpu: dict, tag: str) -> Path:
    step("llama.cpp with Inkling 2 support (CUDA)")
    name, main, runtime = pick_llama_release(releases("ggml-org/llama.cpp", tag))
    if not name:
        raise InstallError(f"no llama.cpp release b{MIN_LLAMA_BUILD} or newer with a Linux CUDA 12 build found yet; "
                           "new releases appear every few hours, try again later")
    folder = user_data / "llama-cpp" / f"llama-{name}"
    server = folder / "llama-server"
    done = folder / ".h3-unpacked"
    if done.exists() and server.exists() and (folder / "libcudart.so.12").exists():
        say(f"  ✓ llama.cpp {name} already installed")
    else:
        main_tar = download(main["browser_download_url"], downloads / main["name"], main.get("size"))
        rt_tar = download(runtime["browser_download_url"], downloads / runtime["name"], runtime.get("size"))
        (user_data / "llama-cpp").mkdir(parents=True, exist_ok=True)
        say(f"  … unpacking {main['name']}")
        with tarfile.open(main_tar) as tar:
            safe_extract(tar, user_data / "llama-cpp")
        if not server.exists():
            raise InstallError(f"{main['name']} did not contain llama-{name}/llama-server")
        # the CUDA runtime goes next to the binaries (they look in $ORIGIN)
        with tempfile.TemporaryDirectory(dir=user_data / "llama-cpp") as tmp:
            with tarfile.open(rt_tar) as tar:
                safe_extract(tar, Path(tmp))
            for lib in Path(tmp).rglob("*.so*"):
                if (folder / lib.name).exists() or (folder / lib.name).is_symlink():
                    (folder / lib.name).unlink()
                shutil.move(str(lib), folder / lib.name)
        if not (folder / "libcudart.so.12").exists():
            raise InstallError(f"{runtime['name']} did not contain libcudart.so.12")
        server.chmod(server.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        done.write_text(main["name"] + "\n", encoding="utf-8")
    ensure_openmp(folder, downloads)
    try:
        devices = subprocess.run([str(server), "--list-devices"], capture_output=True, text=True, timeout=120,
                                 env={**os.environ, "LD_LIBRARY_PATH": str(folder)})
        listing = devices.stdout + devices.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        listing = f"llama-server --list-devices failed: {exc}"
    cuda_lines = [ln.strip() for ln in listing.splitlines() if re.match(r"\s*CUDA\d+:", ln)]
    if cuda_lines:
        for ln in cuda_lines:
            say(f"  ✓ llama.cpp sees {ln}")
    elif gpu["name"]:
        warn("llama.cpp does not see the GPU (no CUDA0 device). Check that the NVIDIA driver works "
             "(`nvidia-smi`), then run this installer again.")
        warn(listing.strip()[-600:])
    return server


def _missing_libs(folder: Path) -> set[str]:
    """Shared libraries llama.cpp's CPU code cannot find on this system."""
    probe = sorted(folder.glob("libggml-cpu-*.so")) or sorted(folder.glob("libggml-cpu*.so"))
    if not probe or not shutil.which("ldd"):
        return set()
    out = subprocess.run(["ldd", str(probe[0])], capture_output=True, text=True,
                         env={**os.environ, "LD_LIBRARY_PATH": str(folder)}).stdout
    return {line.split()[0] for line in out.splitlines() if "not found" in line}


def ensure_openmp(folder: Path, downloads: Path) -> None:
    """llama.cpp's CPU code needs libgomp.so.1 (OpenMP). Without it the model does not load
    ("no CPU backend found"). If the system lacks it, put a private copy next to llama-server;
    it comes from scikit-learn's Linux wheel on PyPI, which ships a self-contained libgomp."""
    forced = os.environ.get("H3_FORCE_BUNDLED_OPENMP") == "1"
    missing = _missing_libs(folder)
    if not forced and "libgomp.so.1" not in missing:
        if missing:
            warn("llama.cpp is missing system libraries: " + ", ".join(sorted(missing)))
        else:
            say("  ✓ system libraries for llama.cpp are present")
        return
    target = folder / "libgomp.so.1"
    if not forced and target.exists():
        return
    say("  … libgomp.so.1 (OpenMP) is not installed on this system; adding a private copy next to llama-server")
    try:
        info = get_json(f"{PYPI}/pypi/scikit-learn/json")
        wheels = [u for u in info.get("urls", []) if u["filename"].endswith(".whl")
                  and "manylinux" in u["filename"] and "x86_64" in u["filename"]]
        if not wheels:
            raise InstallError("no Linux wheel listed")
        wheel = download(wheels[0]["url"], downloads / wheels[0]["filename"], wheels[0].get("size"))
        with zipfile.ZipFile(wheel) as z:
            member = next((n for n in z.namelist() if re.search(r"\.libs/libgomp[-.\w]*\.so[.\d]*$", n)), None)
            if not member:
                raise InstallError("the wheel has no libgomp")
            target.write_bytes(z.read(member))
        target.chmod(0o755)
    except (InstallError, OSError, zipfile.BadZipFile, KeyError, StopIteration) as exc:
        raise InstallError(f"could not add libgomp ({exc}). Install it once with: rpm-ostree install libgomp "
                           "&& systemctl reboot, then run this script again.") from exc
    if "libgomp.so.1" in _missing_libs(folder):
        raise InstallError("libgomp is still missing. Install it with: rpm-ostree install libgomp && systemctl reboot")
    say("  ✓ libgomp.so.1 added")


# --------------------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------------------

PROJ_PREFERENCE = ("bf16", "f16", "f32", "q8")


def choose_model_files(files: list[str], quant: str) -> tuple[list[str], str]:
    """(model GGUF part(s), mmproj) from a Hugging Face file list."""
    ggufs = [f for f in files if f.lower().endswith(".gguf")]
    projs = [f for f in ggufs if "mmproj" in Path(f).name.lower()]
    models = [f for f in ggufs if f not in projs and quant.lower() in Path(f).name.lower()]
    # a quant may be split into parts (…-00001-of-00003.gguf) or have variants (UD-Q4_K_M):
    # prefer the plain name, then keep every part of the chosen file
    def key(f):
        n = Path(f).name.lower()
        return (re.search(r"-\d{5}-of-\d{5}\.gguf$", n) is None, not n.startswith("ud-"), -len(n))
    if not models:
        return [], ""
    best = max(models, key=key)
    m = re.match(r"(.*)-\d{5}-of-(\d{5})\.gguf$", best)
    parts = sorted(f for f in models if m and f.startswith(m.group(1) + "-")) if m else [best]
    return parts, choose_mmproj(files)


def choose_mmproj(files: list[str]) -> str:
    """The vision projector: BF16 > F16 > F32 > Q8."""
    projs = [f for f in files if f.lower().endswith(".gguf") and "mmproj" in Path(f).name.lower()]

    def proj_key(f):
        n = Path(f).name.lower()
        rank = next((i for i, p in enumerate(PROJ_PREFERENCE) if p in n), len(PROJ_PREFERENCE))
        return (-rank, n)
    return max(projs, key=proj_key) if projs else ""


def _gguf_groups(files: list[str], sizes: dict) -> dict:
    """Model GGUFs (no mmproj) grouped by name, with split parts together: {first part: (parts, total size)}."""
    groups: dict[str, list[str]] = {}
    for f in files:
        name = Path(f).name.lower()
        if not name.endswith(".gguf") or "mmproj" in name:
            continue
        m = re.match(r"(.*)-\d{5}-of-\d{5}\.gguf$", f)
        groups.setdefault(m.group(1) if m else f, []).append(f)
    out = {}
    for parts in groups.values():
        parts.sort()
        if all(sizes.get(p) for p in parts):
            out[parts[0]] = (parts, sum(sizes[p] for p in parts))
    return out


def choose_by_size(files: list[str], sizes: dict, limit_bytes: int) -> tuple[list[str], int]:
    """The biggest model file (or split set) that is not bigger than limit_bytes."""
    fitting = [(total, parts) for parts, total in _gguf_groups(files, sizes).values() if total <= limit_bytes]
    if not fitting:
        return [], 0
    total, parts = max(fitting, key=lambda t: (t[0], not Path(t[1][0]).name.lower().startswith("ud-")))
    return parts, total


def _repo_files(repo: str) -> tuple[list[str], dict]:
    info = get_json(f"{HF}/api/models/{repo}?blobs=true")
    siblings = info.get("siblings", [])
    return ([s["rfilename"] for s in siblings],
            {s["rfilename"]: s.get("size") or (s.get("lfs") or {}).get("size") for s in siblings})


def _quant_names(files: list[str]) -> str:
    names = {m.group(1) for f in files
             for m in [re.search(r"[-_.]((?:UD-)?I?Q\d\w*?|BF16|F16)(?:-\d{5}-of-\d{5})?\.gguf$", f, re.I)] if m}
    return ", ".join(sorted(names)) or "none"


def install_model(user_data: Path, repo: str, quant: str, ram_gb: float, search_fallbacks: bool) -> tuple[str, str]:
    repos = [repo] + ([r for r in FALLBACK_REPOS if r != repo] if search_fallbacks else [])
    if quant.lower() == "auto":
        limit_gb = auto_size_limit_gb(ram_gb)
        step(f"Inkling 2 Mini Uncensored: biggest file up to {limit_gb:.1f} GB (fits {ram_gb:.0f} GB RAM + the GPU)")
    else:
        step(f"Inkling 2 Mini Uncensored {quant}")
    listings: dict[str, tuple[list[str], dict]] = {}
    chosen_repo, parts, best_total = "", [], 0
    for r in repos:
        try:
            listings[r] = _repo_files(r)
        except InstallError as exc:
            warn(f"skipping {r}: {exc}")
            continue
        files, sizes = listings[r]
        if quant.lower() == "auto":
            cand, total = choose_by_size(files, sizes, int(limit_gb * 1e9))
            if cand and total > best_total:
                chosen_repo, parts, best_total = r, cand, total
            if best_total >= 0.85 * limit_gb * 1e9:
                break  # good enough; don't query more repositories
        else:
            cand, _ = choose_model_files(files, quant)
            if cand:
                chosen_repo, parts = r, cand
                break
    if not parts and quant.lower() == "auto":
        # nothing small enough anywhere: take the smallest file there is, and say so
        smallest = None
        for r, (files, sizes) in listings.items():
            for group, total in _gguf_groups(files, sizes).values():
                if smallest is None or total < smallest[2]:
                    smallest = (r, group, total)
        if smallest:
            chosen_repo, parts, _ = smallest
            warn(f"no Inkling file of {limit_gb:.1f} GB or less was found; taking the smallest one. With Fooocus "
                 "open, lower the VRAM budget or close other programs; without Fooocus use the Whole GPU profile.")
    if not parts:
        available = "; ".join(f"{r}: {_quant_names(f)}" for r, (f, _) in listings.items())
        if quant.lower() == "auto":
            raise InstallError(f"no Inkling file found ({available or 'no repository reachable'}).")
        raise InstallError(f"no {quant} file found ({available}). Use --quant with one of those.")
    files, sizes = listings[chosen_repo]
    total_gb = sum(sizes.get(f) or 0 for f in parts) / 1e9
    say(f"  ✓ {Path(parts[0]).name} ({total_gb:.1f} GB) from {chosen_repo}")

    # the vision file: from the same upload if it has one, else from another upload of the same model
    mmproj, mmproj_repo = "", ""
    for r in [chosen_repo] + [x for x in repos if x != chosen_repo]:
        if r not in listings:
            try:
                listings[r] = _repo_files(r)
            except InstallError:
                continue
        proj = choose_mmproj(listings[r][0])
        if proj:
            mmproj, mmproj_repo = proj, r
            break
    if not mmproj:
        warn("no mmproj (vision) file found: the model will work without seeing pictures")

    for f in parts:
        download(f"{HF}/{chosen_repo}/resolve/main/{f}?download=true", user_data / "models" / Path(f).name, sizes.get(f))
    if mmproj:
        download(f"{HF}/{mmproj_repo}/resolve/main/{mmproj}?download=true", user_data / "mmproj" / Path(mmproj).name,
                 listings[mmproj_repo][1].get(mmproj))
    others = [p for p in (user_data / "models").glob("*nkling*.gguf") if p.name not in {Path(f).name for f in parts}]
    if others:
        say("  i other Inkling files you can delete to free disk space: " + ", ".join(p.name for p in others))
    return Path(parts[0]).name, Path(mmproj).name if mmproj else ""


# --------------------------------------------------------------------------------------
# H3 files, settings, launchers
# --------------------------------------------------------------------------------------

def _embedded_files() -> dict[str, bytes]:
    """{"user_data/...": content} from EMBEDDED_FILES (one-file setup script)."""
    data = base64.b64decode("".join(EMBEDDED_FILES.split()))
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile() and member.name in H3_FILES:
                files[member.name] = tar.extractfile(member).read()
    missing = set(H3_FILES) - set(files)
    if missing:
        raise InstallError(f"the setup script is incomplete (missing {', '.join(sorted(missing))})")
    return files


def install_h3_files(user_data: Path, source_repo: str, branch: str) -> None:
    step("H3 I2V Director tab")
    # run from a pipe (curl … | bash) there is no __file__
    local_root = Path(__file__).resolve().parent.parent if "__file__" in globals() else None
    embedded = _embedded_files() if EMBEDDED_FILES else {}
    source = "built into the setup script" if embedded else ""
    for rel in H3_FILES:
        dest = user_data / rel.removeprefix("user_data/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if rel in embedded:
            dest.write_bytes(embedded[rel])
        elif local_root and (local_root / rel).exists():
            shutil.copyfile(local_root / rel, dest)
        else:
            url = f"{GITHUB_RAW}/{source_repo}/{branch}/h3-i2v-promptgen/" + urllib.request.quote(rel)
            download(url, dest)
            source = f"from {source_repo}@{branch}"
    say(f"  ✓ installed into {user_data}" + (f" ({source})" if source else ""))


def update_cmd_flags(user_data: Path) -> None:
    path = user_data / "CMD_FLAGS.txt"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, found = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            out.append(line)
            continue
        tokens = shlex.split(stripped)
        if "--model" in tokens or any(t.startswith("--model=") for t in tokens):
            warn("removed --model from CMD_FLAGS.txt: the H3 tab loads Inkling itself, after it has switched "
                 "TextGen to the newer llama.cpp")
            i = tokens.index("--model") if "--model" in tokens else None
            tokens = [t for j, t in enumerate(tokens) if not (t.startswith("--model=") or j == i or
                                                               (i is not None and j == i + 1))]
        if "--extensions" in tokens:
            i = tokens.index("--extensions")
            j = i + 1
            while j < len(tokens) and not tokens[j].startswith("-"):
                j += 1
            if EXTENSION not in tokens[i + 1:j]:
                tokens.insert(j, EXTENSION)
            found = True
        if tokens:
            out.append(shlex.join(tokens))
    if not found:
        out.append(f"--extensions {EXTENSION}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    say(f"  ✓ {path} enables the H3 tab")


def write_settings(user_data: Path, server: Path, model: str, mmproj: str, profile: str | None,
                   budget: float | None) -> dict:
    """Point the tab at the new llama-server and model. Choices made in the tab (profile, budget,
    auto-load) are kept on a re-run unless --profile / --vram-budget are given."""
    path = user_data / "extensions" / EXTENSION / "settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    settings["llama_server_path"] = str(server)
    settings["gpu_profile"] = profile or settings.get("gpu_profile") or "fit"
    settings["vram_budget_gb"] = budget if budget is not None else settings.get("vram_budget_gb", DEFAULT_BUDGET_GB)
    settings.setdefault("autoload", True)
    settings.setdefault("ctx_size", 12288)
    if model:
        settings["model_file"] = model
    if mmproj:
        settings["mmproj_file"] = mmproj
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    how = f"VRAM budget {settings['vram_budget_gb']:g} GB" if settings["gpu_profile"] == "fit" else "whole GPU"
    load = f"auto-load {model or settings.get('model_file') or '(model chosen in the tab)'}" if settings["autoload"] \
        else "auto-load off (as set in the tab)"
    say(f"  ✓ {path}: {load}, {how}")
    return settings


def desktop_quote(arg: str) -> str:
    """Quote one argument for the Exec= key of a .desktop file (freedesktop Desktop Entry spec)."""
    if not re.search(r'[\s"\'\\><~|&;$*?#()`%]', arg):
        return arg
    inner = re.sub(r'(["`$\\])', r"\\\1", arg).replace("%", "%%")
    # the .desktop format then unescapes backslashes once more when it reads the string value
    return '"' + inner.replace("\\", "\\\\") + '"'


def write_launchers(base: Path, desktop: bool) -> Path:
    step("Start script and app-menu entry")
    script = base / "start-h3-director.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "# TextGen with the H3 I2V Director tab.\n"
        "#   ./start-h3-director.sh            desktop window\n"
        "#   ./start-h3-director.sh --browser  no window, open http://127.0.0.1:7860 yourself\n"
        "#   ./start-h3-director.sh --listen   also reachable from other devices on your network\n"
        'DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        'if [[ "$1" == "--browser" ]]; then shift; exec "$DIR/textgen-current/textgen" --no-electron "$@"; fi\n'
        'exec "$DIR/textgen-current/textgen" "$@"\n', encoding="utf-8")
    script.chmod(0o755)
    say(f"  ✓ {script}")
    if desktop:
        apps = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        icon = base / "textgen-current" / "app" / "css" / "icon.png"
        entry = apps / "h3-i2v-director.desktop"
        entry.write_text(
            "[Desktop Entry]\nType=Application\nName=TextGen H3 Director\n"
            "Comment=Inkling 2 Mini writes MiniMax H3 image-to-video prompts\n"
            f"Exec={desktop_quote(str(script))}\n"
            f"Icon={icon if icon.exists() else 'applications-multimedia'}\n"
            "Terminal=false\nCategories=Graphics;AudioVideo;\n", encoding="utf-8")
        say(f"  ✓ app menu: 'TextGen H3 Director' ({entry})")
    return script


# --------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=os.environ.get("H3_PROG") or None, description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", default=str(Path.home() / "AI" / "textgen"), help="install folder (default ~/AI/textgen)")
    ap.add_argument("--repo", default=DEFAULT_REPO, help=f"Hugging Face GGUF repo (default {DEFAULT_REPO})")
    ap.add_argument("--quant", default="auto",
                    help="quant to download, e.g. Q4_K_M; default auto = the biggest file that fits your RAM")
    ap.add_argument("--profile", choices=("fit", "full"), default=None,
                    help="GPU profile: fit = stay within --vram-budget, next to Fooocus (default); full = whole GPU")
    ap.add_argument("--vram-budget", type=float, default=None,
                    help=f"GB of VRAM Inkling may use with --profile fit (default {DEFAULT_BUDGET_GB:g}, for a 16 GB "
                         "card + Fooocus; a re-run keeps what you set in the tab)")
    ap.add_argument("--textgen-tag", default="latest")
    ap.add_argument("--llama-tag", default="latest")
    ap.add_argument("--skip-model", action="store_true", help="don't download the model")
    ap.add_argument("--no-desktop", action="store_true", help="no app-menu entry")
    ap.add_argument("--source-repo", default=H3_SOURCE_REPO, help="GitHub repo with the H3 files (when run standalone)")
    ap.add_argument("--branch", default=H3_SOURCE_BRANCH)
    args = ap.parse_args(argv)

    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        say("This installer is for x86-64 Linux (Bazzite). See the README for Windows/macOS.")
        return 1
    base = Path(args.dir).expanduser().resolve()
    downloads = base / "downloads"
    try:
        gpu = check_gpu()
        step("Checking disk and memory")
        check_space(base, 6 if args.skip_model else 24)
        ram_gb = check_ram()
        install_textgen(base, downloads, gpu, args.textgen_tag)
        user_data = base / "user_data"
        server = install_llama(user_data, downloads, gpu, args.llama_tag)
        model = mmproj = ""
        if not args.skip_model:
            model, mmproj = install_model(user_data, args.repo, args.quant, ram_gb, args.repo == DEFAULT_REPO)
        install_h3_files(user_data, args.source_repo, args.branch)
        update_cmd_flags(user_data)
        settings = write_settings(user_data, server, model, mmproj, args.profile, args.vram_budget)
        script = write_launchers(base, not args.no_desktop)
    except InstallError as exc:
        say(f"\n✗ {exc}")
        return 1
    except KeyboardInterrupt:
        say("\nStopped. Run the installer again to continue where it left off.")
        return 130
    except Exception as exc:  # anything unexpected: show it plainly, keep the details for a bug report
        traceback.print_exc()
        say(f"\n✗ Unexpected error: {type(exc).__name__}: {exc}\n"
            "Run the installer again; finished steps are skipped. If it happens again, the lines above "
            "say where it failed.")
        return 1

    step("Done")
    say(f"Start 'TextGen H3 Director' from the app menu, or run {script}")
    how = f"within {settings['vram_budget_gb']:g} GB of VRAM" if settings["gpu_profile"] == "fit" else "on the whole GPU"
    if settings["autoload"]:
        say(f"Inkling loads by itself ({how}); open the 'H3 I2V Director' tab.")
    else:
        say(f"Open the 'H3 I2V Director' tab and press Load Inkling ({how}).")
    say(f"Downloaded archives are in {downloads}; delete them to free space.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
