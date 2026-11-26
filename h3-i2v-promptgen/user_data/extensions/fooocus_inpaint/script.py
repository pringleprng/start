"""Fooocus Inpaint: a TextGen tab that writes the prompts for Fooocus's Inpaint or Outpaint tab.

Show the picture, say which area you will mask and what should be there; the vision model writes
the three Fooocus boxes (Prompt, Inpaint Additional Prompt, Negative Prompt) and the tab shows the
settings Fooocus uses for the chosen method. The model, the GPU and the backend settings are shared
with the H3 I2V Director tab.

Enable with --extensions h3_i2v_director fooocus_inpaint (or in the Session tab).
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


fc = _load_local("fooocus_inpaint_core", "fooocus_core.py")
core = fc.core

params = {
    "display_name": "Fooocus Inpaint",
    "is_tab": True,
}

_engine_ref = {"module": None}


def _engine():
    """The H3 I2V Director's script module (model connection, settings, picture handling)."""
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
        logger.info("Fooocus Inpaint: the H3 I2V Director tab is off; using its model loader and settings from here")
    _engine_ref["module"] = module
    return module


def setup():
    if DIRECTOR not in (getattr(shared.args, "extensions", None) or []):
        _engine()


METHOD_BY_LABEL = {fc.AUTO: "auto", **{v: k for k, v in fc.METHODS.items()}}
NEGATIVE_BY_LABEL = {"Write one for this edit": "auto", "No negative prompt": "none"}


def _cfg():
    e = _engine()
    keys = ("backend", "api_url", "api_key", "api_model", "thinking", "temperature", "top_p", "min_p", "max_tokens",
            "auto_repair", "save_prompts")
    return {k: e.params[k] for k in keys}


def _marked(img, mask):
    """The picture with the mask (white = the area Fooocus redraws) shown as a red tint, for the model."""
    from PIL import Image

    img = img.convert("RGB")
    m = mask.convert("L").resize(img.size).point(lambda v: 255 if v > 127 else 0)
    if m.getbbox() is None:
        return img, False   # an all-black mask marks nothing
    tinted = Image.blend(img, Image.new("RGB", img.size, (255, 0, 0)), 0.45)
    return Image.composite(tinted, img, m), True


def _request(method_label, outpaint, area, idea, style, negative, notes, n_images, has_mask):
    return fc.InpaintRequest(idea=idea or "", area=area or "", method=METHOD_BY_LABEL.get(method_label, "default"),
                             outpaint=list(outpaint or []), style=style or "",
                             negative=NEGATIVE_BY_LABEL.get(negative, "auto"), image_notes=notes or "",
                             n_images=n_images, has_mask=has_mask).clamp()


def _run(req, encoded, cfg):
    """Write the three boxes, check them, and let the model fix them once if needed.

    Yields ("progress", label, answer, reasoning), then ("done", fields, notes, issues, checks, thinking)
    or ("stopped", answer, reasoning)."""
    e = _engine()
    system = fc.load_system_prompt()
    turns = [("user", fc.build_user_message(req), len(encoded))]
    best, best_score = None, None
    for attempt in (1, 2):
        label = "Writing the Fooocus prompts" if attempt == 1 else "Fixing the prompts (second pass)"
        reasoning, answer = "", ""
        yield ("progress", label, answer, reasoning)
        for reasoning, answer in e._stream(system, turns, encoded, cfg):
            yield ("progress", label, answer, reasoning)
        if e._stop.is_set():
            yield ("stopped", answer, reasoning)
            return
        more, text = core.split_reasoning(answer)
        thoughts = "\n\n".join(x for x in (reasoning.strip(), more) if x)
        fixed, notes = fc.autofix(fc.parse_answer(text), req)
        issues, found = fc.validate(fixed, req), fc.checks(fixed, req)
        score = sum(i.level == "error" for i in issues) + sum(c.repair and not c.ok for c in found)
        if best is None or score < best_score:
            best, best_score = (fixed, notes, issues, found, thoughts), score
        if score == 0 or not cfg["auto_repair"] or attempt == 2:
            break
        turns = turns + [("assistant", fc.as_text(fixed)), ("user", fc.build_fix_message(issues, found), 0)]
    yield ("done", *best)


