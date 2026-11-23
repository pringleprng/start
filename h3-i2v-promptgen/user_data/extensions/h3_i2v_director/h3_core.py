"""Core logic of the H3 I2V Director.

Plain Python with no TextGen imports, so it can be tested on its own:
building the request for the language model, Inkling 2's native prompt
format, pulling the finished prompt out of the model's answer, and checking /
repairing the official MiniMax H3 prompt structure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYSTEM_PROMPT_FILE = HERE / "system_prompt.md"

MODES = ("I2VA", "FL2VA", "L2VA", "T2VA")
MODE_LABELS = {
    "I2VA": "I2VA: image to video (picture = first frame)",
    "FL2VA": "FL2VA: first + last frame",
    "L2VA": "L2VA: picture = last frame",
    "T2VA": "T2VA: text only, no picture",
}
IMAGES_NEEDED = {"I2VA": 1, "FL2VA": 2, "L2VA": 1, "T2VA": 0}

FIELDS = ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")

MIN_SECONDS, MAX_SECONDS = 4, 15

# Fixed first lines from MiniMax's H3 prompt-writing guide (base-en.txt, section 2.1).
I2VA_LINE = ("For the target video, at 0.00 seconds into the target video, "
             "<Picture 1> (from [Shot 1]) is fully referenced.")


def fl2va_line(last_shot: int, duration: float) -> str:
    return ("How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with "
            f"the 0.00-second mark of the target video; Picture 2 (from Shot {last_shot}) aligns with "
            f"the {duration:.2f}-second mark of the target video.")


def l2va_line(last_shot: int, duration: float) -> str:
    return ("How the reference pictures align with the target video — <Picture 1> (from "
            f"[Shot {last_shot}]) aligns with the {duration:.2f}-second mark of the target video.")


def instruction_line(mode: str, last_shot: int, duration: float) -> str:
    if mode == "I2VA":
        return I2VA_LINE
    if mode == "FL2VA":
        return fl2va_line(last_shot, duration)
    if mode == "L2VA":
        return l2va_line(last_shot, duration)
    return ""


CAMERA_MOVES = (
    "Static Shot", "Push In", "Pull Out", "Zoom In", "Zoom Out", "Pan Left", "Pan Right",
    "Truck Left", "Truck Right", "Tilt Up", "Tilt Down", "Pedestal Up", "Pedestal Down",
    "Arc Shot", "Tracking Shot", "POV", "Shake Slightly", "Shake Strongly",
    "Roll Clockwise", "Roll Counterclockwise",
)
CAMERA_SENTENCE = {
    "Static Shot": "the camera holds a static shot",
    "Push In": "the camera pushes in",
    "Pull Out": "the camera pulls out",
    "Zoom In": "the camera zooms in",
    "Zoom Out": "the camera zooms out",
    "Pan Left": "the camera pans left",
    "Pan Right": "the camera pans right",
    "Truck Left": "the camera trucks left",
    "Truck Right": "the camera trucks right",
    "Tilt Up": "the camera tilts up",
    "Tilt Down": "the camera tilts down",
    "Pedestal Up": "the camera pedestals up",
    "Pedestal Down": "the camera pedestals down",
    "Arc Shot": "the camera moves in an arc shot around the subject",
    "Tracking Shot": "the camera follows the subject in a tracking shot",
    "POV": "the shot is a POV from the subject's point of view",
    "Shake Slightly": "the camera shakes slightly",
    "Shake Strongly": "the camera shakes strongly",
    "Roll Clockwise": "the camera rolls clockwise",
    "Roll Counterclockwise": "the camera rolls counterclockwise",
}

# Words the official guide calls abstract, plus image-model tag habits.
HYPE_WORDS = (
    "masterpiece", "stunning", "breathtaking", "beautiful", "gorgeous", "epic", "8k", "4k",
    "ultra-detailed", "ultra detailed", "highly detailed", "best quality", "high quality",
    "photorealistic", "hyperrealistic", "hyper-realistic", "trending on", "award-winning",
)

# Mood words the guide keeps out of non_diegetic_music ("do not use abstract mood words").
MOOD_WORDS = (
    "emotional", "melancholic", "melancholy", "uplifting", "heartwarming", "nostalgic", "joyful", "happy", "sad",
    "tense", "dramatic", "mysterious", "romantic", "hopeful", "comforting", "cozy", "eerie", "triumphant",
    "atmospheric", "atmosphere", "mood", "moody", "feel-good", "inspiring", "haunting", "playful", "whimsical",
)
# Ordinary cut phrases from the guide (section 4.2); transitions only when the user asks.
CUT_PHRASES = ("the camera cuts to", "the shot cuts to", "the shot transitions to", "the shot changes to",
               "the shot switches to")
TRANSITION_RE = re.compile(r"cross-?dissolve|dissolves? (?:in)?to\b|fades? (?:to|from) black|\bfade-(?:in|out)\b|"
                           r"\bwipes? (?:to|across)\b", re.I)
STYLE_RE = re.compile(r"live-action|cinematic|2d|3d|\bcg\b|animat|anime|claymation|stop-motion|watercolou?r|"
                      r"vintage film|film|cartoon|illustrat|painterly|pixel|realistic|photographic|documentary|"
                      r"noir|sketch|ink|oil paint|comic", re.I)

# Hailuo 2.x bracket camera commands. H3 wants natural-language camera motion.
BRACKET_CAMERA_RE = re.compile(
    r"\[(?:truck|pan|tilt|pedestal|push|pull|zoom|tracking|static|shake|arc|roll|pov)\b[^\]]*\]",
    re.IGNORECASE,
)


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()


# --------------------------------------------------------------------------------------
# The request sent to the language model
# --------------------------------------------------------------------------------------

@dataclass
class Request:
    mode: str = "I2VA"
    idea: str = ""
    duration: int = 8
    aspect_ratio: str = "adaptive"
    shots: str = "auto"          # "auto" or a number as text
    camera: str = "auto"         # "auto" or one of CAMERA_MOVES
    amplitude: str = "auto"      # auto / small / medium / large
    speed: str = "auto"          # auto / slow / normal / fast
    dialogue: str = ""           # spoken lines, kept verbatim
    dialogue_language: str = ""  # e.g. English; empty = from the lines
    music: str = "auto"          # auto / none / custom
    music_text: str = ""
    silent: bool = False         # complete silence: soundscape and music N/A
    style: str = ""
    image_notes: str = ""        # what the picture shows (from the describe step or the user)
    n_images: int = 0            # pictures actually attached

    def clamp(self) -> "Request":
        self.mode = self.mode if self.mode in MODES else "I2VA"
        try:
            self.duration = int(round(float(self.duration)))
        except (TypeError, ValueError):
            self.duration = 8
        self.duration = max(MIN_SECONDS, min(MAX_SECONDS, self.duration))
        return self


def dialogue_lines(text: str) -> list[str]:
    """The spoken words of each line, without a leading 'Name:' and outer quotes."""
    lines = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^([^\W\d_][^:\"“]{0,39}):\s*(.+)$", line)
        if m:
            line = m.group(2).strip()
        line = line.strip().strip('"“”').strip()
        if line:
            lines.append(line)
    return lines


def _picture_sentence(req: Request) -> str:
    if req.mode == "I2VA":
        base = "The attached picture is <Picture 1>: the exact first frame of the video at 0.00 seconds, part of [Shot 1]."
    elif req.mode == "FL2VA":
        base = ("The first attached picture is Picture 1, the first frame at 0.00 seconds. The second attached "
                f"picture is Picture 2, the last frame at {req.duration:.2f} seconds, reached at the end of the final shot.")
    elif req.mode == "L2VA":
        base = (f"The attached picture is <Picture 1>: the exact last frame of the video at {req.duration:.2f} seconds, "
                "reached at the end of the final shot.")
    else:
        return "There is no picture. Build the whole scene from the text."
    if req.n_images < IMAGES_NEEDED[req.mode]:
        if req.image_notes.strip():
            base += " The picture could not be attached; rely on the picture notes below as if you saw it."
        else:
            base += " The picture could not be attached; infer it from the idea and keep the description general."
    return base


def build_user_message(req: Request) -> str:
    req.clamp()
    d = req.duration
    out = [
        "Write one MiniMax H3 prompt.",
        f"MODE: {req.mode}. {_picture_sentence(req)}",
        f"DURATION: {d} seconds. Every cut time must be earlier than 00:{d:02d}.000.",
    ]
    if req.aspect_ratio and req.aspect_ratio != "adaptive":
        out.append(f"ASPECT RATIO: {req.aspect_ratio}. Compose the shots for this frame.")
    out += ["", "IDEA FROM THE USER (plain language, any language):", "<<<", req.idea.strip() or "(no idea given: animate the picture naturally)", ">>>", "", "REQUIREMENTS:"]

    if req.shots == "auto":
        out.append("- Shots: your choice. One continuous shot unless the idea needs cuts.")
    elif str(req.shots) == "1":
        out.append("- Shots: exactly one continuous shot, no cuts.")
    else:
        out.append(f"- Shots: exactly {req.shots} shots with timed cuts.")

    if req.camera in CAMERA_SENTENCE:
        phrase = CAMERA_SENTENCE[req.camera]
        if req.camera not in ("Static Shot", "POV", "Shake Slightly", "Shake Strongly"):
            if req.amplitude in ("small", "large"):
                phrase += f" with {req.amplitude} amplitude"
            if req.speed in ("slow", "fast"):
                phrase += f" at {req.speed} speed"
        out.append(f"- Camera: {phrase}. Write it as a natural sentence inside the shot.")
    else:
        out.append("- Camera: your choice, one fitting motion per shot (or a static shot), written as a natural sentence.")

    lines = dialogue_lines(req.dialogue)
    if lines:
        lang = req.dialogue_language.strip() or "the language the lines are written in"
        out.append(f"- Dialogue: use these lines verbatim inside <d>[Language] ...</d>, language tag: {lang}. "
                   "Give each speaker an (S1)/(S2) ID and a voice description:")
        out += [f"    {raw.strip()}" for raw in req.dialogue.splitlines() if raw.strip()]
    else:
        out.append("- Dialogue: none, unless the idea clearly asks for speech.")

    if req.silent:
        out.append("- Sound: complete silence. Write N/A for overall_soundscape and N/A for non_diegetic_music.")
    else:
        if req.music == "none":
            out.append("- Background music: none. Write non_diegetic_music: N/A")
        elif req.music == "custom" and req.music_text.strip():
            out.append(f"- Background music: {req.music_text.strip()}")
        else:
            out.append("- Background music: your choice (or N/A if music would not fit).")

    if req.style.strip():
        out.append(f"- Style: {req.style.strip()}")
    if req.image_notes.strip():
        out += ["", "PICTURE NOTES (checked by the user; trust them over your own reading):", req.image_notes.strip()]

    first = instruction_line(req.mode, 1, d)
    start = f"the exact {req.mode} instruction line" if first else "integrated_multimodal_description:"
    out += ["", f"Output only the finished H3 prompt, starting with {start}."]
    return "\n".join(out)


DESCRIBE_SYSTEM_PROMPT = (
    "You describe pictures for a video prompt writer. Report only what is visible, precisely and briefly, "
    "in English. No story, no guesses about what happens next, no opinions."
)


def build_describe_message(n_images: int) -> str:
    who = "each picture (label them Picture 1 and Picture 2)" if n_images > 1 else "the picture"
    return (
        f"Describe {who} as short factual lines:\n"
        "Style/medium: (photo, 3D render, anime, painting ...)\n"
        "Shot size and camera angle:\n"
        "Subjects: for each one: apparent age, gender, build, hair, face, clothing with colors and materials, "
        "accessories, pose, position in the frame, expression\n"
        "Setting:\n"
        "Key props:\n"
        "Lighting and time of day:\n"
        "Color palette:\n"
        "Depth of field / focus:\n"
        "Visible text (verbatim, in quotes):\n"
        "Things that could move (hair, fabric, water, smoke, background people, vehicles):"
    )


def build_repair_message(issues: list["Issue"]) -> str:
    problems = "\n".join(f"- {i.message}" for i in issues)
    return (
        "Your H3 prompt has these problems:\n"
        f"{problems}\n\n"
        "Rewrite the complete prompt with these fixed and everything else kept. "
        "Output only the corrected prompt."
    )


# --------------------------------------------------------------------------------------
# Inkling 2 native prompt format
# --------------------------------------------------------------------------------------
# Matches the chat template shipped with the model (llama.cpp
# models/templates/thinkingmachines-Inkling.jinja): every content part is its own
# message block, a "Thinking effort level" system block comes before the first
# non-system message, and an image block is the role header followed by the media
# marker (mtmd adds <|content_image|> itself).

INK_SYSTEM = "<|message_system|>"
INK_USER = "<|message_user|>"
INK_MODEL = "<|message_model|>"
INK_TEXT = "<|content_text|>"
INK_THINK = "<|content_thinking|>"
INK_END = "<|end_message|>"
INK_END_SAMPLING = "<|content_model_end_sampling|>"
MEDIA_MARKER = "<__media__>"

THINKING_LEVELS = ("off", "low", "medium", "high")
INKLING_EFFORT = {"off": 0.0, "low": 0.2, "medium": 0.7, "high": 0.9}
# reasoning_effort names accepted by the Inkling template (for llama-server's chat endpoint)
TEMPLATE_EFFORT = {"off": "none", "low": "low", "medium": "medium", "high": "high"}


def is_inkling(model_name: str = "", template: str = "") -> bool:
    return "inkling" in (model_name or "").lower() or (INK_USER in (template or "") and INK_TEXT in (template or ""))


def inkling_prompt(system: str, turns: list[tuple], thinking: str = "off") -> str:
    """turns: ("user", text, n_images) or ("assistant", text). Ends with the generation prompt.

    thinking="off" pre-fills the answer block (<|message_model|><|content_text|>) so the
    model writes the prompt straight away without a thinking block.
    """
    effort = INKLING_EFFORT.get(thinking, 0.0)
    effort_text = "0" if effort == 0 else str(effort)
    parts = []
    if system:
        parts.append(f"{INK_SYSTEM}{INK_TEXT}{system}{INK_END}")
    parts.append(f"{INK_SYSTEM}{INK_TEXT}Thinking effort level: {effort_text}{INK_END}")
    for turn in turns:
        if turn[0] == "user":
            _, text, n_images = turn
            parts += [f"{INK_USER}{MEDIA_MARKER}{INK_END}"] * int(n_images)
            parts.append(f"{INK_USER}{INK_TEXT}{text}{INK_END}")
        else:
            parts.append(f"{INK_MODEL}{INK_TEXT}{turn[1]}{INK_END}{INK_END_SAMPLING}")
    parts.append(INK_MODEL + (INK_TEXT if thinking == "off" else ""))
    return "".join(parts)


# --------------------------------------------------------------------------------------
# Getting the prompt out of the model's answer
# --------------------------------------------------------------------------------------

SPECIAL_TOKEN_RE = re.compile(r"<\|[A-Za-z0-9_]+\|>")
THINK_TAG_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


def split_reasoning(text: str) -> tuple[str, str]:
    """(reasoning, answer). Handles <think> tags and visible Inkling blocks."""
    text = text or ""
    reasoning = ""
    m = THINK_TAG_RE.search(text)
    if m:
        reasoning = m.group(1).strip()
        text = text[:m.start()] + text[m.end():]
    elif INK_THINK in text:
        # <|content_thinking|> ... <|end_message|> <|message_model|><|content_text|> answer
        after = text.split(INK_THINK, 1)[1]
        reasoning, _, rest = after.partition(INK_END)
        text = rest
        reasoning = reasoning.strip()
    if INK_TEXT in text:
        text = text.split(INK_TEXT, 1)[1]
    if INK_END in text:
        text = text.split(INK_END, 1)[0]
    text = SPECIAL_TOKEN_RE.sub("", text)
    return reasoning, text.strip()


_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*$", re.MULTILINE)


def _field_pattern(name: str) -> str:
    # tolerate **bold**, `code`, "##" headings, spaces instead of underscores, any case
    words = name.split("_")
    return r"[#>*`\s]*" + r"[ _]".join(words) + r"[*`]*\s*:[*`]*"


FIELD_RES = {f: re.compile(r"(?im)^" + _field_pattern(f)) for f in FIELDS}
FIELD_ANY_RE = {f: re.compile(_field_pattern(f).replace(r"[#>*`\s]*", r"[*`]*", 1), re.IGNORECASE) for f in FIELDS}
INSTRUCTION_ANCHORS = ("For the target video, at 0.00 seconds", "How the reference pictures align with the target video")


def extract_prompt(text: str) -> tuple[str, str]:
    """(prompt, discarded): the last complete H3 prompt in the text, and what came before it."""
    text = _FENCE_RE.sub("", (text or "").replace("\r\n", "\n"))
    starts = [m.start() for m in FIELD_ANY_RE["integrated_multimodal_description"].finditer(text)]
    if not starts:
        return text.strip(), ""
    start = starts[-1]
    # step back to the instruction line just before the description, if there is one
    window = text[max(0, start - 1500):start]
    best = -1
    for anchor in INSTRUCTION_ANCHORS:
        pos = window.rfind(anchor)
        if pos > best:
            best = pos
    if best >= 0:
        start = max(0, start - 1500) + best
    else:
        line_start = text.rfind("\n", 0, start) + 1
        if not text[line_start:start].strip(" *#`>"):
            start = line_start
    discarded, prompt = text[:start].strip(), text[start:]
    # drop chatter after the non_diegetic_music paragraph
    music = list(FIELD_ANY_RE["non_diegetic_music"].finditer(prompt))
    if music:
        tail = prompt[music[-1].end():]
        m = re.search(r"\S.*?(?:\n\s*\n|$)", tail, re.DOTALL)
        if m:
            prompt = prompt[:music[-1].end()] + tail[:m.end()]
    return prompt.strip(), discarded


# --------------------------------------------------------------------------------------
# Structure: parse, repair, validate
# --------------------------------------------------------------------------------------

SHOT_RE = re.compile(r"\[Shot\s*(\d+)\]", re.IGNORECASE)
TIME_RE = re.compile(
    r"^\s*,?\s*At\s+(?:(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?|(\d{1,3}(?:\.\d{1,3})?)\s*(?=s\b|sec|second))"
    r"\s*(?:s|secs?|seconds?)?\b\s*,?",
    re.IGNORECASE,
)


def _time_secs(m: re.Match) -> float:
    if m.group(4) is not None:
        return float(m.group(4))
    return int(m.group(1)) * 60 + int(m.group(2)) + int((m.group(3) or "0").ljust(3, "0")) / 1000


DIALOGUE_RE = re.compile(r"<d>(.*?)</d>", re.DOTALL)


@dataclass
class Issue:
    level: str   # "error" | "warning"
    message: str


@dataclass
class Parsed:
    preamble: str = ""
    sections: dict = field(default_factory=dict)  # field name -> body text
    order: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)


def parse_prompt(prompt: str) -> Parsed:
    prompt = (prompt or "").replace("\r\n", "\n")
    hits = []
    for name, rx in FIELD_RES.items():
        for m in rx.finditer(prompt):
            hits.append((m.start(), m.end(), name))
    hits.sort()
    p = Parsed()
    if not hits:
        p.preamble = prompt.strip()
        return p
    p.preamble = prompt[:hits[0][0]].strip()
    for i, (s, e, name) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(prompt)
        body = prompt[e:end].strip()
        if name in p.sections:
            p.duplicates.append(name)
            continue
        p.sections[name] = body
        p.order.append(name)
    return p


def _one_paragraph(text: str) -> str:
    return re.sub(r"\s*\n\s*", " ", text.strip())


def _fmt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return f"{ms // 60000:02d}:{(ms // 1000) % 60:02d}.{ms % 1000:03d}"


def _shots(description: str) -> list[tuple[int, int, int]]:
    """[(shot number, start index, end of label)]"""
    return [(int(m.group(1)), m.start(), m.end()) for m in SHOT_RE.finditer(description)]


def _normalize_shots(description: str, notes: list[str]) -> str:
    """Canonical [Shot N] labels, no time on Shot 1, MM:SS.mmm times on later shots."""
    def label(m):
        return f"[Shot {int(m.group(1))}]"
    description = SHOT_RE.sub(label, description)

    out, last = [], 0
    for number, start, end in _shots(description):
        out.append(description[last:end])
        rest = description[end:]
        m = TIME_RE.match(rest)
        if m:
            secs = _time_secs(m)
            if number == 1:
                notes.append("Removed the timestamp from [Shot 1] (the first shot never has one).")
                out.append(" ")
            else:
                canonical = f" At {_fmt_time(secs)},"
                if rest[:m.end()].strip() != canonical.strip():
                    notes.append(f"Normalized the cut time of [Shot {number}] to MM:SS.mmm.")
                out.append(canonical + " ")
            last = end + m.end()
            # swallow spaces after the time
            while last < len(description) and description[last] == " ":
                last += 1
        else:
            if not rest.startswith(" "):
                out.append(" ")
            last = end
    out.append(description[last:])
    return "".join(out).strip()


def autofix(prompt: str, req: Request) -> tuple[str, list[str]]:
    """Deterministic repairs: exact instruction line, field labels and spacing, shot labels and
    times, N/A where silence or no music was requested. Returns (prompt, notes)."""
    req.clamp()
    notes: list[str] = []
    p = parse_prompt(prompt)
    if "integrated_multimodal_description" not in p.sections:
        return (prompt or "").strip(), notes

    description = _one_paragraph(p.sections["integrated_multimodal_description"])
    if not SHOT_RE.search(description):
        description = "[Shot 1] " + description
        notes.append("Added the missing [Shot 1] label.")
    description = _normalize_shots(description, notes)

    soundscape = _one_paragraph(p.sections.get("overall_soundscape", ""))
    music = _one_paragraph(p.sections.get("non_diegetic_music", ""))
    if req.silent:
        if soundscape.upper() != "N/A":
            notes.append("Set overall_soundscape to N/A (complete silence requested).")
        if music.upper() != "N/A":
            notes.append("Set non_diegetic_music to N/A (complete silence requested).")
        soundscape, music = "N/A", "N/A"
    elif req.music == "none" and music.upper() != "N/A":
        notes.append("Set non_diegetic_music to N/A (no music requested).")
        music = "N/A"
    for name, value in (("overall_soundscape", soundscape), ("non_diegetic_music", music)):
        if value.upper() == "N/A" and value != "N/A":
            notes.append(f"Wrote {name} N/A in the official spelling.")

    shots = _shots(description)
    last_shot = max((n for n, _, _ in shots), default=1)
    line = instruction_line(req.mode, last_shot, req.duration)
    if line and p.preamble.strip() != line:
        notes.append(f"Set line 1 to the exact {req.mode} instruction." if p.preamble.strip()
                     else f"Added the {req.mode} instruction line.")
    elif not line and p.preamble.strip():
        notes.append("Removed text before integrated_multimodal_description (T2VA has no instruction line).")

    blocks = []
    if line:
        blocks.append(line)
    blocks.append(f"integrated_multimodal_description: {description}")
    if "overall_soundscape" in p.sections or req.silent:
        blocks.append(f"overall_soundscape: {'N/A' if soundscape.upper() == 'N/A' else soundscape}")
    if "non_diegetic_music" in p.sections or req.silent or req.music == "none":
        blocks.append(f"non_diegetic_music: {'N/A' if music.upper() == 'N/A' else music}")
    if p.order != [f for f in FIELDS if f in p.order]:
        notes.append("Put the three fields in the official order.")
    if p.duplicates:
        notes.append("Dropped duplicate field(s): " + ", ".join(sorted(set(p.duplicates))) + ".")
    return "\n\n".join(blocks), notes


def _sentences(text: str) -> int:
    text = text.strip()
    if not text or text.upper() == "N/A":
        return 0
    return len([s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(<])", text) if s.strip()])


def validate(prompt: str, req: Request) -> list[Issue]:
    req.clamp()
    issues: list[Issue] = []
    err = lambda m: issues.append(Issue("error", m))  # noqa: E731
    warn = lambda m: issues.append(Issue("warning", m))  # noqa: E731

    p = parse_prompt(prompt)
    for name in FIELDS:
        if name not in p.sections:
            err(f"The {name} field is missing.")
    if [f for f in p.order if f in FIELDS] != [f for f in FIELDS if f in p.order]:
        err("The fields are not in the order integrated_multimodal_description, overall_soundscape, non_diegetic_music.")
    if p.duplicates:
        err("A field appears more than once: " + ", ".join(sorted(set(p.duplicates))) + ".")

    description = p.sections.get("integrated_multimodal_description", "")
    shots = _shots(description)
    if description and (not shots or shots[0][0] != 1 or description.find("[Shot 1]") != 0):
        err("integrated_multimodal_description must begin with [Shot 1].")

    # instruction line
    line = instruction_line(req.mode, max((n for n, _, _ in shots), default=1), req.duration)
    if line and p.preamble.strip() != line:
        err(f"Line 1 must be the exact {req.mode} instruction: {line}")
    if not line and p.preamble.strip():
        err("T2VA prompts start directly with integrated_multimodal_description (no text before it).")

    # shots and cut times
    expected, last_time = 1, 0.0
    for idx, (number, start, end) in enumerate(shots):
        if number != expected:
            err(f"Shot numbers must count up 1, 2, 3 ... (found [Shot {number}] where [Shot {expected}] belongs).")
            break
        expected += 1
        m = TIME_RE.match(description[end:])
        if number == 1:
            if m:
                err("[Shot 1] must not have a timestamp.")
            continue
        if not m:
            err(f"[Shot {number}] must start with its cut time, e.g. \"[Shot {number}] At 00:04.500, the camera cuts to ...\".")
            continue
        secs = _time_secs(m)
        if secs <= last_time:
            err(f"The cut time of [Shot {number}] ({_fmt_time(secs)}) must be later than the previous cut.")
        elif secs >= req.duration:
            err(f"The cut time of [Shot {number}] ({_fmt_time(secs)}) is outside the {req.duration}-second video.")
        elif secs - last_time < 1.5:
            warn(f"[Shot {number - 1}] lasts only {secs - last_time:.1f} s; shots shorter than about 2 s rarely read well.")
        last_time = secs
    if shots and req.duration - last_time < 1.5 and len(shots) > 1:
        warn(f"The last shot lasts only {req.duration - last_time:.1f} s.")
    if req.shots not in ("auto", "", None):
        try:
            wanted = int(req.shots)
            if shots and len(shots) != wanted:
                warn(f"You asked for {wanted} shot(s); the prompt has {len(shots)}.")
        except ValueError:
            pass

    # style and composition first, approved cut phrases later
    if shots and not STYLE_RE.search(" ".join(description[shots[0][2]:].split()[:30])):
        warn("[Shot 1] should open with the overall style and composition, e.g. \"[Shot 1] Live-action, cinematic, "
             "a medium shot frames ...\".")
    for number, start, end in shots[1:]:
        rest = description[end:]
        m = TIME_RE.match(rest)
        after = rest[m.end():].lstrip().lower() if m else ""
        if m and not after.startswith(CUT_PHRASES) and not TRANSITION_RE.search(after[:60]):
            warn(f"[Shot {number}] should continue with a cut phrase such as \"the camera cuts to\" "
                 f"(found \"{after[:30]}...\").")
    if TRANSITION_RE.search(description) and not re.search(r"dissolve|fade|wipe", req.idea, re.I):
        warn("A dissolve, fade or wipe is used, but the guide allows them only when you ask for one.")
    if req.mode == "FL2VA" and len(shots) > 1 and req.shots in ("auto", "", "1"):
        warn("First-and-last-frame videos work best as one continuous shot (the guide uses several only when asked).")

    # picture labels must refer to attached pictures
    labels = set(re.findall(r"Picture (\d)", prompt or ""))
    if req.mode == "T2VA" and labels:
        err("T2VA has no picture, but the prompt mentions one (unresolved reference label).")
    elif req.mode in ("I2VA", "L2VA") and labels - {"1"}:
        err(f"{req.mode} has one picture, but the prompt mentions Picture {', '.join(sorted(labels - {'1'}))}.")

    # dialogue
    blocks = DIALOGUE_RE.findall(description)
    if description.count("<d>") != description.count("</d>"):
        err("A <d> dialogue tag is not closed with </d>.")
    for b in blocks:
        if not re.match(r"\s*\[[^\]]+\]", b):
            err(f"Dialogue must start with a language tag such as [English]: <d>{b.strip()[:60]}</d>")
    for m in DIALOGUE_RE.finditer(description):
        before = description[max(0, m.start() - 250):m.start()]
        if not re.search(r"\(S\d+(?:\s*,\s*S\d+)*\)", before):
            warn("A dialogue line has no speaker ID like (S1) before it.")
            break
    ids_used = set(re.findall(r"\bS(\d+)\b", " ".join(re.findall(r"\((S\d+(?:\s*,\s*S\d+)*)\)", description))))
    ids_speaking = set()
    for m in DIALOGUE_RE.finditer(description):
        before = description[max(0, m.start() - 250):m.start()]
        found = re.findall(r"\((S\d+(?:\s*,\s*S\d+)*)\)", before)
        if found:
            ids_speaking |= set(re.findall(r"S(\d+)", found[-1]))
    for silent_id in sorted(ids_used - ids_speaking, key=int):
        warn(f"(S{silent_id}) never speaks; only characters who speak or sing get a speaker ID.")
    if re.search(r"voice-?over", description, re.I):
        if "says in an off-screen voiceover" not in description:
            warn("For a voiceover the guide uses the exact words \"says in an off-screen voiceover\".")
        for m in re.finditer(r"off-screen voiceover:?\s*<d>.*?</d>", description, re.S):
            if "lips remain" not in description[m.end():m.end() + 120]:
                warn("Right after each voiceover line, state that the character's lips remain closed.")
                break
    if description.count("<scenetrans>") % 2:
        warn("<scenetrans> marks both sides of a line that continues across a cut; one side is missing.")
    for line_text in dialogue_lines(req.dialogue):
        if line_text not in description:
            warn(f"Your line \"{line_text[:60]}\" is not in the prompt word for word.")
    for name in ("overall_soundscape", "non_diegetic_music"):
        if "<d>" in p.sections.get(name, ""):
            err(f"Dialogue belongs in integrated_multimodal_description, not in {name}.")

    # sound sections
    soundscape = p.sections.get("overall_soundscape", "")
    music = p.sections.get("non_diegetic_music", "")
    if "overall_soundscape" in p.sections:
        if not soundscape.strip():
            err("overall_soundscape is empty (write N/A only for complete silence).")
        elif soundscape.strip().upper() == "N/A" and not req.silent:
            warn("overall_soundscape is N/A although you did not ask for silence.")
        elif _sentences(soundscape) > 4:
            warn(f"overall_soundscape has {_sentences(soundscape)} sentences; the guide asks for 1 to 4.")
    if "non_diegetic_music" in p.sections:
        if not music.strip():
            err("non_diegetic_music is empty (write N/A for no music).")
        elif _sentences(music) > 3:
            warn(f"non_diegetic_music has {_sentences(music)} sentences; the guide asks for 1 to 3.")
        moods = sorted({w for w in MOOD_WORDS if re.search(r"(?<![a-z-])" + re.escape(w) + r"(?![a-z-])", music.lower())})
        if moods:
            warn("non_diegetic_music should name instruments, tempo, rhythm and dynamics, not moods: "
                 + ", ".join(moods) + ".")

    # style of writing
    if BRACKET_CAMERA_RE.search(prompt or ""):
        warn("Bracket camera commands like [Pan left] are Hailuo 2.x syntax; H3 wants camera motion as a sentence.")
    lowered = (prompt or "").lower()
    hype = sorted({w for w in HYPE_WORDS if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", lowered)})
    if hype:
        warn("Abstract hype words add nothing for H3: " + ", ".join(hype) + ".")
    words = len(description.split())
    if description and words < 60:
        warn(f"integrated_multimodal_description is short ({words} words); H3 follows detailed timelines better.")
    elif words > 900:
        warn(f"integrated_multimodal_description is very long ({words} words).")
    return issues


# --------------------------------------------------------------------------------------
# Does the prompt match what the user asked for?
# --------------------------------------------------------------------------------------

CAMERA_PATTERNS = {
    "Static Shot": r"static shot|holds? (?:a |the )?static|remains? (?:completely |perfectly )?(?:still|static)",
    "Push In": r"push(?:es|ing)? in", "Pull Out": r"pull(?:s|ing)? (?:out|back)",
    "Zoom In": r"zoom(?:s|ing)? in", "Zoom Out": r"zoom(?:s|ing)? out",
    "Pan Left": r"pan(?:s|ning)? left", "Pan Right": r"pan(?:s|ning)? right",
    "Truck Left": r"truck(?:s|ing)? left", "Truck Right": r"truck(?:s|ing)? right",
    "Tilt Up": r"tilt(?:s|ing)? up", "Tilt Down": r"tilt(?:s|ing)? down",
    "Pedestal Up": r"pedestal(?:s|ing)? up", "Pedestal Down": r"pedestal(?:s|ing)? down",
    "Arc Shot": r"\barc(?:s|ing)?\b", "Tracking Shot": r"tracking shot|\btrack(?:s|ing)\b",
    "POV": r"\bPOV\b|point of view", "Shake Slightly": r"shak(?:e|es|ing) slightly",
    "Shake Strongly": r"shak(?:e|es|ing) strongly", "Roll Clockwise": r"roll(?:s|ing)? clockwise",
    "Roll Counterclockwise": r"roll(?:s|ing)? counterclockwise",
}
SPEECH_HINT_RE = re.compile(r"[\"“”«»]|\b(?:say|says|said|saying|talk|talks|speak|speaks|shout|shouts|whisper|"
                            r"whispers|sing|sings|singing|ask|asks|tell|tells|yell|yells|call|calls|line|lines|"
                            r"dialogue|voice|voiceover|narrat\w*)\b", re.I)
STOPWORDS = set("""a an the and or but then than that this these those with without into onto from over under
after before while when where who whom whose which what about above below behind front near next between
around through across along toward towards upon also just very really some more most much many each every
both into its it's his her hers him she he they them their there here have has had having been being were
was are is be do does did doing can could would should will shall may might must not no yes only like same
other another such own your you our ours out off still even back away down up left right camera shot video
clip scene seconds second picture image frame photo make makes made look looks looking slowly quickly
for not you are was has had out off one two get got put see saw way can may all any how why now too yet let
our use via per its him her his she who they them then than""".split()) - {"way"}


@dataclass
class Check:
    ok: bool
    message: str
    repair: bool = False   # worth asking the model to fix


def _stem(word: str) -> str:
    word = word.lower()
    for suffix in ("ing", "ies", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def idea_keywords(idea: str) -> list[str]:
    """Content words of an English idea (empty for other languages)."""
    if not idea or not idea.isascii():
        return []
    words = re.findall(r"[A-Za-z][A-Za-z'-]{1,}", idea)
    out = []
    for w in words:
        lw = w.lower().strip("'")
        if lw in STOPWORDS or len(lw) < 3 or lw in out:
            continue
        out.append(lw)
    return out


def fidelity(prompt: str, req: Request) -> list[Check]:
    """Checks that the prompt does what the user asked for (on top of the format rules)."""
    req.clamp()
    checks: list[Check] = []
    p = parse_prompt(prompt)
    desc = p.sections.get("integrated_multimodal_description", "")
    low = desc.lower()

    if req.shots not in ("auto", "", None):
        try:
            wanted = int(req.shots)
            got = len(_shots(desc))
            checks.append(Check(got == wanted, f"Shots: asked for {wanted}, the prompt has {got}.", repair=got != wanted))
        except ValueError:
            pass

    if req.camera in CAMERA_PATTERNS:
        found = re.search(CAMERA_PATTERNS[req.camera], desc, re.I) is not None
        checks.append(Check(found, f"Camera: {req.camera.lower()}" + ("" if found else " is missing"), repair=not found))
        if req.camera not in ("Static Shot", "POV", "Shake Slightly", "Shake Strongly"):
            for value, phrase in ((req.amplitude, "with {} amplitude"), (req.speed, "at {} speed")):
                if value in ("small", "large", "slow", "fast"):
                    text = phrase.format(value)
                    ok = text in low
                    checks.append(Check(ok, f"Camera: \"{text}\"" + ("" if ok else " is missing"), repair=not ok))

    lines = dialogue_lines(req.dialogue)
    if lines:
        missing = [ln for ln in lines if ln not in desc]
        checks.append(Check(not missing, "Dialogue: all your lines word for word" if not missing else
                            "Dialogue: not word for word: " + "; ".join(f"\"{m[:50]}\"" for m in missing),
                            repair=bool(missing)))
        if req.dialogue_language.strip():
            tag = f"[{req.dialogue_language.strip()}]".lower()
            blocks = DIALOGUE_RE.findall(desc)
            ok = bool(blocks) and all(b.strip().lower().startswith(tag) for b in blocks)
            checks.append(Check(ok, f"Dialogue language tag {tag}" + ("" if ok else " is not used on every line"),
                                repair=not ok))
    elif DIALOGUE_RE.search(desc) and not SPEECH_HINT_RE.search(req.idea):
        checks.append(Check(False, "Dialogue was added although your idea has no speech.", repair=True))

    music = p.sections.get("non_diegetic_music", "").strip()
    soundscape = p.sections.get("overall_soundscape", "").strip()
    if req.silent:
        ok = music.upper() == "N/A" and soundscape.upper() == "N/A"
        checks.append(Check(ok, "Complete silence: soundscape and music are N/A" if ok else
                            "Complete silence was asked, but there is sound"))
    elif req.music == "none":
        checks.append(Check(music.upper() == "N/A", "No music: non_diegetic_music is N/A"))
    elif req.music == "custom" and req.music_text.strip():
        wanted = idea_keywords(req.music_text)
        hit = [w for w in wanted if _stem(w) in _stem_text(music)]
        ok = not wanted or len(hit) >= max(1, len(wanted) // 2)
        checks.append(Check(ok, "Music follows your description" if ok else
                            f"Music: your description ({', '.join(wanted)}) is not reflected", repair=not ok))

    if req.style.strip():
        wanted = idea_keywords(req.style) or [w.lower() for w in re.findall(r"\w{2,}", req.style)]
        opening = " ".join(desc.split()[:40]).lower()
        hit = [w for w in wanted if _stem(w) in _stem_text(opening)]
        ok = bool(hit) or not wanted
        checks.append(Check(ok, f"Style: {req.style.strip()}" + ("" if ok else " is not stated at the start of [Shot 1]"),
                            repair=not ok))

    keywords = idea_keywords(req.idea)
    if keywords:
        stems = _stem_text(desc)
        missing = [w for w in keywords if _stem(w) not in stems]
        share = 1 - len(missing) / len(keywords)
        msg = f"Your idea: {len(keywords) - len(missing)}/{len(keywords)} key words in the description"
        if missing:
            msg += " (not found: " + ", ".join(missing) + "; synonyms are fine)"
        checks.append(Check(share >= 0.6, msg))
    return checks


def _stem_text(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text)}


def build_fix_message(issues: list[Issue], checks: list[Check]) -> str:
    problems = [i.message for i in issues if i.level == "error"] + [c.message for c in checks if c.repair and not c.ok]
    return build_repair_message([Issue("error", m) for m in problems])


def report_markdown(issues: list[Issue], notes: list[str], prompt: str = "", checks: list[Check] | None = None) -> str:
    lines = []
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    if not errors and not warnings:
        lines.append("**Format check: passed.** Structure matches the official H3 guide.")
    elif not errors:
        lines.append(f"**Format check: passed with {len(warnings)} note(s).**")
    else:
        lines.append(f"**Format check: {len(errors)} problem(s).**")
    lines += [f"- ❌ {i.message}" for i in errors]
    lines += [f"- ⚠️ {i.message}" for i in warnings]
    if notes:
        lines.append("")
        lines.append("Auto-fixed:")
        lines += [f"- 🔧 {n}" for n in notes]
    if checks:
        lines.append("")
        misses = [c for c in checks if not c.ok]
        lines.append("**Matches your request: yes.**" if not misses else
                     f"**Matches your request: {len(misses)} point(s) to look at.**")
        lines += [f"- {'✅' if c.ok else '⚠️'} {c.message}" for c in checks]
    if prompt:
        p = parse_prompt(prompt)
        desc = p.sections.get("integrated_multimodal_description", "")
        n_shots = len(_shots(desc))
        lines.append("")
        lines.append(f"<small>{n_shots} shot(s) · {len(desc.split())} words in the description · "
                     f"{len(DIALOGUE_RE.findall(desc))} dialogue line(s)</small>")
    return "\n".join(lines)
