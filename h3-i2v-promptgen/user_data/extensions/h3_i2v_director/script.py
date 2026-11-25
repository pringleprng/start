"""H3 I2V Director: a TextGen tab that turns a plain-language idea plus a picture into a
MiniMax H3 (Hailuo 3) image-to-video prompt in the official H3 format.

The picture goes to the loaded vision model (Inkling 2 Mini with its mmproj), which
writes the prompt; the tab then repairs and checks the structure (h3_core.py).
It can also load Inkling itself within a VRAM budget, so it fits on the GPU next to other
apps such as Fooocus (h3_system.py).

Enable with --extensions h3_i2v_director (or in the Session tab).
"""

import base64
import importlib.util
import io
import json
import os
import re
import stat
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import gradio as gr
import requests

from modules import shared
from modules.logging_colors import logger

HERE = Path(__file__).resolve().parent


def _load_local(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


core = _load_local("h3_i2v_director_core", "h3_core.py")
sysinfo = _load_local("h3_i2v_director_system", "h3_system.py")
sys.modules.setdefault("h3_core", core)  # h3_selftest imports it by this name
selftest = _load_local("h3_i2v_director_selftest", "h3_selftest.py")

SETTINGS_FILE = HERE / "settings.json"
MIN_LLAMA_BUILD = 12653  # llama.cpp fixes for Inkling 2 (tokenizer #32799, looped-MoE experts #32807)

params = {
    "display_name": "H3 I2V Director",
    "is_tab": True,
    "backend": "textgen",               # "textgen" = the model loaded in TextGen; "openai" = a server URL
    "api_url": "http://127.0.0.1:8080/v1",
    "api_key": "",
    "api_model": "",
    "thinking": "off",
    "temperature": 0.8,
    "top_p": 0.95,
    "min_p": 0.05,
    "max_tokens": 2048,
    "auto_repair": True,
    "save_prompts": True,
    "max_image_side": 1024,
    "llama_server_path": "",            # optional newer llama-server for TextGen's llama.cpp loader
    "model_file": "",                   # Inkling GGUF in user_data/models (empty = auto-detect)
    "mmproj_file": "",                  # its vision projector in user_data/mmproj (empty = auto-detect)
    "gpu_profile": "fit",               # fit / full (see h3_system.PROFILES)
    "vram_budget_gb": 6.5,              # VRAM Inkling may use in the "fit" profile (model + vision + context)
    "ctx_size": 12288,                  # rules + picture + answer + a repair pass need about 9k tokens
    "autoload": False,                  # load Inkling when TextGen starts
}
SAVED_KEYS = ("backend", "api_url", "api_key", "api_model", "thinking", "temperature", "top_p", "min_p",
              "max_tokens", "auto_repair", "save_prompts", "max_image_side", "llama_server_path", "model_file",
              "mmproj_file", "gpu_profile", "vram_budget_gb", "ctx_size", "autoload")
PROFILE_BY_LABEL = {v: k for k, v in sysinfo.PROFILES.items()}

BACKENDS = {"TextGen (loaded model)": "textgen", "OpenAI-compatible server (URL)": "openai"}
BACKEND_LABEL = {v: k for k, v in BACKENDS.items()}
MODE_BY_LABEL = {v: k for k, v in core.MODE_LABELS.items()}

_stop = threading.Event()
_override = {"path": None}
_autoload_pending = threading.Event()   # set from start-up until the auto-load has run
_loaded = {"profile": ""}   # how the current model was loaded by this tab


class H3Error(Exception):
    pass


# --------------------------------------------------------------------------------------
# Settings and the optional newer llama-server
# --------------------------------------------------------------------------------------

def _load_settings():
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        params.update({k: saved[k] for k in SAVED_KEYS if k in saved})
    except FileNotFoundError:
        pass
    except Exception as exc:  # a broken file must not stop TextGen
        logger.warning(f"H3 I2V Director: could not read {SETTINGS_FILE}: {exc}")


def _find_llama_server():
    """A newer llama-server: params / H3_LLAMA_SERVER, else the newest one under user_data/llama-cpp/."""
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    configured = str(params.get("llama_server_path") or os.environ.get("H3_LLAMA_SERVER") or "").strip()
    places = [Path(configured).expanduser()] if configured else [Path(shared.user_data_dir) / "llama-cpp"]
    for place in places:
        if place.is_file():
            return place
        if place.is_dir():
            found = [p for p in place.rglob(exe) if p.is_file()]
            if found:
                return max(found, key=lambda p: (_llama_build(p), p.stat().st_mtime))
    return None


def _llama_build(server_path):
    """The build number from a release folder name like llama-b12655/, or 0."""
    m = re.search(r"llama-b(\d+)", str(server_path))
    return int(m.group(1)) if m else 0


def _translate_flags(cmd):
    """TextGen (mid-2026) passes --no-mmap / --mlock; newer llama.cpp replaced them with --load-mode."""
    cmd = list(cmd)
    no_mmap, mlock = "--no-mmap" in cmd, "--mlock" in cmd
    cmd = [c for c in cmd if c not in ("--no-mmap", "--mlock")]
    if no_mmap or mlock:
        cmd += ["--load-mode", "mlock" if (mlock and no_mmap) else ("mmap+mlock" if mlock else "none")]
    return cmd


class _SubprocessShim:
    """Stands in for the subprocess module inside modules.llama_cpp_server."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def Popen(self, cmd, *args, **kwargs):
        if _override["path"] and isinstance(cmd, list) and cmd and str(cmd[0]) == _override["path"]:
            cmd = _translate_flags(cmd)
        return self._real.Popen(cmd, *args, **kwargs)


def _use_llama_server(path):
    from modules import llama_cpp_server as lcs

    path = Path(path)
    if os.name != "nt":
        try:
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass
    cls = lcs.LlamaServer
    if not hasattr(cls, "_h3_original_init"):
        cls._h3_original_init = cls.__init__

        def __init__(self, model_path, server_path=None):
            cls._h3_original_init(self, model_path, server_path=server_path or _override["path"])

        cls.__init__ = __init__
        lcs.subprocess = _SubprocessShim(lcs.subprocess)
    _override["path"] = str(path)
    logger.info(f"H3 I2V Director: TextGen's llama.cpp loader will use {path}")
    build = _llama_build(path)
    if build and build < MIN_LLAMA_BUILD:
        logger.warning(f"H3 I2V Director: llama.cpp b{build} is older than b{MIN_LLAMA_BUILD}, which fixes Inkling 2's "
                       "tokenizer and its expert weights; run the setup script again to update it.")


def _guard_textgen_page_load():
    """TextGen 4.9 quirk (happens with any extension once a model is loaded): on page load its sampler
    filter can get loader None, which prints a KeyError, and the autosave then writes `mode: null`.
    Both are harmless but noisy; treat a missing loader as llama.cpp and a missing mode as instruct."""
    try:
        from modules import loaders
    except Exception:
        return
    original = getattr(loaders, "blacklist_samplers", None)
    if original is None or getattr(original, "_h3_guard", False):
        return

    def blacklist_samplers(loader, dynamic_temperature):
        if loader != "All" and loader not in getattr(loaders, "loaders_samplers", {}):
            loader = "llama.cpp"
        return original(loader, dynamic_temperature)

    blacklist_samplers._h3_guard = True
    loaders.blacklist_samplers = blacklist_samplers
    if shared.settings.get("mode") is None:
        shared.settings["mode"] = "instruct"


def setup():
    _load_settings()
    _guard_textgen_page_load()
    path = _find_llama_server()
    if path:
        _use_llama_server(path)
    if params.get("autoload") and shared.model is None and not _autoload_pending.is_set():
        _autoload_pending.set()
        threading.Thread(target=_autoload, daemon=True).start()


# --------------------------------------------------------------------------------------
# Loading Inkling with a GPU profile
# --------------------------------------------------------------------------------------

_load_lock = threading.Lock()


def _available_files():
    from modules import utils

    models = [m for m in utils.get_available_models() if m != "None"]
    mmprojs = [m for m in utils.get_available_mmproj() if m != "None"]
    return models, mmprojs


def _chosen_files(model_file="", mmproj_file=""):
    models, mmprojs = _available_files()
    auto_model, auto_mmproj = sysinfo.pick_inkling(models, mmprojs)
    model = model_file if model_file in models else (params["model_file"] if params["model_file"] in models else auto_model)
    mmproj = mmproj_file if mmproj_file in mmprojs else (params["mmproj_file"] if params["mmproj_file"] in mmprojs else auto_mmproj)
    return model, mmproj


def _mmproj_mb(name):
    for folder in (Path(shared.user_data_dir) / "mmproj", Path(shared.args.model_dir)):
        path = folder / name
        if name and path.is_file():
            return path.stat().st_size // (1024 * 1024)
    return 0


def load_inkling(model_file="", mmproj_file="", profile_key=None, budget_gb=None):
    """Load the model with a GPU profile. Returns a status line (Markdown)."""
    from modules.models import unload_model

    model, mmproj = _chosen_files(model_file, mmproj_file)
    if not model:
        return ("❌ No Inkling 2 GGUF found in `user_data/models/`. Download the model (and its mmproj) first, "
                "or pick the file in the list.")
    profile = sysinfo.resolve_profile(profile_key or params["gpu_profile"])
    budget = float(budget_gb if budget_gb is not None else params["vram_budget_gb"])
    if not _load_lock.acquire(blocking=False):
        return "⏳ Inkling is already being loaded; wait a moment (the status line above updates by itself)."
    vision_note = ""
    try:
        unload_model()  # measure free VRAM without the previous copy of the model
        margin = sysinfo.fit_margin_mb(profile, budget, _mmproj_mb(mmproj), sysinfo.gpu_info())
        args = sysinfo.load_args(mmproj, params["ctx_size"], margin)
        logger.info(f"H3 I2V Director: loading {model} (mmproj {mmproj or 'none'}, profile {profile}, "
                    f"leaving {margin} MiB of VRAM free)")
        error = _try_load(model, args)
        if error and mmproj:
            # a vision file that does not fit this model or this llama.cpp: keep the text side working
            logger.warning(f"H3 I2V Director: loading with {mmproj} failed ({error}); trying without vision")
            unload_model()
            margin = sysinfo.fit_margin_mb(profile, budget, 0, sysinfo.gpu_info())
            if not _try_load(model, sysinfo.load_args("", params["ctx_size"], margin)):
                vision_note = (f" ⚠️ The vision file `{mmproj}` did not load ({error}), so pictures cannot be read: "
                               "pick another mmproj file in the list (it must come from the same Inkling 2 Mini "
                               "upload) and press *Load Inkling*.")
                mmproj = ""
                error = None
        if error:
            hint = ""
            if "inkling" in error.lower() or "architecture" in error.lower() or not _override["path"]:
                hint = (f" TextGen's built-in llama.cpp is too old for Inkling 2: put a llama.cpp release "
                        f"(b{MIN_LLAMA_BUILD} or newer) in `user_data/llama-cpp/` and restart TextGen, "
                        "or run the setup script again.")
            return f"❌ Loading failed: {error}.{hint}"
    finally:
        _load_lock.release()
    where = (f"VRAM budget {budget:g} GB, the rest in system RAM" if profile == "fit"
             else "as much as fits on the GPU")
    _loaded.update(profile=where, model=model)
    return (f"✅ Loaded `{model}` with {'`' + mmproj + '`' if mmproj else 'no mmproj (no vision)'} · {where}."
            + vision_note)


def _try_load(model, args):
    """Load through TextGen. None on success, else a short error text."""
    from modules.api.models import _load_model

    try:
        _load_model({"model_name": model, "args": args})
    except Exception as exc:
        logger.exception("H3 I2V Director: model load failed")
        return f"{type(exc).__name__}: {exc}"
    if shared.model is None:
        return "llama-server did not start (see the TextGen console)"
    return None


def unload_inkling():
    from modules.models import unload_model

    unload_model()
    return "Model unloaded; its GPU memory is free again."


def _ui_is_up(timeout=180):
    """Wait until TextGen's web interface is built and serving (loading a model while TextGen is still
    building its interface mixes up TextGen's own page-load events)."""
    import socket

    if getattr(shared.args, "nowebui", False):
        return True
    port = int(getattr(shared.args, "listen_port", None) or 7860)
    host = getattr(shared.args, "listen_host", None) or "127.0.0.1"
    host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    end = time.time() + timeout
    while time.time() < end:
        if "interface" in getattr(shared, "gradio", {}):
            try:
                with socket.create_connection((host, port), timeout=1):
                    return True
            except OSError:
                pass
        time.sleep(1)
    return False


def _autoload():
    try:
        _ui_is_up()
        time.sleep(1)
        if shared.model is None:
            logger.info("H3 I2V Director: " + load_inkling())
    finally:
        _autoload_pending.clear()


# --------------------------------------------------------------------------------------
# Talking to the model
# --------------------------------------------------------------------------------------

IMAGE_PATCH = 28  # pixels per vision token side (conservative estimate for Inkling 2's encoder)


def _image_data_uri(img, max_side):
    """(data URI, estimated vision tokens)"""
    from PIL import Image

    img = img.convert("RGB")
    w, h = img.size
    scale = min(1.0, float(max_side) / max(w, h))
    if scale < 1.0:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    w, h = img.size
    tokens = -(-w // IMAGE_PATCH) * -(-h // IMAGE_PATCH)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"), tokens


def _openai_messages(system, turns, uris):
    messages = [{"role": "system", "content": system}] if system else []
    pending = list(uris)
    for turn in turns:
        if turn[0] == "user":
            n = int(turn[2])
            take, pending = pending[:n], pending[n:]
            if take:
                content = [{"type": "image_url", "image_url": {"url": u}} for u in take]
                content.append({"type": "text", "text": turn[1]})
            else:
                content = turn[1]
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "assistant", "content": turn[1]})
    return messages