def _save(fields, req):
    folder = Path(shared.user_data_dir) / "logs" / "fooocus_prompts"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"{stamp}_{req.method}.txt"
    n = 2
    while path.exists() or path.with_suffix(".json").exists():
        path = path.with_name(f"{path.stem.split('~')[0]}~{n}.txt")
        n += 1
    path.write_text(fc.as_text(fields) + "\n", encoding="utf-8")
    meta = {"method": fc.METHODS[req.method], "outpaint": req.outpaint, "area": req.area, "idea": req.idea,
            "style": req.style, "settings": fc.SETTINGS[req.method]}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _encode(img, mask, blind):
    """([(data URI, tokens)], picture marked with the mask?)"""
    e = _engine()
    if img is None or blind:
        return [], False
    marked = False
    if mask is not None:
        img, marked = _marked(img, mask)
    return [e._image_data_uri(img, e.params["max_image_side"])], marked


def generate(img, mask, method_label, outpaint, area, idea, style, negative, notes):
    """Yields (prompt, additional, negative, settings, report, thinking, status)."""
    e = _engine()
    e._stop.clear()
    cfg = _cfg()
    keep = gr.update()
    if img is None and not (notes or "").strip():
        yield keep, keep, keep, keep, "", "", "❌ Add the picture first, or describe it in *Picture notes*."
        return
    blind = bool(img is not None and cfg["backend"] == "textgen" and shared.model is not None
                 and not getattr(shared, "is_multimodal", False))
    if blind and not (notes or "").strip():
        yield keep, keep, keep, keep, "", "", ("❌ Inkling is loaded without its vision file, so it can't see the "
                                               "picture. Press *Load Inkling* above to load it again with its vision "
                                               "file, or describe the picture in *Picture notes*.")
        return
    stop_reason = fc.blocked_reason(idea, area)
    if stop_reason:
        yield keep, keep, keep, keep, "", "", f"❌ {stop_reason}"
        return
    try:
        encoded, marked = _encode(img, mask, blind)
        req = _request(method_label, outpaint, area, idea, style, negative, notes, len(encoded), marked)
        settings = fc.settings_markdown(req)
        last, result = 0.0, None
        for event in _run(req, encoded, cfg):
            if event[0] == "progress":
                _, label, answer, reasoning = event
                if time.time() - last > 0.2:
                    last = time.time()
                    yield keep, keep, keep, settings, "", reasoning, f"⏳ {label}… {len(answer.split())} words"
            elif event[0] == "stopped":
                yield keep, keep, keep, settings, "", event[2], "⏹ Stopped."
                return
            else:
                result = event[1:]
        fields, fix_notes, issues, found, thoughts = result
        held_back = fc.blocked_output(fields)
        if not held_back and not any(fields.values()) and fc._BODY_RE.search(fc._no_baby_bump(req.idea)):
            held_back = ("The model answered N/A: it sees a girl, boy or child in the masked area, and this tab "
                         "doesn't write sexual, nude, underwear or pregnancy edits for them.")
        if held_back:
            yield "", "", "", settings, "", thoughts, f"❌ {held_back}"
            return
        report = fc.report_markdown(issues, fix_notes, found)
        if any(i.level == "error" for i in issues):
            status = "⚠️ Finished, but the format check still finds problems (see below). Generate again, or edit and press Re-check."
        elif any(not c.ok for c in found):
            status = "✅ Done; see *Matches your request* below for points to look at."
        else:
            status = "✅ Done. Copy each box into Fooocus (copy button in the corner of each box)."
        if cfg["save_prompts"] and (fields["prompt"] or fields["additional"]):
            status += f" Saved to `{_save(fields, req)}`."
        yield (fields["prompt"] or "", fields["additional"] or "", fields["negative"] or "", settings, report,
               thoughts, status)
    except e.H3Error as exc:
        yield keep, keep, keep, keep, "", "", f"❌ {exc}"
    except Exception as exc:
        logger.exception("Fooocus Inpaint failed")
        yield keep, keep, keep, keep, "", "", f"❌ {type(exc).__name__}: {exc}"


