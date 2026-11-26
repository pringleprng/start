"""Core logic of the Fooocus Inpaint tab: prompts for Fooocus's Inpaint or Outpaint tab.

Plain Python with no TextGen imports, so it can be tested on its own. The settings per method are
the ones Fooocus 2.5.5 sets itself when the method is chosen (webui.py, inpaint_mode_change), and
the box handling follows modules/async_worker.py (the additional prompt becomes the first line;
every line of a prompt is a separate prompt). People are read with the H3 Director's h3_core, so
"woman" and "girl" (plus the user's own words) stay exactly as written.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYSTEM_PROMPT_FILE = HERE / "fooocus_system_prompt.md"


def _load_h3_core():
    for name in ("h3_i2v_director_core", "h3_core"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "parse_people"):
            return module
    path = HERE.parent / "h3_i2v_director" / "h3_core.py"
    spec = importlib.util.spec_from_file_location("h3_i2v_director_core", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


core = _load_h3_core()
Issue, Check = core.Issue, core.Check

AUTO = "Auto (the best method for this edit)"
# Fooocus's own method names (modules/flags.py)
METHODS = {
    "default": "Inpaint or Outpaint (default)",
    "detail": "Improve Detail (face, hand, eyes, etc.)",
    "modify": "Modify Content (add objects, change background, etc.)",
}
OUTPAINT = ("Left", "Right", "Top", "Bottom")
# what Fooocus 2.5.5 sets when the method is chosen (webui.py, inpaint_mode_change)
SETTINGS = {
    "default": {"strength": 1.0, "field": 0.618, "engine": "v2.6", "no_initial_latent": False},
    "detail": {"strength": 0.5, "field": 0.0, "engine": "None", "no_initial_latent": False},
    "modify": {"strength": 1.0, "field": 0.0, "engine": "v2.6", "no_initial_latent": True},
}
FIELDS = ("prompt", "additional", "negative")
LABELS = {"prompt": "PROMPT", "additional": "ADDITIONAL", "negative": "NEGATIVE"}
LIMITS = {"prompt": 75, "additional": 25, "negative": 30}   # words; SDXL's CLIP reads 75 tokens per chunk
EDIT_WORDS = set("""change changes changed make makes add adds remove removes replace replaces replaced fix fixes fixed
turn turns put puts give gives swap swaps edit inpaint outpaint extend extends wider bigger more less better
improve improves erase delete get rid area""".split())
DEFECT_WORDS = re.compile(r"\b(?:deformed|extra|bad|blurry|blurred|distorted|missing|mutated|ugly|poorly|malformed|"
                          r"fused|broken|low|disfigured|cropped|duplicate|wrong|asymmetrical|floating|unnatural|"
                          r"warped|melted|messy|noisy|grainy|jpeg|artifacts?)\b", re.I)
# words that pick the method in Auto
_DETAIL_RE = re.compile(r"\b(?:detail(?:ed|s)?|sharp(?:er|en)?|clear(?:er)?|fix|fixes|improve|enhance|refine|better|"
                        r"crisp(?:er)?|focus(?:ed)?|restore|repair)\b", re.I)
_DETAIL_PART_RE = re.compile(r"\b(?:face|faces|eyes?|hands?|fingers?|teeth|mouth|lips|nose|ears?|skin texture|"
                             r"details?)\b", re.I)
_MODIFY_RE = re.compile(r"\b(?:add|adds|insert|put|place|new|remove|removes|erase|delete|get rid of|replace the "
                        r"background|background)\b", re.I)
# changes that make something bigger than its outline in the picture: the mask must leave room
SHAPE_RE = re.compile(r"\b(?:pregnan\w*|belly|bump|bigger|larger|longer|taller|wider|thicker|fuller|muscular|curvy|"
                      r"chubby|fat|bulk\w*|grow\w*|extend\w*|hair)\b", re.I)
# no pregnancy or nude edits for a minor
_MINOR = r"(?:girl|girls|boy|boys|child|children|kid|kids|toddler|baby|teen|teens|teenager|schoolgirl|schoolboy)"
# the one line this tab keeps: no sexual, nude, underwear or pregnancy edits for a girl, boy or child
_BODY = (r"(?:pregnan\w*|nude|naked|nudity|topless|bare chest|breasts?|nipples?|underwear|lingerie|panties|bra|"
         r"sexy|sexual|sexualized|erotic|seductive|provocative)")
_ADULT = r"(?:woman|women|man|men|lady|ladies|mother|mom|wife|husband|father|dad)"
_FOR_MINOR_RE = re.compile(   # the body edit is clearly for a minor
    rf"\b(?:pregnan\w*|nude|naked|topless)\s+(?:\w+\s+)?{_MINOR}\b"                 # pregnant girl
    rf"|\b{_MINOR}(?:'s)?\s+(?:\w+\s+)?{_BODY}\b"                                     # girl pregnant belly, girl in lingerie
    rf"|\b{_BODY}(?:\s+(?!{_ADULT}\b)(?!next\b)\w+){{0,2}}\s+(?:on|of|for)\s+(?:the\s+|a\s+|this\s+|that\s+)?"
    rf"(?:\w+\s+)?{_MINOR}\b"                                                         # pregnant belly on (the) girl
    rf"|\b{_MINOR}\s+(?:is|looks|gets|becomes)\s+(?:\w+\s+)?(?:pregnan\w*|nude|naked|topless)\b", re.I)
_BODY_RE = re.compile(rf"\b{_BODY}\b", re.I)
_BABY_BUMP_RE = re.compile(r"\bbaby[\s-]+bumps?\b", re.I)   # "baby bump" is pregnancy, not a baby


def _no_baby_bump(text: str) -> str:
    return _BABY_BUMP_RE.sub("pregnancy bump", text or "")
_MINOR_RE = re.compile(rf"\b{_MINOR}\b", re.I)
_ADULT_RE = re.compile(rf"\b{_ADULT}\b", re.I)
H3_LEFTOVERS = re.compile(r"integrated_multimodal_description|overall_soundscape|non_diegetic_music|\[Shot \d|"
                          r"<Picture \d>|fully referenced", re.I)


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()


def suggest_method(idea: str, area: str = "", outpaint=None) -> tuple[str, str]:
    """(method, why) for Auto: Fooocus's own descriptions of the three methods applied to the idea."""
    text = f"{idea or ''} {area or ''}"
    if outpaint:
        return "default", "extending the picture is done with Inpaint or Outpaint"
    if _DETAIL_RE.search(text) and (_DETAIL_PART_RE.search(text) or len(text.split()) <= 6):
        return "detail", "sharpening what is there (face, eyes, hands) is what Improve Detail is for"
    if _MODIFY_RE.search(text):
        return "modify", "adding something new, removing something or a new background is what Modify Content is for"
    return "default", ("changing what is there (a body part, clothes, hair, colors) keeps the skin tone, light and "
                       "edges of the picture best with Inpaint or Outpaint")