def _model_vram_mb():
    process = getattr(shared.model, "process", None)
    pid = getattr(process, "pid", None)
    return sysinfo.process_vram_mb(pid) if pid else None


def model_status():
    gpu = sysinfo.gpu_summary(model_vram_mb=_model_vram_mb() if shared.model is not None else None)
    if params["backend"] == "openai":
        return f"Backend: server at `{_api_base(params['api_url'])}`  \n{gpu}"
    name = shared.model_name if shared.model_name not in (None, "None") and shared.model is not None else None
    if not name and (_load_lock.locked() or _autoload_pending.is_set()):
        return f"Backend: TextGen · ⏳ **loading Inkling…** (this line updates by itself)  \n{gpu}"
    if not name:
        return f"Backend: TextGen · **no model loaded** (use *Load Inkling* below)  \n{gpu}"
    vision = "vision on" if getattr(shared, "is_multimodal", False) else "**no vision** (load it with its mmproj file)"
    fmt = "Inkling native format" if core.is_inkling(name, shared.settings.get("instruction_template_str", "")) else "model's chat template"
    moe = f" · {_loaded['profile']}" if _loaded["profile"] and name == _loaded.get("model") else ""
    return f"Backend: TextGen · `{name}` · {vision} · {fmt}{moe}  \n{gpu}"


