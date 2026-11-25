"""Core logic of the H3 POV tab: the camera is the girl's eyes (image to video).

Plain Python with no TextGen imports, so it can be tested on its own. It builds on the
H3 I2V Director's h3_core (official H3 format, people rules, repairs and checks) and adds
the POV request and the POV checks.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYSTEM_PROMPT_FILE = HERE / "pov_system_prompt.md"


def _load_h3_core():
    """The director's h3_core (shared format rules); reuse the copy TextGen already loaded."""
    for name in ("h3_i2v_director_core", "h3_core"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "validate"):
            return module
    path = HERE.parent / "h3_i2v_director" / "h3_core.py"
    spec = importlib.util.spec_from_file_location("h3_i2v_director_core", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


core = _load_h3_core()

MODES = {
    "snap": "The picture shows her: the camera snaps into her eyes",
    "eyes": "The picture is already her view: the camera stays at her eyes",
}
SNAP_TIMES = (0.5, 1.0, 1.5, 2.0)
HEAD = {
    "steady": ("Steady (small natural sway)",
               "The POV holds steady at her eye height with only a small natural sway of her head."),
    "look": ("Looks around slowly",
             "Her head turns slowly: the POV pans or tilts with small amplitude at slow speed toward what she looks at."),
    "walk": ("Walking",
             "She walks: the POV moves forward with a gentle walking bob (a tracking shot that shakes slightly)."),
    "still": ("Perfectly still",
              "Her head stays still: the POV holds a static shot at her eye height."),
}
HANDS = {
    "auto": ("When she uses them", "Show the girl's hands from the bottom of the frame only when she takes, holds or "
                                   "touches something."),
    "yes": ("Always in view", "Keep the girl's hands in view at the bottom of the frame for most of the POV."),
    "no": ("Never in view", "Keep the girl's hands and body out of the frame: only what she sees."),
}

POV_RE = re.compile(r"\bPOV\b|point of view|first-person|first person", re.I)
EYE_HEIGHT_RE = re.compile(r"eye height|eye level|eye-level|eye line|eyeline", re.I)
MIRROR_RE = re.compile(r"mirror|reflection|reflected", re.I)


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()


@dataclass
class PovRequest:
    idea: str = ""
    mode: str = "snap"           # snap / eyes (see MODES)
    who: str = "girl"            # the user's word for the POV person
    snap_at: float = 1.0         # seconds; when the camera cuts into her eyes (snap mode)
    duration: int = 5
    head: str = "steady"         # see HEAD
    hands: str = "auto"          # see HANDS
    dialogue: str = ""
    dialogue_language: str = ""
    music: str = "auto"          # auto / none / custom
    music_text: str = ""
    silent: bool = False
    style: str = ""
    image_notes: str = ""
    n_images: int = 0

    def clamp(self) -> "PovRequest":
        self.mode = self.mode if self.mode in MODES else "snap"
        self.head = self.head if self.head in HEAD else "steady"
        self.hands = self.hands if self.hands in HANDS else "auto"
        who = re.sub(r"[^\w' -]", "", (self.who or "")).strip().lower()
        who = re.sub(r"^(?:the|a|an)\s+", "", who)
        self.who = who or "girl"
        try:
            self.duration = int(round(float(self.duration)))
        except (TypeError, ValueError):
            self.duration = 5
        self.duration = max(core.MIN_SECONDS, min(core.MAX_SECONDS, self.duration))
        try:
            self.snap_at = float(self.snap_at)
        except (TypeError, ValueError):
            self.snap_at = 1.0
        # at least 2 seconds of POV after the snap
        self.snap_at = round(max(0.5, min(self.snap_at, self.duration - 2.0)), 3)
        return self

    def core_request(self) -> "core.Request":
        """The same request as the director's checks understand it (I2VA, POV camera)."""
        self.clamp()
        return core.Request(mode="I2VA", idea=self.idea, duration=self.duration, shots="auto", camera="POV",
                            dialogue=self.dialogue, dialogue_language=self.dialogue_language, music=self.music,
                            music_text=self.music_text, silent=self.silent, style=self.style,
                            image_notes=self.image_notes, n_images=self.n_images).clamp()

    @property
    def snap_time(self) -> str:
        return core._fmt_time(self.snap_at)

    @property
    def pov_words(self) -> str:
        return f"a first-person POV from the {self.who}'s eyes"


def build_user_message(r: PovRequest) -> str:
    r.clamp()
    who, d = r.who, r.duration
    picture = ("The attached picture is <Picture 1>: the exact first frame of the video at 0.00 seconds, part of [Shot 1]."
               if r.n_images else
               "The picture could not be attached; rely on the picture notes below as if you saw it."
               if r.image_notes.strip() else
               "The picture could not be attached; infer it from the idea and keep the description general.")
    out = ["Write one MiniMax H3 POV prompt.", f"MODE: I2VA. {picture}", f"THE POV PERSON: the {who}."]
    if r.mode == "snap":
        pov_secs = d - r.snap_at
        out.append(f"POV MODE: SNAP. <Picture 1> shows the {who} from the outside. [Shot 1] is the picture and lasts "
                   f"{r.snap_at:g} second{'s' if r.snap_at != 1 else ''}. [Shot 2] starts exactly with \"At {r.snap_time}, "
                   f"the camera cuts to {r.pov_words}\" and stays in her POV until the end.")
        out.append(f"DURATION: {d} seconds ({pov_secs:g} seconds of POV). Every cut time must be earlier than 00:{d:02d}.000.")
        beats = "2 clear beats" if pov_secs <= 4 else "2 to 3 clear beats" if pov_secs <= 7 else "3 to 5 clear beats"
        out.append(f"PACE: [Shot 1] 30 to 60 words. The POV part fits {beats}: the first movement starts at once, time "
                   "words place the beats (at first, midway, in the last second), and the last sentence is the state "
                   "that holds until the end.")
    else:
        out.append(f"POV MODE: EYES. <Picture 1> is already what the {who} sees. One continuous shot that starts with "
                   f"\"{r.pov_words} shows the view in <Picture 1>\", no cuts.")
        out.append(f"DURATION: {d} seconds.")
        out.append(f"PACE: {core.pace_hint(d)}")
    out += ["", "IDEA FROM THE USER (plain language, any language):", "<<<",
            r.idea.strip() or f"(no idea given: the {who} looks around naturally)", ">>>", "", "REQUIREMENTS:"]
    out.append(f"- The camera is the {who}'s eyes: at the {who}'s eye height, looking where she looks. Never show the "
               f"{who}'s face or head from the outside after the POV starts. People who look at her look into the lens.")
    out.append(f"- Head movement: {HEAD[r.head][1]}")
    out.append(f"- Hands: {HANDS[r.hands][1].replace('the girl', 'the ' + who)}")
    out += core.people_requirements(r.idea)

    lines = core.dialogue_lines(r.dialogue)
    if lines:
        lang = r.dialogue_language.strip() or "the language the lines are written in"
        out.append(f"- Dialogue: use these lines verbatim inside <d>[Language] ...</d>, language tag: {lang}. "
                   f"Lines spoken by the {who} come from off screen behind the camera. Give each speaker an "
                   "(S1)/(S2) ID and a voice description:")
        out += [f"    {raw.strip()}" for raw in r.dialogue.splitlines() if raw.strip()]
    else:
        out.append("- Dialogue: none, unless the idea clearly asks for speech.")
    if r.silent:
        out.append("- Sound: complete silence. Write N/A for overall_soundscape and N/A for non_diegetic_music.")
    elif r.music == "none":
        out.append("- Background music: none. Write non_diegetic_music: N/A")
    elif r.music == "custom" and r.music_text.strip():
        out.append(f"- Background music: {r.music_text.strip()}")
    else:
        out.append("- Background music: your choice (or N/A if music would not fit).")
    if r.style.strip():
        out.append(f"- Style: {r.style.strip()}")
    if r.image_notes.strip():
        out += ["", "PICTURE NOTES (checked by the user; trust them over your own reading):", r.image_notes.strip()]
    out += ["", "Output only the finished H3 prompt, starting with the exact I2VA instruction line."]
    return "\n".join(out)


# --------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------

def _shot_texts(desc: str) -> list[tuple[int, str]]:
    shots = core._shots(desc)
    return [(n, desc[end:(shots[i + 1][1] if i + 1 < len(shots) else len(desc))]) for i, (n, _, end) in enumerate(shots)]


def validate(prompt: str, r: PovRequest) -> list:
    """The official H3 format checks, minus the note about a short first shot (the snap is meant to be quick)."""
    return [i for i in core.validate(prompt, r.core_request())
            if not (r.mode == "snap" and i.level == "warning" and i.message.startswith("[Shot 1] lasts only"))]


def pov_checks(prompt: str, r: PovRequest) -> list:
    r.clamp()
    Check = core.Check
    who = r.who
    desc = core.parse_prompt(prompt).sections.get("integrated_multimodal_description", "")
    shots = _shot_texts(desc)
    checks = []
    if not shots:
        return [Check(False, "POV: the description has no [Shot 1].", repair=True)]

    if r.mode == "snap":
        ok = len(shots) == 2
        checks.append(Check(ok, "Snap: [Shot 1] is the picture, [Shot 2] is her POV" if ok else
                            f"Snap: use exactly two shots ([Shot 1] the picture, [Shot 2] At {r.snap_time}, the camera "
                            f"cuts to {r.pov_words}); the prompt has {len(shots)}.", repair=not ok))
        first, pov = shots[0][1], (shots[1][1] if len(shots) > 1 else "")
        if len(shots) > 1:
            m = core.TIME_RE.match(pov)
            at = core._time_secs(m) if m else None
            ok = at is not None and abs(at - r.snap_at) < 0.05
            checks.append(Check(ok, f"Snap: the camera cuts into her eyes at {r.snap_time}" if ok else
                                f"Snap: [Shot 2] must start with \"At {r.snap_time}, the camera cuts to {r.pov_words}\" "
                                f"(found {core._fmt_time(at) if at is not None else 'no cut time'}).", repair=not ok))
        ok = not POV_RE.search(first)
        checks.append(Check(ok, "Snap: [Shot 1] shows her from the outside, as in the picture" if ok else
                            "Snap: [Shot 1] is the picture (her from the outside); the POV starts only in [Shot 2].",
                            repair=not ok))
    else:
        ok = len(shots) == 1
        checks.append(Check(ok, "Eyes: one continuous POV shot" if ok else
                            f"Eyes: write one continuous POV shot with no cuts; the prompt has {len(shots)} shots.",
                            repair=not ok))
        pov = shots[0][1]

    head = " ".join(pov.split()[:45])
    ok = bool(POV_RE.search(head)) and re.search(rf"\b{re.escape(who)}'s eyes|\bher eyes", head, re.I) is not None
    checks.append(Check(ok, f"POV: the camera is the {who}'s eyes" if ok else
                        f"POV: start the POV with the words \"{r.pov_words}\".", repair=not ok))
    ok = EYE_HEIGHT_RE.search(pov) is not None
    checks.append(Check(ok, "POV: the camera is at her eye height" if ok else
                        f"POV: say that the camera is \"at the {who}'s eye height\".", repair=not ok))

    if not MIRROR_RE.search(r.idea or ""):  # a mirror the user asked for may show her
        outside = re.search(rf"\b(?:frames|shows|close-up of|shot of)\s+the\s+{re.escape(who)}\b|"
                            rf"\bthe\s+{re.escape(who)}'s\s+(?:face|head|hair|eyes\s+widen)|"
                            rf"\b{re.escape(who)}\s+(?:smiles|frowns|blinks|nods)\b", pov, re.I)
        checks.append(Check(outside is None, "POV: her face stays out of view (she is the camera)" if outside is None else
                            f"POV: \"{outside.group(0)}\" shows the {who} from the outside, but the camera is her eyes; "
                            "describe only what she sees (her hands may enter from the bottom of the frame).",
                            repair=outside is not None))
    hands = re.search(rf"\b(?:the\s+{re.escape(who)}'s|her)\s+(?:hands?|fingers|forearms?|arms?)\b", pov, re.I)
    if r.hands == "yes":
        checks.append(Check(hands is not None, f"Hands: the {who}'s hands are in view" if hands else
                            f"Hands: show the {who}'s hands at the bottom of the frame.", repair=hands is None))
    elif r.hands == "no":
        checks.append(Check(hands is None, "Hands: her hands stay out of view" if hands is None else
                            f"Hands: keep the {who}'s hands out of the frame (asked: never in view).", repair=hands is not None))
    if r.who not in (r.idea or "").lower() and not re.search(rf"\b{re.escape(who)}\b", desc, re.I):
        checks.append(Check(False, f"POV: call the POV person \"the {who}\".", repair=True))
    return checks


def checks(prompt: str, r: PovRequest) -> list:
    """Everything the tab reports: what the director checks for any H3 prompt, then the POV checks."""
    core_checks = [c for c in core.fidelity(prompt, r.core_request())
                   if not c.message.startswith("Shots:")]  # the POV checks own the shot count
    return pov_checks(prompt, r) + core_checks


def report_markdown(issues, notes, prompt, found) -> str:
    return core.report_markdown(issues, notes, prompt, found)