def required_phrases(idea: str) -> list[str]:
    """Keyword ideas ("red leather jacket, silver zipper"): each short phrase must appear word for word."""
    text = (idea or "").strip()
    if not text or not text.isascii():
        return []
    parts = [p.strip(" .;:!\"'").lower() for p in re.split(r",|;|\n|\band\b(?=\s+\w+\s*(?:,|$))", text)]
    phrases = []
    for p in parts:
        words = p.split()
        if not 1 <= len(words) <= 4 or words[0] in EDIT_WORDS or _verb_like(words):
            return []      # a sentence ("change girl shirt to red hoodie"), not a keyword list
        phrases.append(" ".join(words))
    return phrases


_SENTENCE_WORDS = {"to", "into", "is", "are", "was", "were", "has", "have", "should", "please", "will", "would",
                   "can", "could", "make", "making", "want", "need"}


def _verb_like(words) -> bool:
    """Sentence words give a sentence away; a keyword list has none ("detailed hands" is a keyword phrase)."""
    return any(w in _SENTENCE_WORDS for w in words)


def blocked_reason(idea: str, area: str = "") -> str:
    """This tab writes no pregnancy, nude or underwear edits for a girl, boy or child."""
    text = _no_baby_bump(f"{idea or ''} {area or ''}")
    clearly_minor = _FOR_MINOR_RE.search(text)
    only_minor = _BODY_RE.search(text) and _MINOR_RE.search(text) and not _ADULT_RE.search(text)
    if clearly_minor or only_minor:
        return ("This tab doesn't write sexual, nude, underwear or pregnancy edits for a girl, boy or child. "
                "Everything else it writes as you ask.")
    return ""