def _context_size():
    return int(getattr(shared.model, "n_ctx", 0) or shared.settings.get("truncation_length", 0) or 0)


def _fit_max_tokens(used, wanted):
    """Keep prompt + answer inside the loaded context (TextGen would otherwise cut the prompt's start)."""
    ctx = _context_size()
    if ctx <= 0:
        return int(wanted)
    room = ctx - used - 32
    if room < 400:
        raise H3Error(f"The request needs about {used} tokens, but the model was loaded with a context of {ctx}. "
                      "Load it with *Load Inkling* in *Model and GPU* (12k context), or shorten the idea.")
    return min(int(wanted), room)


def _llama_server_stream(prompt, uris, image_tokens, cfg):
    """Raw Inkling prompt straight to the llama-server TextGen started for the loaded model.

    A fresh connection per request, the exact prompt (TextGen's own prompt handling
    would truncate or re-template it), images as multimodal_data.
    """
    base = f"http://127.0.0.1:{shared.model.port}"
    marker = getattr(shared.model, "media_marker", None) or core.MEDIA_MARKER
    with requests.Session() as session:
        if uris and marker == core.MEDIA_MARKER:
            # newer llama.cpp picks a random picture marker; TextGen normally reads it at load time
            try:
                marker = session.get(f"{base}/props", timeout=10).json().get("media_marker") or marker
            except (requests.RequestException, ValueError):
                pass
        tok = session.post(f"{base}/tokenize", json={"content": prompt, "add_special": False, "parse_special": True},
                           timeout=60)
        tok.raise_for_status()
        max_tokens = _fit_max_tokens(len(tok.json().get("tokens", [])) + image_tokens, cfg["max_tokens"])

        text_prompt = prompt.replace(core.MEDIA_MARKER, marker)
        payload = {
            "prompt": ({"prompt_string": text_prompt, "multimodal_data": [u.split(",", 1)[1] for u in uris]}
                       if uris else text_prompt),
            "n_predict": max_tokens,
            "temperature": float(cfg["temperature"]),
            "top_p": float(cfg["top_p"]),
            "min_p": float(cfg["min_p"]),
            "top_k": 0,
            "repeat_penalty": 1.0,
            "stream": True,
            "cache_prompt": True,
        }
        resp = session.post(f"{base}/completion", json=payload, stream=True, timeout=(10, 900))
        with resp:
            if resp.status_code >= 400:
                raise H3Error(f"llama-server answered {resp.status_code}: {resp.text[:600]}")
            text = ""
            for line in resp.iter_lines():
                if _stop.is_set():
                    break
                if not line:
                    continue
                line = line.decode("utf-8", errors="replace")
                if line.startswith("data: "):
                    line = line[6:]
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("content"):
                    text += data["content"]
                    yield "", text
                if data.get("stop"):
                    break


