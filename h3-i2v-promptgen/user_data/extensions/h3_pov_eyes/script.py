"""H3 POV: her eyes. A separate TextGen tab that writes MiniMax H3 image-to-video prompts in which
the camera is the girl's eyes: the picture shows her and the video snaps into her point of view,
or the picture is already her view and the camera stays at her eyes.

It uses the same model, settings and checks as the H3 I2V Director tab (h3_i2v_director); only
the rules for the model (pov_system_prompt.md) and the POV checks (pov_core.py) are its own.

Enable with --extensions h3_i2v_director h3_pov_eyes (or in the Session tab).
"""

import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import gradio as gr

from modules import shared
from modules.logging_colors import logger

HERE = Path(__file__).resolve().parent
DIRECTOR = "h3_i2v_director"


def _load_local(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pov = _load_local("h3_pov_eyes_core", "pov_core.py")
core = pov.core

params = {
    "display_name": "H3 POV: her eyes",
    "is_tab": True,
}

_engine_ref = {"module": None}


def _engine():
    """The H3 I2V Director's script module: model connection, settings, picture handling, repair loop.

    TextGen loads it as user_ext_h3_i2v_director when that tab is enabled; if only this tab is
    enabled, it is loaded here once and set up the same way (settings, newer llama-server, auto-load)."""
    if _engine_ref["module"] is not None:
        return _engine_ref["module"]
    module = sys.modules.get(f"user_ext_{DIRECTOR}")
    if module is None:
        path = HERE.parent / DIRECTOR / "script.py"
        spec = importlib.util.spec_from_file_location(f"user_ext_{DIRECTOR}", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.setup()
        logger.info("H3 POV: the H3 I2V Director tab is off; using its model loader and settings from here")
    _engine_ref["module"] = module
    return module


def setup():
    # With the director enabled, TextGen sets it up itself (it may come after this tab in the list).
    if DIRECTOR not in (getattr(shared.args, "extensions", None) or []):
        _engine()


# --------------------------------------------------------------------------------------
# Callbacks
# --------------------------------------------------------------------------------------

MODE_BY_LABEL = {v: k for k, v in pov.MODES.items()}
HEAD_BY_LABEL = {v[0]: k for k, v in pov.HEAD.items()}
HANDS_BY_LABEL = {v[0]: k for k, v in pov.HANDS.items()}
MUSIC_BY_LABEL = {"Let the model choose": "auto", "No music (N/A)": "none", "Describe it": "custom"}


def _cfg():
    """The model and backend settings of the H3 I2V Director tab (shared)."""
    e = _engine()
    keys = ("backend", "api_url", "api_key", "api_model", "thinking", "temperature", "top_p", "min_p", "max_tokens",
            "auto_repair", "save_prompts")
    return {k: e.params[k] for k in keys}


def _request(mode_label, who, snap_at, idea, duration, head, hands, dialogue, dialogue_language, music, music_text,
             silent, style, notes, n_images):
    try:
        snap = float(str(snap_at).split()[0])
    except (ValueError, IndexError):
        snap = 1.0
    return pov.PovRequest(
        idea=idea or "", mode=MODE_BY_LABEL.get(mode_label, "snap"), who=who or "girl", snap_at=snap,
        duration=duration, head=HEAD_BY_LABEL.get(head, "steady"), hands=HANDS_BY_LABEL.get(hands, "auto"),
        dialogue=dialogue or "", dialogue_language=dialogue_language or "", music=MUSIC_BY_LABEL.get(music, "auto"),
        music_text=music_text or "", silent=bool(silent), style=style or "", image_notes=notes or "",
        n_images=n_images,
    ).clamp()


def _run(preq, encoded, cfg):
    """The director's write -> check -> repair loop with the POV rules and checks."""
    e = _engine()
    return e._pipeline(preq.core_request(), encoded, cfg, system=pov.load_system_prompt(),
                       message=pov.build_user_message(preq),
                       validate=lambda prompt, _req: pov.validate(prompt, preq),
                       checks=lambda prompt, _req: pov.checks(prompt, preq))


def _save(prompt, preq):
    folder = Path(shared.user_data_dir) / "logs" / "h3_prompts"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"{stamp}_POV-{preq.mode}_{preq.duration}s.txt"
    path.write_text(prompt + "\n", encoding="utf-8")
    meta = {k: getattr(preq, k) for k in ("mode", "who", "snap_at", "idea", "duration", "head", "hands", "dialogue",
                                          "music", "music_text", "silent", "style")}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def generate(img1, mode_label, who, snap_at, idea, duration, head, hands, dialogue, dialogue_language, music,
             music_text, silent, style, notes):
    """Yields (prompt, report, thinking, status)."""
    e = _engine()
    e._stop.clear()
    cfg = _cfg()
    if img1 is None and not (notes or "").strip():
        yield gr.update(), "", "", "❌ Add the picture first, or describe it in *Picture notes*."
        return
    blind = bool(img1 is not None and cfg["backend"] == "textgen" and shared.model is not None
                 and not getattr(shared, "is_multimodal", False))
    if blind and not (notes or "").strip():
        yield gr.update(), "", "", ("❌ Inkling is loaded without its vision file, so it can't see the picture. Load it "
                                    "with its mmproj file (*Load Inkling* in the H3 I2V Director tab), or describe the "
                                    "picture in *Picture notes*.")
        return
    preq = _request(mode_label, who, snap_at, idea, duration, head, hands, dialogue, dialogue_language, music,
                    music_text, silent, style, notes, 0 if (blind or img1 is None) else 1)
    try:
        encoded = [] if (blind or img1 is None) else [e._image_data_uri(img1, e.params["max_image_side"])]
        last, result = 0.0, None
        for event in _run(preq, encoded, cfg):
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
        fixed, fix_notes, issues, found, thoughts = result
        report = pov.report_markdown(issues, fix_notes, fixed, found)
        if any(i.level == "error" for i in issues):
            status = ("⚠️ Finished, but the format check still finds problems (see below). Generate again, or edit "
                      "the prompt and press Re-check.")
        elif any(not c.ok for c in found):
            status = "✅ Done; see *Matches your request* below for points to look at."
        else:
            status = "✅ Done. Copy the prompt with the button in its top-right corner."
        if cfg["save_prompts"] and fixed.strip():
            status += f" Saved to `{_save(fixed, preq)}`."
        yield fixed, report, thoughts, status
    except e.H3Error as exc:
        yield gr.update(), "", "", f"❌ {exc}"
    except Exception as exc:
        logger.exception("H3 POV failed")
        yield gr.update(), "", "", f"❌ {type(exc).__name__}: {exc}"


def describe(img1):
    """Yields (picture notes, status)."""
    e = _engine()
    e._stop.clear()
    if img1 is None:
        yield gr.update(), "❌ Add the picture first."
        return
    cfg = dict(_cfg(), thinking="off", temperature=0.3)
    try:
        encoded = [e._image_data_uri(img1, e.params["max_image_side"])]
        turns = [("user", core.build_describe_message(1), 1)]
        text, last = "", 0.0
        for _, text in e._stream(core.DESCRIBE_SYSTEM_PROMPT, turns, encoded, cfg):
            if time.time() - last > 0.2:
                last = time.time()
                yield core.split_reasoning(text)[1], "⏳ Looking at the picture…"
        yield core.split_reasoning(text)[1], ("⏹ Stopped." if e._stop.is_set() else
                                              "✅ This is what the model sees. Fix anything wrong; these notes go into the prompt.")
    except e.H3Error as exc:
        yield gr.update(), f"❌ {exc}"
    except Exception as exc:
        logger.exception("H3 POV: describe failed")
        yield gr.update(), f"❌ {type(exc).__name__}: {exc}"


def recheck(prompt, img1, mode_label, who, snap_at, idea, duration, head, hands, dialogue, dialogue_language, music,
            music_text, silent, style, notes):
    preq = _request(mode_label, who, snap_at, idea, duration, head, hands, dialogue, dialogue_language, music,
                    music_text, silent, style, notes, 1)
    fixed, fix_notes = core.autofix(prompt or "", preq.core_request())
    return fixed, pov.report_markdown(pov.validate(fixed, preq), fix_notes, fixed, pov.checks(fixed, preq))


SELFTEST = [
    # ideas that fit any picture of her, so the tests check the POV mechanics, not the picture
    ("snap-look", "snap into the girl's eyes at 1 s, then she looks around slowly",
     dict(mode="snap", snap_at=1.0, head="look", idea="the girl looks around the room slowly")),
    ("snap-walk", "snap at 1.5 s, then she walks forward a few steps",
     dict(mode="snap", snap_at=1.5, head="walk", idea="the girl walks forward a few steps")),
    ("eyes-hands", "the picture is already her view; her hands come into view",
     dict(mode="eyes", head="steady", hands="yes", idea="she raises her hands in front of her and looks at them")),
]


def run_selftest(img1):
    """Yields (summary, details)."""
    e = _engine()
    e._stop.clear()
    if img1 is None:
        yield "❌ Add a picture as Picture 1 first (the POV tests are image to video).", ""
        return
    cfg = dict(_cfg(), save_prompts=False)
    encoded = [e._image_data_uri(img1, e.params["max_image_side"])]
    results = []
    for name, what, kw in SELFTEST:
        if e._stop.is_set():
            break
        case = e.selftest.Case(name, what, {})
        yield e.selftest.summary_markdown(results) + f"\n\n⏳ Running **{name}**…", e.selftest.details_text(results)
        preq = pov.PovRequest(duration=5, n_images=1, **kw).clamp()
        try:
            outcome = None
            for event in _run(preq, encoded, cfg):
                if event[0] == "done":
                    outcome = event
            if outcome is None:
                results.append(e.selftest.Result(case, error="stopped"))
                continue
            _, prompt, _notes, issues, found, _thoughts = outcome
            results.append(e.selftest.Result(case, prompt, issues, found))
        except e.H3Error as exc:
            results.append(e.selftest.Result(case, error=str(exc)))
            if "No model is loaded" in str(exc) or "still loading" in str(exc) or "Could not reach" in str(exc):
                break
        except Exception as exc:
            logger.exception("H3 POV: self-test case failed")
            results.append(e.selftest.Result(case, error=f"{type(exc).__name__}: {exc}"))
    yield e.selftest.summary_markdown(results), e.selftest.details_text(results)


# --------------------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------------------

def ui():
    e = _engine()
    gr.Markdown(
        "### H3 POV: her eyes\n"
        "Image to video where **the camera is the girl's eyes**. Add the picture, say what happens, press "
        "**Generate**. Either the picture shows her and the video **snaps into her eyes**, or the picture is already "
        "her view and the camera stays there. Model and settings are shared with the *H3 I2V Director* tab."
    )
    status_model = gr.Markdown(e.model_status())
    with gr.Row():
        load_btn = gr.Button("Load Inkling", size="sm")
        load_status = gr.Markdown("")

    with gr.Row():
        with gr.Column(scale=5):
            img1 = gr.Image(type="pil", label="Picture 1 (first frame)", sources=["upload", "clipboard"], height=280)
            mode = gr.Radio(list(pov.MODES.values()), value=pov.MODES["snap"], label="What the picture shows")
            with gr.Row():
                who = gr.Textbox("girl", label="Whose eyes (your word for her)", max_lines=1)
                snap_at = gr.Dropdown([f"{t:g} s" for t in pov.SNAP_TIMES], value="1 s",
                                      label="Snap into her eyes at")
                duration = gr.Slider(core.MIN_SECONDS, core.MAX_SECONDS, value=5, step=1, label="Duration (seconds)")
            idea = gr.Textbox(label="Your idea (what happens, what she sees and does)", lines=4,
                              placeholder="e.g. the woman hands the girl a cup and smiles at her")
            with gr.Row():
                head = gr.Dropdown([v[0] for v in pov.HEAD.values()], value=pov.HEAD["steady"][0],
                                   label="Her head (camera movement)")
                hands = gr.Dropdown([v[0] for v in pov.HANDS.values()], value=pov.HANDS["auto"][0],
                                    label="Her hands in view")
            with gr.Accordion("Dialogue, sound and style", open=False):
                dialogue = gr.Textbox(label="Spoken lines (kept word for word; her own lines come from behind the camera)",
                                      lines=3, placeholder="Woman: Careful, it's hot.\nGirl: Thank you!")
                dialogue_language = gr.Textbox(label="Dialogue language tag", placeholder="English (empty = from the lines)")
                with gr.Row():
                    music = gr.Radio(list(MUSIC_BY_LABEL), value="Let the model choose", label="Background music")
                    silent = gr.Checkbox(False, label="Complete silence (no sound at all)")
                music_text = gr.Textbox(label="Music description", visible=False,
                                        placeholder="slow solo piano that swells at the end")
                style = gr.Textbox(label="Style (optional)", placeholder="Leave empty to take the style from the picture")
            with gr.Accordion("Picture notes (what the model sees)", open=False):
                notes = gr.Textbox(label="Picture notes", lines=8,
                                   placeholder="Press 'Describe picture' to see what the model reads from the image. "
                                               "Correct mistakes here; the notes are added to the request.")
                with gr.Row():
                    describe_btn = gr.Button("👁 Describe picture")
                    clear_notes = gr.Button("Clear notes")
                describe_status = gr.Markdown("")
            with gr.Row():
                generate_btn = gr.Button("Generate POV prompt", variant="primary")
                stop_btn = gr.Button("Stop", variant="stop")
            status = gr.Markdown("")

        with gr.Column(scale=5):
            prompt = gr.Textbox(label="H3 POV prompt (paste into MiniMax H3 / Hailuo 3 with the same picture)",
                                lines=24, max_lines=60, show_copy_button=True, interactive=True)
            report = gr.Markdown("")
            recheck_btn = gr.Button("Re-check / fix the prompt above")
            with gr.Accordion("Model thinking", open=False):
                thinking_box = gr.Textbox(label="Thinking / discarded text", lines=8, interactive=False)

    with gr.Accordion("🧪 POV self-test (uses Picture 1)", open=False):
        gr.Markdown("Runs three POV ideas through the model, exactly like *Generate*, and checks every answer: the "
                    "official H3 format, the snap into her eyes at the right time, eye height, her face out of view, "
                    "the people and the action.")
        selftest_btn = gr.Button("Run POV self-test")
        selftest_summary = gr.Markdown("")
        selftest_details = gr.Textbox(label="Prompts and findings", lines=14, interactive=False, show_copy_button=True)

    mode.change(lambda m: gr.update(visible=MODE_BY_LABEL.get(m) == "snap"), mode, snap_at, queue=False)
    music.change(lambda m: gr.update(visible=m == "Describe it"), music, music_text, queue=False)
    request_inputs = [mode, who, snap_at, idea, duration, head, hands, dialogue, dialogue_language, music, music_text,
                      silent, style, notes]
    generate_btn.click(generate, [img1] + request_inputs, [prompt, report, thinking_box, status]).then(
        e.model_status, None, status_model, queue=False)
    describe_btn.click(describe, img1, [notes, describe_status])
    clear_notes.click(lambda: "", None, notes, queue=False)
    stop_btn.click(e.stop, None, None, queue=False)
    recheck_btn.click(recheck, [prompt, img1] + request_inputs, [prompt, report])
    selftest_btn.click(run_selftest, img1, [selftest_summary, selftest_details])
    load_btn.click(lambda: "⏳ Loading… (a 10 GB model takes a little while)", None, load_status, queue=False).then(
        lambda: e.load_inkling(), None, load_status).then(e.model_status, None, status_model, queue=False)
    interface = shared.gradio.get("interface") if isinstance(getattr(shared, "gradio", None), dict) else None
    if interface is not None:
        interface.load(e.model_status, None, status_model, every=10, show_progress="hidden")