def describe(img, mask):
    """Yields (picture notes, status)."""
    e = _engine()
    e._stop.clear()
    if img is None:
        yield gr.update(), "❌ Add the picture first."
        return
    cfg = dict(_cfg(), thinking="off", temperature=0.3)
    try:
        encoded, marked = _encode(img, mask, False)
        message = core.build_describe_message(1)
        if marked:
            message += "\nThe red-tinted part is the area that will be redrawn: describe it in extra detail."
        text, last = "", 0.0
        for _, text in e._stream(core.DESCRIBE_SYSTEM_PROMPT, [("user", message, 1)], encoded, cfg):
            if time.time() - last > 0.2:
                last = time.time()
                yield core.split_reasoning(text)[1], "⏳ Looking at the picture…"
        yield core.split_reasoning(text)[1], ("⏹ Stopped." if e._stop.is_set() else
                                              "✅ This is what the model sees. Fix anything wrong; these notes go into the request.")
    except e.H3Error as exc:
        yield gr.update(), f"❌ {exc}"
    except Exception as exc:
        logger.exception("Fooocus Inpaint: describe failed")
        yield gr.update(), f"❌ {type(exc).__name__}: {exc}"


def recheck(prompt, additional, negative, method_label, outpaint, area, idea, style, neg_choice, notes):
    req = _request(method_label, outpaint, area, idea, style, neg_choice, notes, 1, False)
    fields, fix_notes = fc.autofix({"prompt": prompt, "additional": additional, "negative": negative}, req)
    return (fields["prompt"], fields["additional"], fields["negative"], fc.settings_markdown(req),
            fc.report_markdown(fc.validate(fields, req), fix_notes, fc.checks(fields, req)))


SELFTEST = [
    # ideas that fit most pictures, so the tests check the Fooocus mechanics, not the picture
    ("keywords", "Auto: \"long wavy hair, auburn\" word for word, Inpaint or Outpaint, ADDITIONAL empty",
     dict(method="auto", area="the hair", idea="long wavy hair, auburn")),
    ("detail-face", "Improve Detail: a short detail phrase in ADDITIONAL",
     dict(method="detail", area="the face", idea="sharper face with clear eyes")),
    ("modify-bench", "Modify Content: only the new object in ADDITIONAL, nothing wanted in NEGATIVE",
     dict(method="modify", area="the empty space on the right", idea="add a red wooden bench")),
]


def run_selftest(img):
    """Yields (summary, details)."""
    e = _engine()
    e._stop.clear()
    if img is None:
        yield "❌ Add a picture first (the tests use it like a picture you inpaint).", ""
        return
    cfg = dict(_cfg(), save_prompts=False)
    encoded = [e._image_data_uri(img, e.params["max_image_side"])]
    results = []
    for name, what, kw in SELFTEST:
        if e._stop.is_set():
            break
        case = e.selftest.Case(name, what, {})
        yield e.selftest.summary_markdown(results) + f"\n\n⏳ Running **{name}**…", e.selftest.details_text(results)
        req = fc.InpaintRequest(n_images=1, **kw).clamp()
        try:
            outcome = None
            for event in _run(req, encoded, cfg):
                if event[0] == "done":
                    outcome = event
            if outcome is None:
                results.append(e.selftest.Result(case, error="stopped"))
                continue
            _, fields, _notes, issues, found, _thoughts = outcome
            results.append(e.selftest.Result(case, fc.as_text(fields), issues, found))
        except e.H3Error as exc:
            results.append(e.selftest.Result(case, error=str(exc)))
            if "No model is loaded" in str(exc) or "still loading" in str(exc) or "Could not reach" in str(exc):
                break
        except Exception as exc:
            logger.exception("Fooocus Inpaint: self-test case failed")
            results.append(e.selftest.Result(case, error=f"{type(exc).__name__}: {exc}"))
    yield e.selftest.summary_markdown(results), e.selftest.details_text(results)