def _textgen_stream(system, turns, uris, cfg, image_tokens=0):
    if (shared.model is None or shared.model_name in (None, "None")) and (_load_lock.locked() or _autoload_pending.is_set()):
        raise H3Error("Inkling is still loading. Wait until the status line at the top shows it, then press Generate again.")
    if shared.model is None or shared.model_name in (None, "None"):
        raise H3Error("No model is loaded. Press *Load Inkling* (in the H3 I2V Director tab it is under *Model and GPU*).")
    if uris and not getattr(shared, "is_multimodal", False):
        raise H3Error("The loaded model can't see pictures: no mmproj (vision file) is loaded. Press *Load Inkling* to "
                      "load it again with its vision file (the file is chosen under *Model and GPU* in the H3 I2V "
                      "Director tab).")

    if core.is_inkling(shared.model_name, shared.settings.get("instruction_template_str", "")):
        if getattr(shared.model, "port", None):
            yield from _llama_server_stream(core.inkling_prompt(system, turns, cfg["thinking"]), uris, image_tokens, cfg)
            return
        raise H3Error("Inkling 2 needs the llama.cpp loader (GGUF). Load the GGUF with the llama.cpp loader, "
                      "or switch Backend to an OpenAI-compatible server.")

    # Any other vision model: TextGen renders the model's own chat template.
    from modules.api import completions as oai
    from modules.api.typing import ChatCompletionRequest
    from modules.text_generation import encode

    rough = "\n".join([system] + [t[1] for t in turns])
    max_tokens = _fit_max_tokens(len(encode(rough)[0]) + image_tokens, cfg["max_tokens"])
    body = ChatCompletionRequest(messages=_openai_messages(system, turns, uris), mode="instruct", stream=True,
                                 enable_thinking=cfg["thinking"] != "off",
                                 reasoning_effort="low" if cfg["thinking"] == "off" else cfg["thinking"],
                                 max_tokens=max_tokens, temperature=float(cfg["temperature"]),
                                 top_p=float(cfg["top_p"]), min_p=float(cfg["min_p"]), top_k=0,
                                 repetition_penalty=1.0).__dict__
    reasoning, answer = "", ""
    for chunk in oai.chat_completions_common(body, stream=True, stop_event=_stop):
        choices = chunk.get("choices") or []
        if choices:
            delta = choices[0].get("delta") or {}
            reasoning += delta.get("reasoning_content") or ""
            answer += delta.get("content") or ""
            yield reasoning, answer


def _api_base(url):
    url = (url or "").strip().rstrip("/")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    return url if url.endswith("/v1") else url + "/v1"


def _openai_stream(system, turns, uris, cfg):
    payload = {
        "messages": _openai_messages(system, turns, uris),
        "stream": True,
        "max_tokens": int(cfg["max_tokens"]),
        "temperature": float(cfg["temperature"]),
        "top_p": float(cfg["top_p"]),
        "min_p": float(cfg["min_p"]),
        "chat_template_kwargs": {"reasoning_effort": core.TEMPLATE_EFFORT.get(cfg["thinking"], "none")},
    }
    if cfg.get("api_model"):
        payload["model"] = cfg["api_model"]
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    url = _api_base(cfg["api_url"]) + "/chat/completions"
    try:
        resp = requests.post(url, json=payload, headers=headers, stream=True, timeout=(10, 900))
    except requests.RequestException as exc:
        raise H3Error(f"Could not reach {url}: {exc}. Is llama-server running?") from exc
    with resp:
        if resp.status_code >= 400:
            raise H3Error(f"{url} answered {resp.status_code}: {resp.text[:600]}")
        resp.encoding = "utf-8"
        reasoning, answer = "", ""
        for raw in resp.iter_lines(decode_unicode=True):
            if _stop.is_set():
                break
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if obj.get("error"):
                raise H3Error(f"Server error: {obj['error']}")
            choices = obj.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                reasoning += delta.get("reasoning_content") or delta.get("reasoning") or ""
                answer += delta.get("content") or ""
                yield reasoning, answer


def _stream(system, turns, images, cfg):
    """images: [(data URI, estimated tokens)]. Yields (reasoning, answer) so far.

    TextGen keeps a pooled connection to its llama-server that can go stale after a
    stream is cut short; one retry with a fresh request covers that.
    """
    uris = [u for u, _ in images]
    for retry in (False, True):
        try:
            if cfg["backend"] == "openai":
                yield from _openai_stream(system, turns, uris, cfg)
            else:
                yield from _textgen_stream(system, turns, uris, cfg, sum(t for _, t in images))
            return
        except requests.ConnectionError as exc:
            if retry or _stop.is_set():
                raise H3Error(f"Lost the connection to the model server: {exc}") from exc
            logger.warning("H3 I2V Director: connection to the model server dropped, retrying once")
            yield "", ""


# --------------------------------------------------------------------------------------
# Gradio callbacks
# --------------------------------------------------------------------------------------