def blocked_output(fields: dict) -> str:
    """The same line for what the model wrote: a prompt describing a minor that way is not shown."""
    text = _no_baby_bump(f"{fields.get('prompt', '')}, {fields.get('additional', '')}")
    if _FOR_MINOR_RE.search(text) or (_BODY_RE.search(text) and _MINOR_RE.search(text) and not _ADULT_RE.search(text)):
        return ("The model described a girl, boy or child with a sexual, nude, underwear or pregnancy edit; this tab "
                "doesn't write that. Everything else it writes as you ask.")
    return ""


def tips(r: "InpaintRequest") -> list[str]:
    r.clamp()
    out = []
    if r.auto_reason:
        out.append(f"Method picked by Auto: {r.auto_reason}.")
    if r.method in ("default", "modify") and SHAPE_RE.search(f"{r.idea} {r.area}"):
        out.append("This edit makes something bigger than it is now: mask a little beyond where the new shape will "
                   "reach (for longer hair, where it will fall), or Fooocus can only fill the "
                   "current outline.")
    if r.method == "default":
        out.append("If the old shape keeps showing through, switch the method to Modify Content (it ignores what is "
                   "under the mask) and use the ADDITIONAL line it then needs: generate again here with that method.")
    elif r.method == "detail":
        out.append("Mask only the part to sharpen (the face, the eyes, one hand); Improve Detail keeps the shapes.")
    else:
        out.append("Modify Content sees only the masked area: mask generously so the new content has room and edges "
                   "to blend into.")
    return out


@dataclass
class InpaintRequest:
    idea: str = ""
    area: str = ""                    # the masked area in the user's words ("her shirt", "the sky")
    method: str = "default"           # see METHODS
    outpaint: list = field(default_factory=list)
    style: str = ""
    negative: str = "auto"            # auto / none
    image_notes: str = ""
    n_images: int = 0
    has_mask: bool = False            # the picture shows the mask as a red tint
    auto_reason: str = ""             # why Auto picked the method ("" = the user picked it)

    def clamp(self) -> "InpaintRequest":
        if self.method == "auto" or self.method not in METHODS:
            self.method, self.auto_reason = suggest_method(self.idea, self.area, self.outpaint)
        self.outpaint = [d for d in OUTPAINT if d in (self.outpaint or [])] if self.method == "default" else []
        self.negative = self.negative if self.negative in ("auto", "none") else "auto"
        return self