def ui():
    e = _engine()
    gr.Markdown(
        "### Fooocus Inpaint\n"
        "Inpainting prompts for Fooocus. Add the picture, say in a few words what the masked area should become "
        "(e.g. *red leather jacket, silver zipper*) and press **Generate**: you get the Fooocus boxes, the method and its "
        "settings, and tips for the mask. Model and settings are shared with the *H3 I2V Director* tab."
    )
    status_model = gr.Markdown(e.model_status())
    with gr.Row():
        load_btn = gr.Button("Load Inkling", size="sm")
        load_status = gr.Markdown("")

    with gr.Row():
        with gr.Column(scale=5):
            with gr.Row():
                img = gr.Image(type="pil", label="Picture (the image you will inpaint)", sources=["upload", "clipboard"],
                               height=280)
                mask = gr.Image(type="pil", label="Mask (optional; white = the area Fooocus redraws)",
                                sources=["upload", "clipboard"], height=280)
            idea = gr.Textbox(label="What the masked area should become (your words)", lines=3,
                              placeholder="e.g. red leather jacket / long wavy hair, auburn / detailed hands / add a cat on the sofa")
            area = gr.Textbox(label="Area you will mask (optional; the model can tell from the picture and your words)",
                              max_lines=1, placeholder="e.g. her jacket, girl shirt, the face, the sky")
            method = gr.Radio([fc.AUTO] + list(fc.METHODS.values()), value=fc.AUTO,
                              label="Method (pick the same one in Fooocus; Auto shows which and why)")
            with gr.Accordion("Outpaint instead (extend the picture past its edges)", open=False):
                outpaint = gr.CheckboxGroup(list(fc.OUTPAINT), value=[], label="Outpaint Direction")
            with gr.Row():
                style = gr.Textbox(label="Style (optional)", placeholder="Leave empty to match the picture")
                negative = gr.Radio(list(NEGATIVE_BY_LABEL), value="Write one for this edit", label="Negative prompt")
            with gr.Accordion("Picture notes (what the model sees)", open=False):
                notes = gr.Textbox(label="Picture notes", lines=6,
                                   placeholder="Press 'Describe picture' to see what the model reads from the image. "
                                               "Correct mistakes here; the notes are added to the request.")
                with gr.Row():
                    describe_btn = gr.Button("👁 Describe picture")
                    clear_notes = gr.Button("Clear notes")
                describe_status = gr.Markdown("")
            with gr.Row():
                generate_btn = gr.Button("Generate Fooocus prompts", variant="primary")
                stop_btn = gr.Button("Stop", variant="stop")
            status = gr.Markdown("")

        with gr.Column(scale=5):
            out_prompt = gr.Textbox(label="Prompt (Fooocus main prompt box)", lines=4, show_copy_button=True,
                                    interactive=True)
            out_additional = gr.Textbox(label="Inpaint Additional Prompt (Improve Detail / Modify Content only)",
                                        lines=2, show_copy_button=True, interactive=True)
            out_negative = gr.Textbox(label="Negative Prompt (Settings tab)", lines=2, show_copy_button=True,
                                      interactive=True)
            settings = gr.Markdown(fc.settings_markdown(fc.InpaintRequest()))
            report = gr.Markdown("")
            recheck_btn = gr.Button("Re-check / fix the boxes above")
            with gr.Accordion("Model thinking", open=False):
                thinking_box = gr.Textbox(label="Thinking", lines=6, interactive=False)

    with gr.Accordion("🧪 Self-test (uses the picture)", open=False):
        gr.Markdown("Runs one idea per Fooocus method through the model, exactly like *Generate*, and checks the "
                    "answers: three one-line boxes, ADDITIONAL filled in only where Fooocus uses it, nothing wanted in "
                    "the negative prompt.")
        selftest_btn = gr.Button("Run self-test")
        selftest_summary = gr.Markdown("")
        selftest_details = gr.Textbox(label="Prompts and findings", lines=12, interactive=False, show_copy_button=True)

    def _settings(m, out, a, i):
        return fc.settings_markdown(_request(m, out, a, i, "", "Write one for this edit", "", 0, False))

    for trigger in (method.change, outpaint.change, idea.blur, area.blur):
        trigger(_settings, [method, outpaint, area, idea], settings, queue=False)
    inputs = [img, mask, method, outpaint, area, idea, style, negative, notes]
    generate_btn.click(generate, inputs, [out_prompt, out_additional, out_negative, settings, report, thinking_box,
                                          status]).then(e.model_status, None, status_model, queue=False)
    describe_btn.click(describe, [img, mask], [notes, describe_status])
    clear_notes.click(lambda: "", None, notes, queue=False)
    stop_btn.click(e.stop, None, None, queue=False)
    recheck_btn.click(recheck, [out_prompt, out_additional, out_negative, method, outpaint, area, idea, style, negative,
                                notes], [out_prompt, out_additional, out_negative, settings, report])
    selftest_btn.click(run_selftest, img, [selftest_summary, selftest_details])
    load_btn.click(lambda: "⏳ Loading… (a 10 GB model takes a little while)", None, load_status, queue=False).then(
        lambda: e.load_inkling(), None, load_status).then(e.model_status, None, status_model, queue=False)
    interface = shared.gradio.get("interface") if isinstance(getattr(shared, "gradio", None), dict) else None
    if interface is not None:
        interface.load(e.model_status, None, status_model, every=10, show_progress="hidden")