def _cfg(backend_label, api_url, api_key, api_model, thinking, temperature, top_p, min_p, max_tokens,
         auto_repair, save_prompts):
    cfg = {"backend": BACKENDS.get(backend_label, "textgen"), "api_url": api_url, "api_key": api_key,
           "api_model": api_model, "thinking": thinking, "temperature": temperature, "top_p": top_p,
           "min_p": min_p, "max_tokens": max_tokens, "auto_repair": auto_repair, "save_prompts": save_prompts}
    params.update(cfg)  # keep for this session
    return cfg


def _images_for(mode, img1, img2):
    pics = [img1, img2][: core.IMAGES_NEEDED[mode]]
    return [p for p in pics if p is not None]


def _request(mode_label, idea, duration, aspect, shots, camera, amplitude, speed, dialogue, dialogue_language,
             music, music_text, silent, style, notes, n_images):
    mode = MODE_BY_LABEL.get(mode_label, "I2VA")
    music_key = {"Let the model choose": "auto", "No music (N/A)": "none", "Describe it": "custom"}.get(music, "auto")
    return core.Request(
        mode=mode, idea=idea or "", duration=duration, aspect_ratio=aspect,
        shots="auto" if shots == "Auto" else str(shots).split()[0],
        camera="auto" if camera.startswith("Auto") else camera,
        amplitude=amplitude, speed=speed, dialogue=dialogue or "", dialogue_language=dialogue_language or "",
        music=music_key, music_text=music_text or "", silent=bool(silent), style=style or "",
        image_notes=notes or "", n_images=n_images,
    ).clamp()


def _finish(raw_reasoning, raw_answer, req, validate=None):
    reasoning, answer = core.split_reasoning(raw_answer)
    reasoning = "\n\n".join(x for x in (raw_reasoning.strip(), reasoning) if x)
    prompt, discarded = core.extract_prompt(answer)
    if discarded and not reasoning:
        reasoning = discarded
    fixed, notes = core.autofix(prompt, req)
    issues = (validate or core.validate)(fixed, req)
    return fixed, notes, issues, reasoning


def _pipeline(req, encoded, cfg, system=None, message=None, validate=None, checks=None):
    """Write the prompt, check it, and let the model fix it once if needed.

    Other tabs (the POV tab) pass their own rules (system), request text (message) and
    check functions (validate(prompt, req) -> issues, checks(prompt, req) -> checks).

    Yields ("progress", label, answer, reasoning) while the model writes, then
    ("done", prompt, notes, issues, checks, thinking) or ("stopped", answer, reasoning).
    """
    system = system or core.load_system_prompt()
    checks = checks or core.fidelity
    turns = [("user", message or core.build_user_message(req), len(encoded))]
    best, best_score = None, None
    for attempt in (1, 2):
        label = "Writing the H3 prompt" if attempt == 1 else "Fixing the prompt (second pass)"
        reasoning, answer = "", ""
        yield ("progress", label, answer, reasoning)
        for reasoning, answer in _stream(system, turns, encoded, cfg):
            yield ("progress", label, answer, reasoning)
        if _stop.is_set():
            yield ("stopped", answer, reasoning)
            return
        fixed, notes, issues, thoughts = _finish(reasoning, answer, req, validate)
        found = checks(fixed, req)
        score = sum(i.level == "error" for i in issues) + sum(c.repair and not c.ok for c in found)
        if best is None or score < best_score:
            best, best_score = (fixed, notes, issues, found, thoughts), score
        if score == 0 or not cfg["auto_repair"] or attempt == 2:
            break
        turns = turns + [("assistant", fixed), ("user", core.build_fix_message(issues, found), 0)]
    yield ("done", *best)


def _save(prompt, req):
    folder = Path(shared.user_data_dir) / "logs" / "h3_prompts"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"{stamp}_{req.mode}_{req.duration}s.txt"
    path.write_text(prompt + "\n", encoding="utf-8")
    meta = {k: getattr(req, k) for k in ("mode", "idea", "duration", "aspect_ratio", "shots", "camera", "amplitude",
                                         "speed", "dialogue", "music", "music_text", "silent", "style")}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def generate(mode_label, img1, img2, idea, duration, aspect, shots, camera, amplitude, speed, dialogue,
             dialogue_language, music, music_text, silent, style, notes,
             backend_label, api_url, api_key, api_model, thinking, temperature, top_p, min_p, max_tokens,
             auto_repair, save_prompts):
    """Yields (prompt, report, thinking, status)."""
    _stop.clear()
    cfg = _cfg(backend_label, api_url, api_key, api_model, thinking, temperature, top_p, min_p, max_tokens,
               auto_repair, save_prompts)
    mode = MODE_BY_LABEL.get(mode_label, "I2VA")
    images = _images_for(mode, img1, img2)
    needed = core.IMAGES_NEEDED[mode]
    if len(images) < needed and not (notes or "").strip():
        which = "both pictures (first and last frame)" if needed == 2 else "the picture"
        yield gr.update(), "", "", f"❌ Add {which} first, or describe the picture in *Picture notes*."
        return
    if not (idea or "").strip() and mode == "T2VA":
        yield gr.update(), "", "", "❌ Describe the video you want in *Your idea*."
        return

    blind = bool(images and cfg["backend"] == "textgen" and shared.model is not None
                 and not getattr(shared, "is_multimodal", False))
    req = _request(mode_label, idea, duration, aspect, shots, camera, amplitude, speed, dialogue, dialogue_language,
                   music, music_text, silent, style, notes, 0 if blind else len(images))
    if blind and not (notes or "").strip():
        yield gr.update(), "", "", ("❌ Inkling is loaded without its vision file, so it can't see the picture. Open "
                                    "*Model and GPU* above, pick the mmproj file and press *Load Inkling*, or describe "
                                    "the picture in *Picture notes*.")
        return
    try:
        # without vision, the picture notes stand in for the picture (it is still Picture 1 in the prompt)
        encoded = [] if blind else [_image_data_uri(img, params["max_image_side"]) for img in images]
        last, result = 0.0, None
        for event in _pipeline(req, encoded, cfg):
            if event[0] == "progress":
                _, label, answer, reasoning = event
                if time.time() - last > 0.2:
                    last = time.time()
                    yield core.split_reasoning(answer)[1], "", reasoning, f"⏳ {label}… {len(answer.split())} words"
            elif event[0] == "stopped":
                yield core.split_reasoning(event[1])[1], "", event[2], "⏹ Stopped."
                return
            else:
                result = event[1:]
        fixed, fix_notes, issues, checks, thoughts = result
        report = core.report_markdown(issues, fix_notes, fixed, checks)
        if any(i.level == "error" for i in issues):
            status = ("⚠️ Finished, but the format check still finds problems (see below). Generate again, set "
                      "Thinking to low, or edit the prompt and press Re-check.")
        elif any(not c.ok for c in checks):
            status = "✅ Done; see *Matches your request* below for points to look at."
        else:
            status = "✅ Done. Copy the prompt with the button in its top-right corner."
        if cfg["save_prompts"] and fixed.strip():
            path = _save(fixed, req)
            status += f" Saved to `{path}`."
        yield fixed, report, thoughts, status
    except H3Error as exc:
        yield gr.update(), "", "", f"❌ {exc}"
    except Exception as exc:
        logger.exception("H3 I2V Director failed")
        yield gr.update(), "", "", f"❌ {type(exc).__name__}: {exc}"