def build_user_message(r: InpaintRequest) -> str:
    r.clamp()
    if r.n_images and r.has_mask:
        picture = ("The attached picture is the image to inpaint. The red-tinted part is the masked area that Fooocus "
                   "will redraw; the rest stays.")
    elif r.n_images:
        picture = "The attached picture is the image to inpaint."
    elif r.image_notes.strip():
        picture = "The picture could not be attached; rely on the picture notes below as if you saw it."
    else:
        picture = "The picture could not be attached; infer it from the idea."
    out = ["Write the Fooocus inpaint prompts.", picture, f"METHOD: {METHODS[r.method]}."]
    if r.outpaint:
        out.append(f"OUTPAINT DIRECTION: {', '.join(r.outpaint)}. The picture is extended past these edges; PROMPT "
                   "describes the wider scene.")
    if r.area.strip():
        out.append(f"MASKED AREA (the user's words): {r.area.strip()}")
    out += ["", "IDEA FROM THE USER (plain language, any language):", "<<<",
            r.idea.strip() or "(no idea given: improve the masked area so it matches the picture)", ">>>", "",
            "REQUIREMENTS:"]
    if r.method == "default":
        out.append("- ADDITIONAL: N/A (this method has no additional box). PROMPT: what fills the masked area first, "
                   "then how it matches the rest of the picture (light, colors, style, perspective).")
    elif r.method == "detail":
        out.append("- ADDITIONAL: a short phrase naming the part and the detail wanted (3 to 20 words). PROMPT: the "
                   "whole picture as it is, briefly, or N/A.")
    else:
        out.append("- ADDITIONAL: only the new content of the masked area (3 to 20 words). PROMPT: the whole picture "
                   "as it should look with the new content in place.")
    phrases = required_phrases(r.idea)
    if phrases:
        where = "PROMPT" if r.method == "default" else "ADDITIONAL (and PROMPT)"
        out.append(f"- The idea is a list of the user's own words: put each of them word for word near the start of "
                   f"{where}: " + ", ".join(f'"{p}"' for p in phrases) + ". Then add only words that support them "
                   "and match the picture (shape, texture, color, light).")
    people = _people_lines(r.idea)
    out += people
    if not people:
        out.append("- The user names nobody: name the person in the masked area by what the picture shows, with the "
                   "plain words \"woman\" or \"man\" for adults, and no age words.")
    if r.negative == "none":
        out.append("- NEGATIVE: N/A (the user wants no negative prompt).")
    else:
        out.append("- NEGATIVE: only what to avoid for this edit; nothing the user wants.")
    if r.style.strip():
        out.append(f"- Style: {r.style.strip()}")
    else:
        out.append("- Style: take it from the picture (photo, anime, 3D render, painting ...).")
    if r.image_notes.strip():
        out += ["", "PICTURE NOTES (checked by the user; trust them over your own reading):", r.image_notes.strip()]
    out += ["", "Answer with exactly three lines: PROMPT: ... / ADDITIONAL: ... / NEGATIVE: ..."]
    return "\n".join(out)


def _people_lines(idea: str) -> list[str]:
    """The people rules of the H3 tabs, minus what only fits a video (sides of the frame, who acts in which sentence)."""
    lines = []
    for line in core.people_requirements(idea):
        if line.startswith("- Call them") or line.startswith("- Call this person"):
            line = line.split("; name the person")[0].rstrip(".") + "."
        if line.startswith("- Action"):
            continue   # an inpaint prompt describes how things look, not a sequence of actions
        lines.append(line)
    return lines


# --------------------------------------------------------------------------------------
# Reading the model's answer
# --------------------------------------------------------------------------------------

_LABEL_RE = {
    "prompt": r"(?:main\s+)?prompt|positive(?:\s+prompt)?",
    "additional": r"(?:inpaint\s+)?additional(?:\s+prompt)?",
    "negative": r"negative(?:\s+prompt)?",
}
_ANY_LABEL = re.compile(r"(?im)^[\s>*#`-]*(" + "|".join(f"(?P<{k}>{v})" for k, v in _LABEL_RE.items()) +
                        r")[\s*`]*:[\s*`]*")


def parse_answer(text: str) -> dict:
    """{prompt, additional, negative} from the model's answer (tolerates bold labels, fences, chatter)."""
    text = re.sub(r"^```[\w-]*\s*$", "", (text or "").replace("\r\n", "\n"), flags=re.M)
    hits = list(_ANY_LABEL.finditer(text))
    out = {f: "" for f in FIELDS}
    for i, m in enumerate(hits):
        name = next(k for k in FIELDS if m.group(k))
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        body = text[m.end():end]
        # chatter after the last box ("Let me know ...") is a new paragraph
        body = re.split(r"\n\s*\n", body.strip(), maxsplit=1)[0] if name == "negative" else body
        if not out[name]:
            out[name] = body.strip()
    return out


