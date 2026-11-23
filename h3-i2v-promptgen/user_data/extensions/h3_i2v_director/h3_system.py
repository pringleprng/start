"""Machine-side helpers for the H3 I2V Director: GPU memory, Fooocus, model files.

Plain Python (no TextGen imports) so it can be tested on its own.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

# --------------------------------------------------------------------------------------
# GPU
# --------------------------------------------------------------------------------------


def gpu_info(timeout: float = 5.0) -> list[dict]:
    """NVIDIA GPUs from nvidia-smi: [{name, used_mb, total_mb, driver}] (empty if unavailable)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.used,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            try:
                gpus.append({"name": parts[0], "used_mb": int(float(parts[1])), "total_mb": int(float(parts[2])),
                             "driver": parts[3]})
            except ValueError:
                continue
    return gpus


def gpu_summary(gpus: list[dict] | None = None) -> str:
    gpus = gpu_info() if gpus is None else gpus
    if not gpus:
        return "GPU: no NVIDIA GPU found (nvidia-smi missing)"
    g = gpus[0]
    return f"GPU: {g['name']} · {g['used_mb'] / 1024:.1f} / {g['total_mb'] / 1024:.1f} GB in use"


# --------------------------------------------------------------------------------------
# Fooocus
# --------------------------------------------------------------------------------------

_FOOOCUS_RE = re.compile(r"fooocus", re.IGNORECASE)


def fooocus_processes(proc: Path = Path("/proc")) -> list[dict]:
    """Running Fooocus Python processes: [{pid, cwd}] (works for distrobox/podman too)."""
    found = []
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if "python" not in cmd.lower():
            continue
        try:
            cwd = os.readlink(entry / "cwd")
        except OSError:
            cwd = ""
        # "python /path/Fooocus/entry_with_update.py", or "python entry_with_update.py" run inside Fooocus/
        started_here = "entry_with_update.py" in cmd or "launch.py" in cmd
        if _FOOOCUS_RE.search(cmd) or (started_here and _FOOOCUS_RE.search(cwd)):
            found.append({"pid": int(entry.name), "cwd": cwd})
    return found


def _fooocus_config_outputs(root: Path) -> list[Path]:
    """path_outputs from Fooocus' config.txt (JSON), if set."""
    cfg = root / "config.txt"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    value = data.get("path_outputs") if isinstance(data, dict) else None
    return [Path(value).expanduser()] if isinstance(value, str) and value else []


def fooocus_output_dirs(configured: str = "", processes: list[dict] | None = None, home: Path | None = None) -> list[Path]:
    """Folders where Fooocus saves images: the configured one, the running Fooocus' folder, common installs."""
    home = home or Path.home()
    if configured.strip():
        path = Path(configured.strip()).expanduser()
        return [path] if path.is_dir() else []
    roots: list[Path] = []
    for proc in (processes if processes is not None else fooocus_processes()):
        if proc.get("cwd"):
            roots.append(Path(proc["cwd"]))
    for rel in ("Fooocus", "fooocus", "AI/Fooocus", "ai/Fooocus", "Applications/Fooocus", "src/Fooocus",
                "Downloads/Fooocus", "Fooocus_win64/Fooocus"):
        roots.append(home / rel)
    dirs: list[Path] = []
    for root in roots:
        for candidate in _fooocus_config_outputs(root) + [root / "outputs"]:
            if candidate.is_dir() and candidate not in dirs:
                dirs.append(candidate)
    return dirs


def newest_images(dirs: list[Path], count: int = 1, max_depth: int = 3) -> list[Path]:
    """The newest image files (newest last) under the given folders."""
    found: list[tuple[float, Path]] = []
    for base in dirs:
        base_depth = len(base.parts)
        for dirpath, dirnames, filenames in os.walk(base):
            if len(Path(dirpath).parts) - base_depth >= max_depth:
                dirnames[:] = []
            for name in filenames:
                if name.lower().endswith(IMAGE_SUFFIXES):
                    path = Path(dirpath) / name
                    try:
                        found.append((path.stat().st_mtime, path))
                    except OSError:
                        continue
    found.sort(key=lambda t: t[0])
    return [p for _, p in found[-count:]]


# --------------------------------------------------------------------------------------
# Model files and GPU profiles
# --------------------------------------------------------------------------------------

PROFILES = {
    "auto": "Auto: share the GPU when Fooocus is running",
    "full": "Full GPU (fastest)",
    "share": "Share GPU with Fooocus (MoE experts in system RAM, small VRAM use)",
}


def pick_inkling(models: list[str], mmprojs: list[str]) -> tuple[str, str]:
    """Best guess for the Inkling 2 GGUF and its mmproj among the available files."""
    def score(name: str) -> tuple:
        low = name.lower()
        return ("inkling" in low, "uncensored" in low or "unbound" in low or "heretic" in low, "q4_k_m" in low, name)

    candidates = [m for m in models if m.lower().endswith(".gguf") and "mmproj" not in m.lower()]
    model = max(candidates, key=score) if candidates else ""
    projs = [m for m in mmprojs if m and m != "None"]
    proj_score = lambda n: ("inkling" in n.lower(), "uncensored" in n.lower(), n)  # noqa: E731
    mmproj = max(projs, key=proj_score) if projs else ""
    if model and "inkling" not in model.lower():
        model = ""
    return model, mmproj


def resolve_profile(profile: str, fooocus_running: bool) -> str:
    if profile == "auto":
        return "share" if fooocus_running else "full"
    return profile if profile in ("full", "share") else "full"


def load_args(profile: str, mmproj: str, ctx_size: int = 16384, vram_margin_mb: int = 1024) -> dict:
    """TextGen llama.cpp loader settings for a resolved profile ("full" or "share")."""
    args = {
        "loader": "llama.cpp",
        "ctx_size": int(ctx_size),
        "cache_type": "q8_0",
        "mmproj": mmproj or None,
        "cpu_moe": False,
    }
    if profile == "share":
        # all layers on the GPU except the MoE experts, which stay in system RAM:
        # a few GB of VRAM, still fast because only 8 of 128 experts run per token
        args.update(gpu_layers=999, cpu_moe=True)
    else:
        # let llama.cpp fit as much as possible into VRAM, leaving a margin for the desktop
        args.update(gpu_layers=-1, fit_target=str(int(vram_margin_mb)))
    return args