def describe(mode_label, img1, img2, backend_label, api_url, api_key, api_model, thinking, temperature, top_p,
             min_p, max_tokens, auto_repair, save_prompts):
    """Yields (picture notes, status)."""
    _stop.clear()
    cfg = _cfg(backend_label, api_url, api_key, api_model, thinking, temperature, top_p, min_p, max_tokens,
               auto_repair, save_prompts)
    cfg = dict(cfg, thinking="off", temperature=0.3)
    mode = MODE_BY_LABEL.get(mode_label, "I2VA")
    images = _images_for(mode, img1, img2) or [p for p in (img1, img2) if p is not None]
    if not images:
        yield gr.update(), "❌ Add a picture first."
        return
    try:
        encoded = [_image_data_uri(img, params["max_image_side"]) for img in images]
        turns = [("user", core.build_describe_message(len(encoded)), len(encoded))]
        text, last = "", 0.0
        for _, text in _stream(core.DESCRIBE_SYSTEM_PROMPT, turns, encoded, cfg):
            if time.time() - last > 0.2:
                last = time.time()
                yield core.split_reasoning(text)[1], "⏳ Looking at the picture…"
        yield core.split_reasoning(text)[1], ("⏹ Stopped." if _stop.is_set() else
                                              "✅ This is what the model sees. Fix anything wrong; these notes go into the prompt.")
    except H3Error as exc:
        yield gr.update(), f"❌ {exc}"
    except Exception as exc:
        logger.exception("H3 I2V Director: describe failed")
        yield gr.update(), f"❌ {type(exc).__name__}: {exc}"


def recheck(prompt, mode_label, img1, img2, idea, duration, aspect, shots, camera, amplitude, speed, dialogue,
            dialogue_language, music, music_text, silent, style, notes):
    req = _request(mode_label, idea, duration, aspect, shots, camera, amplitude, speed, dialogue, dialogue_language,
                   music, music_text, silent, style, notes, 0)
    fixed, fix_notes = core.autofix(prompt or "", req)
    return fixed, core.report_markdown(core.validate(fixed, req), fix_notes, fixed, core.fidelity(fixed, req))


def run_selftest(img1, backend_label, api_url, api_key, api_model, thinking, temperature, top_p, min_p, max_tokens,
                 auto_repair, save_prompts):
    """Runs the built-in basic prompts through the model. Yields (summary, details)."""
    _stop.clear()
    cfg = _cfg(backend_label, api_url, api_key, api_model, thinking, temperature, top_p, min_p, max_tokens,
               auto_repair, save_prompts)
    cfg = dict(cfg, save_prompts=False)
    encoded = [_image_data_uri(img1, params["max_image_side"])] if img1 is not None else []
    results = []
    for case in selftest.CASES:
        if _stop.is_set():
            break
        if case.needs_picture and not encoded:
            results.append(selftest.Result(case, skipped="add a picture as Picture 1 to run this one"))
            continue
        yield selftest.summary_markdown(results) + f"\n\n⏳ Running **{case.name}**…", selftest.details_text(results)
        req = selftest.make_request(case, n_images=len(encoded) if case.needs_picture else 0)
        try:
            outcome = None
            for event in _pipeline(req, encoded if case.needs_picture else [], cfg):
                if event[0] == "done":
                    outcome = event
            if outcome is None:
                results.append(selftest.Result(case, error="stopped"))
                continue
            _, prompt, _notes, issues, checks, _thoughts = outcome
            results.append(selftest.Result(case, prompt, issues, checks))
        except H3Error as exc:
            results.append(selftest.Result(case, error=str(exc)))
            if "No model is loaded" in str(exc) or "Could not reach" in str(exc):
                break
        except Exception as exc:
            logger.exception("H3 I2V Director: self-test case failed")
            results.append(selftest.Result(case, error=f"{type(exc).__name__}: {exc}"))
    yield selftest.summary_markdown(results), selftest.details_text(results)


def stop():
    _stop.set()
    shared.stop_everything = True