def _clean(value: str) -> str:
    value = " ".join((value or "").split())                      # one line: Fooocus splits at line breaks
    value = value.strip().strip('"“”').strip().strip("*`").strip()
    value = re.sub(r"\s*,\s*", ", ", value).strip(" ,")
    return "" if value.upper() in ("N/A", "NA", "NONE", "-", "") else value


def autofix(fields: dict, r: InpaintRequest) -> tuple[dict, list[str]]:
    r.clamp()
    notes = []
    fixed = {}
    for f in FIELDS:
        raw = fields.get(f, "") or ""
        fixed[f] = _clean(raw)
        if "\n" in raw.strip() and fixed[f]:
            notes.append(f"Joined {LABELS[f]} into one line (Fooocus treats every line as a separate prompt).")
    if r.method == "default" and fixed["additional"]:
        # this method has no additional box: keep the words by putting them at the front of the prompt
        if fixed["additional"].lower() not in fixed["prompt"].lower():
            fixed["prompt"] = f"{fixed['additional']}, {fixed['prompt']}".strip(", ")
        fixed["additional"] = ""
        notes.append("Moved ADDITIONAL into PROMPT (Inpaint or Outpaint has no additional box).")
    if r.negative == "none" and fixed["negative"]:
        fixed["negative"] = ""
        notes.append("Emptied NEGATIVE (you chose no negative prompt).")
    return fixed, notes


def as_text(fields: dict) -> str:
    return "\n".join(f"{LABELS[f]}: {fields.get(f) or 'N/A'}" for f in FIELDS)


# --------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------

def _wanted_words(idea: str) -> list[str]:
    removal = re.search(r"\b(?:remove|erase|delete|get rid of|without|no)\b(.*)", (idea or "").lower())
    unwanted = set(core.idea_keywords(removal.group(1))) if removal else set()
    return [w for w in core.idea_keywords(idea) if w not in EDIT_WORDS and w not in unwanted and len(w) >= 3]


def validate(fields: dict, r: InpaintRequest) -> list:
    r.clamp()
    issues = []
    err = lambda m: issues.append(Issue("error", m))  # noqa: E731
    warn = lambda m: issues.append(Issue("warning", m))  # noqa: E731
    if r.method == "default" and not fields["prompt"]:
        err("PROMPT is empty: write what fills the masked area and how it matches the picture.")
    if r.method in ("detail", "modify") and not fields["additional"]:
        err(f"ADDITIONAL is empty, but {METHODS[r.method]} uses it as the main line: write "
            + ("the part and the detail wanted (e.g. \"detailed girl face, clear eyes\")." if r.method == "detail"
               else "only the new content of the masked area."))
    for f in FIELDS:
        if H3_LEFTOVERS.search(fields[f]):
            err(f"{LABELS[f]} contains video-prompt text (H3 fields or shots); write a Fooocus image prompt.")
        words = len(fields[f].split())
        if words > LIMITS[f]:
            warn(f"{LABELS[f]} has {words} words; SDXL reads about 75 tokens at a time, so the end weighs less. "
                 "Shorter usually works better.")
        if re.search(r"\(\s*[^()]+:\s*\d(?:\.\d+)?\s*\)|__\w+__", fields[f]) and not re.search(r":\s*\d|__", r.idea):
            warn(f"{LABELS[f]} uses weights or wildcards you did not ask for.")
    positive = f"{fields['prompt']} {fields['additional']}".lower()
    if r.outpaint and fields["prompt"] and len(fields["prompt"].split()) < 8:
        warn("Outpaint: PROMPT is very short; describe the wider scene past the edges.")
    return issues


