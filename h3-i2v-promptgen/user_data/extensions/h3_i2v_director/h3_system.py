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
                gpus.append({"name": parts[0], "used_mb": int(float(parts[1])), "total_mb": int(float(parts[2])),
                             "driver": parts[3]})
            except ValueError:
                continue
    return gpus


def gpu_info() -> list[dict]:
    """NVIDIA GPUs from nvidia-smi: [{name, used_mb, total_mb, driver}] (empty if unavailable)."""
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
    "small": "Small VRAM: runs next to Fooocus (MoE experts in system RAM)",
    "full": "Full GPU: fastest, when nothing else uses the GPU",
}
DEFAULT_PROFILE = "small"


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
    return "full" if profile == "full" else "small"


def load_args(profile: str, mmproj: str, ctx_size: int = 16384, vram_margin_mb: int = 1024) -> dict:
    """TextGen llama.cpp loader settings for a profile ("small" or "full")."""
    args = {
        "loader": "llama.cpp",
        "ctx_size": int(ctx_size),
        "cache_type": "q8_0",
        "mmproj": mmproj or None,
        "cpu_moe": False,
    }
    if resolve_profile(profile) == "small":
        # every layer on the GPU except the MoE experts, which stay in system RAM:
        # little VRAM, still quick because only 8 of 128 experts run per token
        args.update(gpu_layers=999, cpu_moe=True)
    else:
        # let llama.cpp fit as much as possible into VRAM, leaving a margin for the desktop
        args.update(gpu_layers=-1, fit_target=str(int(vram_margin_mb)))
    return args