def save_settings(backend_label, api_url, api_key, api_model, thinking, temperature, top_p, min_p, max_tokens,
                  auto_repair, save_prompts, llama_server_path, model_file, mmproj_file, profile_label, budget,
                  autoload):
    _cfg(backend_label, api_url, api_key, api_model, thinking, temperature, top_p, min_p, max_tokens, auto_repair,
         save_prompts)
    params["llama_server_path"] = (llama_server_path or "").strip()
    params["model_file"] = model_file or ""
    params["mmproj_file"] = mmproj_file or ""
    params["gpu_profile"] = PROFILE_BY_LABEL.get(profile_label, sysinfo.DEFAULT_PROFILE)
    params["vram_budget_gb"] = float(budget)
    params["autoload"] = bool(autoload)
    SETTINGS_FILE.write_text(json.dumps({k: params[k] for k in SAVED_KEYS}, indent=2), encoding="utf-8")
    msg = f"Saved to `{SETTINGS_FILE}`."
    path = _find_llama_server()
    if path:
        _use_llama_server(path)
        msg += f" llama-server: `{path}` (used the next time you load a model)."
    elif params["llama_server_path"]:
        msg += " ⚠️ No llama-server found at that path."
    return msg


# --------------------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------------------

def ui():
    gr.Markdown(
        "### H3 I2V Director\n"
        "Write what should happen in plain words, add the picture, press **Generate**. "
        "The vision model looks at the picture and writes a MiniMax H3 prompt in the official format."
    )
    status_model = gr.Markdown(model_status())

    models, mmprojs = _available_files()
    chosen_model, chosen_mmproj = _chosen_files()
    with gr.Accordion("Model and GPU", open=shared.model is None and not params.get("autoload")):
        with gr.Row():
            model_file = gr.Dropdown(models, value=chosen_model or None, label="Inkling 2 GGUF (user_data/models)")
            mmproj_file = gr.Dropdown(mmprojs, value=chosen_mmproj or None, label="Vision file / mmproj (user_data/mmproj)")
        gpu_profile = gr.Radio(list(sysinfo.PROFILES.values()),
                               value=sysinfo.PROFILES[sysinfo.resolve_profile(params["gpu_profile"])],
                               label="GPU profile")
        vram_budget = gr.Slider(2, 15, value=params["vram_budget_gb"], step=0.5,
                                label="VRAM budget for Inkling in GB (Fit profile; model + vision + context)",
                                info="16 GB card with Fooocus open: about 6.5. Watch 'Inkling uses' in the status line.")
        with gr.Row():
            load_btn = gr.Button("Load Inkling", variant="primary")
            unload_btn = gr.Button("Unload (free the GPU)")
            refresh_files_btn = gr.Button("Refresh lists")
        autoload = gr.Checkbox(params["autoload"], label="Load automatically when TextGen starts (saved with 'Save settings')")
        load_status = gr.Markdown("")

    with gr.Row():
        with gr.Column(scale=5):
            mode = gr.Radio(list(core.MODE_LABELS.values()), value=core.MODE_LABELS["I2VA"], label="Mode")
            with gr.Row():
                img1 = gr.Image(type="pil", label="Picture 1 (first frame)", sources=["upload", "clipboard"], height=280)
                img2 = gr.Image(type="pil", label="Picture 2 (last frame)", sources=["upload", "clipboard"], height=280,
                                visible=False)
            idea = gr.Textbox(label="Your idea", lines=4,
                              placeholder="e.g. she turns to the window and smiles as the train starts moving, rain on the glass")
            with gr.Row():
                duration = gr.Slider(core.MIN_SECONDS, core.MAX_SECONDS, value=5, step=1, label="Duration (seconds)")
                shots = gr.Dropdown(["Auto", "1 (one continuous shot)", "2", "3", "4"], value="Auto", label="Shots")
                aspect = gr.Dropdown(["adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"], value="adaptive",
                                     label="Aspect ratio")
            with gr.Row():
                camera = gr.Dropdown(["Auto (model chooses)"] + list(core.CAMERA_MOVES), value="Auto (model chooses)",
                                     label="Camera")
                amplitude = gr.Dropdown(["auto", "small", "medium", "large"], value="auto", label="Amplitude")
                speed = gr.Dropdown(["auto", "slow", "normal", "fast"], value="auto", label="Speed")
            with gr.Accordion("Dialogue, sound and style", open=False):
                dialogue = gr.Textbox(label="Spoken lines (kept word for word)", lines=3,
                                      placeholder="Woman: I get off at the next station.\nMan: Then I'll wait.")
                dialogue_language = gr.Textbox(label="Dialogue language tag", placeholder="English (empty = from the lines)")
                with gr.Row():
                    music = gr.Radio(["Let the model choose", "No music (N/A)", "Describe it"],
                                     value="Let the model choose", label="Background music")
                    silent = gr.Checkbox(False, label="Complete silence (no sound at all)")
                music_text = gr.Textbox(label="Music description", placeholder="slow solo piano that swells at the end",
                                        visible=False)
                style = gr.Textbox(label="Style (optional)",
                                   placeholder="Leave empty to take the style from the picture. e.g. 2D anime, vintage film")
            with gr.Accordion("Picture notes (what the model sees)", open=False):
                notes = gr.Textbox(label="Picture notes", lines=8,
                                   placeholder="Press 'Describe picture' to see what the model reads from the image. "
                                               "Correct mistakes here; the notes are added to the request.")
                with gr.Row():
                    describe_btn = gr.Button("👁 Describe picture")
                    clear_notes = gr.Button("Clear notes")
                describe_status = gr.Markdown("")
            with gr.Row():
                generate_btn = gr.Button("Generate H3 prompt", variant="primary")
                stop_btn = gr.Button("Stop", variant="stop")
            status = gr.Markdown("")

        with gr.Column(scale=5):
            prompt = gr.Textbox(label="H3 prompt (paste into MiniMax H3 / Hailuo 3)", lines=24, max_lines=60,
                                show_copy_button=True, interactive=True)
            report = gr.Markdown("")
            recheck_btn = gr.Button("Re-check / fix the prompt above")
            with gr.Accordion("Model thinking", open=False):
                thinking_box = gr.Textbox(label="Thinking / discarded text", lines=8, interactive=False)

    with gr.Accordion("🧪 Self-test: check the loaded model against the H3 rules", open=False):
        gr.Markdown(
            "Runs basic plain-language ideas through the model, exactly like *Generate*, and checks every answer "
            "against the official H3 format and against what was asked (camera, shots, dialogue word for word, "
            "silence, music). Text-only tests always run; the picture tests use *Picture 1* if you added one. "
            "Takes a few minutes."
        )
        selftest_btn = gr.Button("Run self-test")
        selftest_summary = gr.Markdown("")
        selftest_details = gr.Textbox(label="Prompts and findings", lines=14, interactive=False, show_copy_button=True)

    with gr.Accordion("Model and backend settings", open=False):
        with gr.Row():
            backend = gr.Radio(list(BACKENDS), value=BACKEND_LABEL.get(params["backend"], "TextGen (loaded model)"),
                               label="Backend")
            thinking = gr.Dropdown(list(core.THINKING_LEVELS), value=params["thinking"],
                                   label="Thinking (off = fastest; low/medium can follow complex ideas better)")
        with gr.Row():
            api_url = gr.Textbox(params["api_url"], label="Server URL (OpenAI-compatible, e.g. llama-server)")
            api_key = gr.Textbox(params["api_key"], label="API key (if the server needs one)", type="password")
            api_model = gr.Textbox(params["api_model"], label="Model name (optional)")
        with gr.Row():
            temperature = gr.Slider(0.0, 1.5, value=params["temperature"], step=0.05, label="temperature")
            top_p = gr.Slider(0.0, 1.0, value=params["top_p"], step=0.01, label="top_p")
            min_p = gr.Slider(0.0, 0.5, value=params["min_p"], step=0.01, label="min_p")
            max_tokens = gr.Slider(256, 8192, value=params["max_tokens"], step=64, label="max tokens")
        with gr.Row():
            auto_repair = gr.Checkbox(params["auto_repair"], label="Auto-repair: ask the model again if the format is broken")
            save_prompts = gr.Checkbox(params["save_prompts"], label="Save every prompt to user_data/logs/h3_prompts")
        llama_server_path = gr.Textbox(
            params["llama_server_path"],
            label="Newer llama-server for TextGen (file or folder; empty = auto-detect user_data/llama-cpp/)")
        with gr.Row():
            save_btn = gr.Button("Save settings")
            refresh_btn = gr.Button("Refresh model status")
        save_status = gr.Markdown("")

    # visibility
    mode.change(lambda m: gr.update(visible=MODE_BY_LABEL.get(m) == "FL2VA"), mode, img2, queue=False)
    mode.change(lambda m: gr.update(label="Picture 1 (last frame)" if MODE_BY_LABEL.get(m) == "L2VA" else
                                    "Picture 1 (first frame)", visible=MODE_BY_LABEL.get(m) != "T2VA"), mode, img1,
                queue=False)
    music.change(lambda m: gr.update(visible=m == "Describe it"), music, music_text, queue=False)

    settings_inputs = [backend, api_url, api_key, api_model, thinking, temperature, top_p, min_p, max_tokens,
                       auto_repair, save_prompts]
    request_inputs = [mode, img1, img2, idea, duration, aspect, shots, camera, amplitude, speed, dialogue,
                      dialogue_language, music, music_text, silent, style, notes]

    generate_btn.click(generate, request_inputs + settings_inputs, [prompt, report, thinking_box, status]).then(
        model_status, None, status_model, queue=False)
    describe_btn.click(describe, [mode, img1, img2] + settings_inputs, [notes, describe_status]).then(
        model_status, None, status_model, queue=False)
    clear_notes.click(lambda: "", None, notes, queue=False)
    stop_btn.click(stop, None, None, queue=False)
    selftest_btn.click(run_selftest, [img1] + settings_inputs, [selftest_summary, selftest_details])
    recheck_btn.click(recheck, [prompt] + request_inputs, [prompt, report])
    save_btn.click(save_settings, settings_inputs + [llama_server_path, model_file, mmproj_file, gpu_profile,
                                                     vram_budget, autoload], save_status)

    def _load(model, mmproj, profile_label, budget):
        params["gpu_profile"] = PROFILE_BY_LABEL.get(profile_label, sysinfo.DEFAULT_PROFILE)
        params["vram_budget_gb"] = float(budget)
        return load_inkling(model or "", mmproj or "", params["gpu_profile"], params["vram_budget_gb"])

    def _refresh_files():
        models, mmprojs = _available_files()
        model, mmproj = _chosen_files()
        return gr.update(choices=models, value=model or None), gr.update(choices=mmprojs, value=mmproj or None)

    load_btn.click(lambda: "⏳ Loading… (a 10 GB model takes a little while)", None, load_status, queue=False).then(
        _load, [model_file, mmproj_file, gpu_profile, vram_budget], load_status).then(model_status, None, status_model, queue=False)
    unload_btn.click(unload_inkling, None, load_status).then(model_status, None, status_model, queue=False)
    refresh_files_btn.click(_refresh_files, None, [model_file, mmproj_file]).then(
        model_status, None, status_model, queue=False)
    refresh_btn.click(model_status, None, status_model, queue=False)
    # keep the status line current (Inkling loads in the background at start-up), without a busy indicator
    interface = shared.gradio.get("interface") if isinstance(getattr(shared, "gradio", None), dict) else None
    if interface is not None:
        interface.load(model_status, None, status_model, every=10, show_progress="hidden")
    backend.change(lambda b: (params.update(backend=BACKENDS.get(b, "textgen")), model_status())[1], backend, status_model,
                   queue=False)