def checks(fields: dict, r: InpaintRequest) -> list:
    """Does it do what the user asked? People in the user's words, wanted things not in NEGATIVE, key words."""
    r.clamp()
    found = []
    positive = f"{fields['prompt']}, {fields['additional']}"
    pos_low = positive.lower()

    # people: the user's words, no ages, no other word for the girl; the user's description kept
    people = core.parse_people(r.idea)
    if people:
        keep = ("ages were added", "call her", "call him")
        for c in core.people_checks(positive, r.idea):
            if any(k in c.message for k in keep) and not c.ok:
                found.append(c)
        if fields["additional"]:
            for c in core.people_checks(fields["additional"], r.idea):
                if "speaks of several" in c.message and not c.ok:
                    found.append(Check(False, c.message.replace("the description", "ADDITIONAL"), repair=True))
        for p in people:
            sing, plural, alts = core.PEOPLE[p.cls]
            others = {"girl": ("child", "kid", "toddler", "teen", "teenager", "lady"),
                      "boy": ("child", "kid", "toddler", "teen", "teenager", "gentleman"),
                      "woman": ("lady", "mother", "mom"), "man": ("gentleman", "father", "dad")}.get(p.cls, ())
            wrong = [w for w in others if re.search(rf"\b{w}s?\b", pos_low) and not re.search(rf"\b{w}s?\b", r.idea.lower())]
            if wrong:
                found.append(Check(False, f"People: \"{wrong[0]}\" is used, but you wrote \"{sing}\"; use \"{sing}\".",
                                   repair=True))
            if p.count == 1 and p.adjectives and re.search(rf"\b(?:{sing}|{plural})\b", pos_low):
                missing = [a for a in p.adjectives if core._stem(a) not in core._stem_text(pos_low)]
                label = " ".join(p.adjectives + [sing])
                found.append(Check(not missing, f"People: \"{label}\", in your words" if not missing else
                                   f"People: write \"{label}\", as you did ({', '.join(missing)} is missing).",
                                   repair=bool(missing)))
        if not any(not c.ok for c in found):
            found.append(Check(True, "People: your words, no ages added"))

    # nothing the user wants may be in NEGATIVE ("deformed hands" next to "detailed hands" is fine)
    # an item clashes when it is made only of what the user asked for ("red hoodie", "clear eyes"); "grey sky" or
    # "storm clouds" next to a wanted blue sky with white clouds rule out the old look, which is right
    wanted = {core._stem(w) for w in _wanted_words(r.idea) if core._stem(w) in core._stem_text(pos_low)}
    wanted |= {core._stem(w) for p in required_phrases(r.idea) for w in p.split()}   # keyword ideas: always wanted
    clashes = []
    for item in [x.strip() for x in fields["negative"].split(",") if x.strip()]:
        if DEFECT_WORDS.search(item):
            continue
        words = {core._stem(w) for w in core.idea_keywords(item)}
        if words and words <= wanted:
            clashes.append(item)
    if fields["negative"]:
        found.append(Check(not clashes, "NEGATIVE: nothing you asked for" if not clashes else
                           f"NEGATIVE contains what you asked for: {', '.join(clashes[:3])}; take it out.",
                           repair=bool(clashes)))

    # the one line: a sexual, nude, underwear or pregnancy edit next to "girl"/"boy"/"child" the user did not write
    if _BODY_RE.search(_no_baby_bump(r.idea)):
        minor = _MINOR_RE.search(_no_baby_bump(pos_low))
        if minor and not _MINOR_RE.search(_no_baby_bump(r.idea)):
            found.append(Check(False, f"People: \"{minor.group(0)}\" appears with this edit. Name the person as the "
                                      "picture shows them (an adult is \"woman\" or \"man\"); if the person is a "
                                      "child, answer with three N/A lines.", repair=True))

    # keyword ideas: every phrase word for word ("red leather jacket", "silver zipper")
    phrases = required_phrases(r.idea)
    if phrases:
        flat = " ".join(re.findall(r"[a-z0-9']+", pos_low))
        missing = [p for p in phrases if not re.search(rf"\b{re.escape(p)}\b", flat)]
        found.append(Check(not missing, "Your words, word for word: " + ", ".join(f'"{p}"' for p in phrases)
                           if not missing else "Your words missing word for word: "
                           + ", ".join(f'"{p}"' for p in missing) + "; put them in as you wrote them.",
                           repair=bool(missing)))

    # the idea's own words (without editing words such as change, add, remove)
    keys = _wanted_words(r.idea)
    if keys:
        have = [w for w in keys if core._stem(w) in core._stem_text(pos_low)]
        share = len(have) / len(keys)
        missing = [w for w in keys if w not in have]
        found.append(Check(share >= 0.5, f"Your idea: {len(have)}/{len(keys)} key words in the prompts"
                           + (f" (not found: {', '.join(missing[:6])}; synonyms are fine)" if missing else "")))
    return found


