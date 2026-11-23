"""Machine-side helpers for the H3 I2V Director: GPU memory, model files, GPU profiles.

Plain Python (no TextGen imports) so it can be tested on its own.
"""

from __future__ import annotations

import shutil
import subprocess

# --------------------------------------------------------------------------------------
# GPU
# --------------------------------------------------------------------------------------


def _nvidia_smi(query: list[str], timeout: float = 5.0) -> str:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return ""
    try:
        return subprocess.run([exe, *query, "--format=csv,noheader,nounits"], capture_output=True, text=True,
                              timeout=timeout, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_gpus(out: str) -> list[dict]:
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            try:
                used, total = int(float(parts[1])), int(float(parts[2]))
            except ValueError:
                continue
            gpus.append({"name": parts[0], "used_mb": used, "total_mb": total, "free_mb": total - used,
                         "driver": parts[3]})
    return gpus


def gpu_info() -> list[dict]:
    """NVIDIA GPUs from nvidia-smi: [{name, used_mb, total_mb, free_mb, driver}] (empty if unavailable)."""
    return parse_gpus(_nvidia_smi(["--query-gpu=name,memory.used,memory.total,driver_version"]))


def parse_process_vram(out: str, pid: int) -> int | None:
    """VRAM (MiB) used by one process, from `nvidia-smi --query-compute-apps=pid,used_memory`."""
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0] == str(pid):
            try:
                return int(float(parts[1]))
            except ValueError:
                return None
    return None


def process_vram_mb(pid: int) -> int | None:
    return parse_process_vram(_nvidia_smi(["--query-compute-apps=pid,used_memory"]), pid)


def gpu_summary(gpus: list[dict] | None = None, model_vram_mb: int | None = None) -> str:
    gpus = gpu_info() if gpus is None else gpus
    if not gpus:
        return "GPU: no NVIDIA GPU found (nvidia-smi missing)"
    g = gpus[0]
    text = f"GPU: {g['name']} · {g['used_mb'] / 1024:.1f} / {g['total_mb'] / 1024:.1f} GB in use"
    if model_vram_mb is not None:
        text += f" · Inkling uses {model_vram_mb / 1024:.1f} GB of it"
    return text


# --------------------------------------------------------------------------------------
# Model files and GPU profiles
# --------------------------------------------------------------------------------------

PROFILES = {
    "fit": "Fit next to Fooocus: Inkling stays within the VRAM budget below, the rest goes to system RAM",
    "full": "Whole GPU: fastest, when Fooocus is closed",
}
DEFAULT_PROFILE = "fit"
VISION_OVERHEAD_MB = 512   # image-encoder work buffers on top of the mmproj weights
DESKTOP_MARGIN_MB = 1024   # what the "whole GPU" profile leaves free


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


def resolve_profile(profile: str) -> str:
    return "full" if profile == "full" else "fit"


def fit_margin_mb(profile: str, budget_gb: float, mmproj_mb: int, gpus: list[dict]) -> int:
    """llama.cpp --fit-target (VRAM to leave free) for a profile.

    "fit": Inkling (model + context + vision file) should use about budget_gb of VRAM, whatever
    else is running. llama.cpp only counts the model and context, so the vision file is taken
    off the budget, and the margin is the GPU's free memory minus what is left.
    """
    if resolve_profile(profile) == "full" or not gpus:
        return DESKTOP_MARGIN_MB
    model_budget = int(budget_gb * 1024) - int(mmproj_mb) - VISION_OVERHEAD_MB
    return max(DESKTOP_MARGIN_MB // 2, gpus[0]["free_mb"] - max(model_budget, 512))


def load_args(mmproj: str, ctx_size: int, margin_mb: int) -> dict:
    """TextGen llama.cpp loader settings: let llama.cpp place layers and MoE experts so that
    margin_mb of VRAM stays free (it moves expert weights to system RAM first)."""
    return {
        "loader": "llama.cpp",
        "ctx_size": int(ctx_size),
        "cache_type": "q8_0",
        "mmproj": mmproj or None,
        "cpu_moe": False,
        "gpu_layers": -1,
        "fit_target": str(int(margin_mb)),
    }