def build_fix_message(issues: list, found: list) -> str:
    problems = [i.message for i in issues if i.level == "error"] + [c.message for c in found if c.repair and not c.ok]
    lines = ["Your Fooocus prompts have these problems:"] + [f"- {p}" for p in problems]
    lines += ["", "Write all three lines again with these fixed, and change nothing else. Answer with exactly three "
                  "lines: PROMPT: ... / ADDITIONAL: ... / NEGATIVE: ..."]
    return "\n".join(lines)


def settings_markdown(r: InpaintRequest) -> str:
    r.clamp()
    s = SETTINGS[r.method]
    rows = [
        "**Fooocus settings** (Input Image → Inpaint or Outpaint):",
        "",
        "| Setting | Value |",
        "|---|---|",
        f"| Method | {METHODS[r.method]}{' (picked by Auto)' if r.auto_reason else ''} |",
    ]
    if r.method == "default":
        rows.append(f"| Outpaint Direction | {', '.join(r.outpaint) if r.outpaint else 'none (inpaint only)'} |")
    rows += [
        f"| Inpaint Additional Prompt | {'the ADDITIONAL line' if r.method != 'default' else '— (not used by this method)'} |",
        "| Negative Prompt (Settings tab) | " + ("the NEGATIVE line" if r.negative == "auto" else "empty") + " |",
        f"| Inpaint Denoising Strength | {s['strength']:g} |",
        f"| Inpaint Respective Field | {s['field']:g}"
        + (" (only the masked area)" if s["field"] == 0 else " (uses the picture around the mask)") + " |",
        f"| Inpaint Engine | {s['engine']} |",
        f"| Disable initial latent in inpaint | {'on' if s['no_initial_latent'] else 'off'} |",
        "",
        "**Tips for this edit:**",
        *[f"- {t}" for t in tips(r)],
        "",
        "<small>Fooocus sets the last four by itself when you choose the method; they are under Advanced → "
        "Developer Debug Mode → Inpaint if you want to check them. With the Fooocus V2 style on, Fooocus adds a few "
        "words of its own to the first line; untick it under Styles if it changes things you described.</small>",
    ]
    return "\n".join(rows)


def report_markdown(issues: list, notes: list, found: list) -> str:
    lines = []
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    if not errors and not warnings:
        lines.append("**Format check: passed.** Three one-line boxes, as Fooocus reads them.")
    elif not errors:
        lines.append(f"**Format check: passed with {len(warnings)} note(s).**")
    else:
        lines.append(f"**Format check: {len(errors)} problem(s).**")
    lines += [f"- ❌ {i.message}" for i in errors] + [f"- ⚠️ {i.message}" for i in warnings]
    if notes:
        lines += ["", "Auto-fixed:"] + [f"- 🔧 {n}" for n in notes]
    if found:
        misses = [c for c in found if not c.ok]
        lines += ["", "**Matches your request: yes.**" if not misses else
                  f"**Matches your request: {len(misses)} point(s) to look at.**"]
        lines += [f"- {'✅' if c.ok else '⚠️'} {c.message}" for c in found]
    return "\n".join(lines)
