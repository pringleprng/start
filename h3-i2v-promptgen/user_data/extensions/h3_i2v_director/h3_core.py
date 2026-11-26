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
    duration: int = 5
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
            self.duration = 5
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


# --------------------------------------------------------------------------------------
# People and actions named in the idea (kept exactly: a girl stays a girl)
# --------------------------------------------------------------------------------------

# class -> (singular, plural, other words that count as the same class)
PEOPLE = {
    "woman": ("woman", "women", ("lady", "ladies")),
    "man": ("man", "men", ("gentleman", "gentlemen")),
    "girl": ("girl", "girls", ()),
    "boy": ("boy", "boys", ()),
    "child": ("child", "children", ("kid", "kids")),
    "baby": ("baby", "babies", ("infant",)),
    "toddler": ("toddler", "toddlers", ()),
    "teenager": ("teenager", "teenagers", ("teen", "teens")),
    "mother": ("mother", "mothers", ("mom", "mum")),
    "father": ("father", "fathers", ("dad",)),
    "daughter": ("daughter", "daughters", ()),
    "son": ("son", "sons", ()),
    "grandmother": ("grandmother", "grandmothers", ("grandma",)),
    "grandfather": ("grandfather", "grandfathers", ("grandpa",)),
    "sister": ("sister", "sisters", ()),
    "brother": ("brother", "brothers", ()),
    "wife": ("wife", "wives", ()),
    "husband": ("husband", "husbands", ()),
}
CHILD_CLASSES = {"girl", "boy", "child", "baby", "toddler"}
ADULT_CLASSES = {"woman", "man", "mother", "father", "grandmother", "grandfather", "wife", "husband"}
FEMALE_CLASSES = {"woman", "girl", "mother", "daughter", "grandmother", "sister", "wife"}
MALE_CLASSES = {"man", "boy", "father", "son", "grandfather", "brother", "husband"}
_WORD_TO_CLASS = {}
for _cls, (_one, _many, _alts) in PEOPLE.items():
    for _w in (_one, _many, *_alts):
        _WORD_TO_CLASS[_w] = _cls
_PLURALS = {many for _, many, _ in PEOPLE.values()} | {"ladies", "gentlemen", "kids", "teens"}
_PERSON_RE = "(" + "|".join(sorted(_WORD_TO_CLASS, key=len, reverse=True)) + ")(?!-)"  # not "man-made"
_NUMBERS = {"a": 1, "an": 1, "one": 1, "another": 1, "two": 2, "both": 2, "three": 3, "four": 4, "five": 5, "six": 6}
# actions whose direction matters (who does it to whom), with words that count as the same action
VERB_GROUPS = {
    "hand": ("hand", "give", "pass", "offer"), "give": ("give", "hand", "pass", "offer"),
    "pass": ("pass", "hand", "give"), "offer": ("offer", "hand", "give"), "pour": ("pour", "fill"),
    "hug": ("hug", "embrace"), "kiss": ("kiss",), "push": ("push", "shove"), "pull": ("pull", "drag"),
    "lift": ("lift", "pick"), "carry": ("carry",), "feed": ("feed",), "help": ("help",), "chase": ("chase",),
    "follow": ("follow",), "teach": ("teach",), "show": ("show",), "hold": ("hold",), "throw": ("throw", "toss"),
    "kick": ("kick",), "hit": ("hit", "strike"), "comfort": ("comfort",), "dress": ("dress",), "brush": ("brush",),
    "tickle": ("tickle",), "lead": ("lead", "guide"), "catch": ("catch",), "wake": ("wake",), "tuck": ("tuck",),
    "take": ("take", "grab", "receive", "accept", "get", "snatch"),
}
_DET = r"(?:the|a|an|one|another|her|his|their|its|this|that)"
# never a description of the person that follows ("next to girl", "and the girl", "hands girl")
_NOT_ADJ = set("""the a an one another her his their its this that these those my your our some other each every both
either neither no not and or but then than so too very also just only now again same from with without by for at
on in into onto to of off over under near next behind beside besides between around toward towards about after
before while as like when where who which what he she they it him them we us i you is are was were be been""".split())
_PRONOUNS = {"he", "she", "they", "it", "who", "i", "we", "you"}


def _describes(word, before: str = "") -> bool:
    """Is word (in front of a person noun) a description of that person, like "muscular" or "older"?
    Not if it is a small word or a verb: "the woman hands girl" -> "hands" is what the woman does."""
    if not word or word in _NOT_ADJ or word in _NUMBERS or word in _WORD_TO_CLASS or _verb_key(word):
        return False
    m = re.search(r"([a-z']+)\s*$", before.lower())   # the word right before, with no comma or stop between
    prev = m.group(1) if m else ""
    return prev.removesuffix("'s") not in _WORD_TO_CLASS and prev not in _PRONOUNS


@dataclass
class Person:
    cls: str
    count: int
    adjectives: list = field(default_factory=list)
    read_as_one: str = ""   # "muscular women" that the rest of the idea shows is one person


@dataclass
class Action:
    actor: str        # class
    verb: str         # key of VERB_GROUPS
    receiver: str     # class
    actor_adj: str = ""
    receiver_adj: str = ""
    text: str = ""
    taken_from: bool = False   # "the girl takes the stick from the woman": the actor takes, the receiver gives


def _verb_key(word: str) -> str:
    word = word.lower()
    candidates = [word]
    for suffix in ("es", "s", "ed", "ing"):
        if word.endswith(suffix):
            base = word[: -len(suffix)]
            candidates += [base, base + "e", base[:-1] + "y" if base.endswith("i") else base]
    for c in candidates:
        if c in VERB_GROUPS:
            return c
    return ""


def parse_people(idea: str) -> list[Person]:
    """People the idea names, with how many of each (English ideas only)."""
    text = (idea or "").lower()
    if not text.isascii():
        return []
    counts: dict[str, int] = {}
    adjs: dict[str, list] = {}
    indefinite: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    mentions: dict[str, list] = {}   # cls -> [(plural, number word, description)]
    for m in re.finditer(rf"\b(?:(a|an|one|another|two|both|three|four|five|six)\s+)?(?:(\w+)\s+)?{_PERSON_RE}\b", text):
        number, adj, word = m.group(1), m.group(2), m.group(3)
        cls = _WORD_TO_CLASS[word]
        if adj and not _describes(adj, text[:m.start(2)]):
            adj = None  # "a baby girl" is one girl; "the woman hands girl": "hands" is a verb
        first_seen.setdefault(cls, m.start())
        plural = word in _PLURALS
        mentions.setdefault(cls, []).append((plural, number, adj))
        if adj:
            adjs.setdefault(cls, [])
            if adj not in adjs[cls]:
                adjs[cls].append(adj)
        if number:
            n = _NUMBERS[number]
            n = max(n, 2) if plural else n
            if number in ("a", "an", "one", "another"):
                indefinite[cls] = indefinite.get(cls, 0) + 1
            else:
                counts[cls] = max(counts.get(cls, 0), n)
        else:
            counts[cls] = max(counts.get(cls, 0), 2 if plural else 1)
    for cls, n in indefinite.items():
        counts[cls] = max(counts.get(cls, 0), n)
    # "muscular women standing next to girl, muscular woman hands girl a stick": a plural without a number
    # whose description the idea also uses for a single person is a slip for that one person
    read_as_one = {}
    for cls, ms in mentions.items():
        plurals = [x for x in ms if x[0]]
        singles = [x for x in ms if not x[0]]
        single_adjs = {a for _, _, a in singles if a}
        # "the older woman ... the younger woman": different descriptions of one kind are different people
        if len(single_adjs) >= 2:
            counts[cls] = max(counts.get(cls, 0), len(single_adjs))
            continue
        if plurals and singles and not any(n for _, n, _ in plurals) and not any(
                n and _NUMBERS.get(n, 1) > 1 for _, n, _ in singles):
            if all(a and a in single_adjs for _, _, a in plurals):
                counts[cls] = 1
                read_as_one[cls] = f"{plurals[0][2]} {PEOPLE[cls][1]}"
    order = sorted(counts, key=lambda c: first_seen.get(c, 0))
    return [Person(cls, counts[cls], adjs.get(cls, [])[:2] if counts[cls] == 1 else adjs.get(cls, []),
                   read_as_one.get(cls, "")) for cls in order]


def parse_actions(idea: str) -> list[Action]:
    """Directed actions between two people ("the woman hands the girl a cup")."""
    text = (idea or "").lower()
    if not text.isascii():
        return []
    person = rf"(?:(\w+)\s+)?{_PERSON_RE}"
    start = rf"(?:\b{_DET}\s+|(?<![\w']))"   # "the woman hands ..." or, written quickly, "woman hands ..."
    det = rf"(?:{_DET}\s+)?"
    patterns = (
        (rf"{start}{person}\s+(\w+)\s+{det}{person}(?!\w)", False),                          # X hands the girl ...
        (rf"{start}{person}\s+(\w+)\s+(?:\w+\s+){{0,4}}?(?:to|for|at)\s+{det}{person}(?!\w)", False),  # X pours tea for Y
        (rf"{start}{person}\s+(\w+)\s+(?:\w+\s+){{0,4}}?from\s+{det}{person}(?!\w)", True),    # X takes the stick from Y
    )
    actions = []
    for pat, from_ in patterns:
        for m in re.finditer(pat, text):
            a_adj, a_word, verb, r_adj, r_word = m.groups()
            key = _verb_key(verb)
            if not key or a_word not in _WORD_TO_CLASS or r_word not in _WORD_TO_CLASS:
                continue
            if from_ != (key == "take"):
                continue   # "from" only for taking; taking only with "from" (else who gives is unclear)
            a_adj = a_adj if _describes(a_adj or "", text[:m.start(1)] if a_adj else "") else ""
            r_adj = r_adj if _describes(r_adj or "", text[:m.start(4)] if r_adj else "") else ""
            end = re.search(r"[,.;!?]|\band then\b|\bthen\b|\bwhile\b|\band (?:the |a )?(?:" + _PERSON_RE[1:-6] + r")\b",
                            text[m.end():])
            clause = text[m.start(): m.end() + (end.start() if end else len(text) - m.end())].strip()
            act = Action(_WORD_TO_CLASS[a_word], key, _WORD_TO_CLASS[r_word], a_adj, r_adj, clause, from_)
            if not any(x.actor == act.actor and x.verb == act.verb and x.receiver == act.receiver for x in actions):
                actions.append(act)
    return actions


_COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def people_requirements(idea: str) -> list[str]:
    """Lines for the request that pin down the people and actions of the idea."""
    people = parse_people(idea)
    if not people:
        return []
    parts = []
    for p in people:
        sing, plural, _ = PEOPLE[p.cls]
        parts.append(f"one {sing}" if p.count == 1 else f"{_COUNT_WORDS.get(p.count, str(p.count))} {plural}")
    words = " and ".join(f'"{PEOPLE[p.cls][0]}"' for p in people)
    lines = [f"- People: exactly {' and '.join(parts)}. No more, no fewer, and never merge two people into one. "
             f"Use the words {words} for them every time, never another word for the same person, and add no ages "
             "or age words (adult, child, young, little, \"of about eight\")."]
    labels = [f'"the {" ".join(p.adjectives + [PEOPLE[p.cls][0]])}"' for p in people if p.count == 1]
    total = sum(p.count for p in people)
    if labels and total > 1:
        lines.append(f"- Call them {' and '.join(labels)} every time; name the person at the start of every action "
                     "sentence instead of \"she\" or \"he\" when two people could be meant. Give each person a side "
                     "of the frame at the start (left or right) and keep it.")
    elif labels:
        lines.append(f"- Call this person {labels[0]} every time.")
    for p in people:
        if p.read_as_one:
            sing = PEOPLE[p.cls][0]
            lines.append(f"- \"{p.read_as_one}\" in the idea means this one person: "
                         f"the {' '.join(p.adjectives + [sing])}. Show one {sing}, not several.")
        if p.count == 1 and p.adjectives:
            sing = PEOPLE[p.cls][0]
            lines.append(f"- Show the {sing} clearly as {' and '.join(p.adjectives)}, as the user wrote, and keep it "
                         "the same all the way.")
        if p.count > 1:
            sing = PEOPLE[p.cls][0]
            if len(p.adjectives) >= p.count:
                named = " and ".join(f'"the {a} {sing}"' for a in p.adjectives[: p.count])
                lines.append(f"- The {PEOPLE[p.cls][1]} must be told apart: call them {named} every time, as the user "
                             f"does, and show the difference visibly. Never call one of them just \"the {sing}\".")
            else:
                lines.append(f"- The {PEOPLE[p.cls][1]} must be told apart: give each {sing} a clothing colour or a "
                             f"position and use that same label every time, e.g. \"the {sing} "
                             f"in the red coat\" and \"the {sing} in the white blouse\". Never call one of them just "
                             f"\"the {sing}\".")
    for a in parse_actions(idea):
        actor = f"the {(a.actor_adj + ' ') if a.actor_adj else ''}{a.actor}"
        receiver = f"the {(a.receiver_adj + ' ') if a.receiver_adj else ''}{a.receiver}"
        how = (f"{actor} takes it from {receiver}" if a.taken_from else f"{actor} does it, {receiver} receives it")
        lines.append(f"- Action, keep the direction exactly: {a.text.strip()} ({how}).")
    return lines


def pace_hint(seconds: int) -> str:
    """How much action fits the clip (H3 renders 4 to 15 seconds)."""
    if seconds <= 6:
        beats, words = "2 to 3 clear action beats", "about 120 to 250 words"
    elif seconds <= 10:
        beats, words = "3 to 5 clear action beats", "about 180 to 350 words"
    else:
        beats, words = "5 or more clear action beats", "about 250 to 450 words"
    return (f"{seconds} seconds fits {beats}. The first movement starts at once, time words place the beats "
            "(at first, midway, in the last second), and the last sentence is the state that holds until the end. "
            f"integrated_multimodal_description: {words}.")


def build_user_message(req: Request) -> str:
    req.clamp()
    d = req.duration
    out = [
        "Write one MiniMax H3 prompt.",
        f"MODE: {req.mode}. {_picture_sentence(req)}",
        f"DURATION: {d} seconds. Every cut time must be earlier than 00:{d:02d}.000.",
        f"PACE: {pace_hint(d)}",
    ]
    if req.aspect_ratio and req.aspect_ratio != "adaptive":
        out.append(f"ASPECT RATIO: {req.aspect_ratio}. Compose the shots for this frame.")
    out += ["", "IDEA FROM THE USER (plain language, any language):", "<<<", req.idea.strip() or "(no idea given: animate the picture naturally)", ">>>", "", "REQUIREMENTS:"]

    out += people_requirements(req.idea)
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
        "Subjects: how many people; for each one: hair, clothing with colors and materials, "
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
    if len(prompt or "") > 7000:
        err(f"The prompt has {len(prompt)} characters; H3 accepts at most 7000.")
    elif len(prompt or "") > 6000:
        warn(f"The prompt has {len(prompt)} characters, close to H3's limit of 7000.")
    symbols = sorted(set(re.findall(r"->|=>|→|←|⇒|•|\s\+\s|#\w|\*\*?|[\U0001F300-\U0001FAFF]", DIALOGUE_RE.sub(" ", prompt or ""))))
    if symbols:
        warn("Symbols such as " + " ".join(x.strip() for x in symbols[:5]) +
             " can be drawn as text by H3; write plain sentences.")
    words = len(description.split())
    if description and words < 60:
        warn(f"integrated_multimodal_description is short ({words} words); H3 follows detailed timelines better.")
    elif words > 900:
        warn(f"integrated_multimodal_description is very long ({words} words).")
    elif req is not None and words > (350 if req.duration <= 6 else 500 if req.duration <= 10 else 900):
        warn(f"integrated_multimodal_description has {words} words, a lot for {req.duration} seconds: H3 may rush "
             "or skip actions. Fewer, clearer beats work better.")
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


_IRREGULAR_NOUNS = {"women": "woman", "men": "man", "children": "child", "people": "person"}


def _stem(word: str) -> str:
    word = word.lower().removesuffix("'s")
    word = _IRREGULAR_NOUNS.get(word, word)
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
        lw = w.lower().strip("'").removesuffix("'s")
        lw = _IRREGULAR_NOUNS.get(lw, lw)
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

    checks += people_checks(desc, req.idea)

    outside_dialogue = DIALOGUE_RE.sub(" ", desc)
    quoted = re.findall(r"\"([^\"]{1,80})\"", outside_dialogue)
    asks_text = re.search(r"[\"“”]|\b(?:text|sign|signs|title|caption|subtitles?|logo|banner|label|words?|writing|"
                          r"written|reads|reading|letters|poster|neon)\b", req.idea or "", re.I)
    if quoted and not asks_text:
        checks.append(Check(False, "On-screen text was added (" + ", ".join(f'"{q}"' for q in quoted[:3]) +
                            ") although your idea has none; H3 would draw it.", repair=True))

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


_IRREGULAR = {"give": "gave|given", "take": "took|taken", "get": "got|gotten", "hold": "held", "throw": "threw|thrown", "lead": "led", "catch": "caught",
              "feed": "fed", "teach": "taught", "show": "shown", "wake": "woke|woken", "strike": "struck",
              "hit": "hit", "pick": "picked"}


def _verb_regex(verbs) -> str:
    forms = []
    for v in verbs:
        if v.endswith("y"):
            forms.append(v[:-1] + "(?:y|ies|ied|ying)")
        elif v.endswith("e"):
            forms.append(v[:-1] + "(?:e|es|ed|ing)")
        else:
            forms.append(v + "(?:s|es|ed|ing|" + v[-1] + "ed|" + v[-1] + "ing)?")
        if v in _IRREGULAR:
            forms.append(_IRREGULAR[v])
    return r"\b(?:" + "|".join(forms) + r")\b"


_HAND_NOUN_BEFORE = set("""her his their its my your our the a an both one two each either empty right left free open
other own outstretched raised small big large bare gloved""".split())


def _is_body_part(sentence: str, match) -> bool:
    """True when a match of the verb "hand" is the noun: "her hand", "the woman's right hand"."""
    word = match.group(0)
    if not word.startswith("hand") or word.startswith(("handed", "handing")):
        return False
    prev = re.search(r"([a-z']+)\s*$", sentence[:match.start()])
    return bool(prev) and (prev.group(1) in _HAND_NOUN_BEFORE or prev.group(1).endswith("'s"))


def _sentences_of(desc: str) -> list[str]:
    text = DIALOGUE_RE.sub("<d/>.", desc)
    text = SHOT_RE.sub(".", text)
    return [x.strip() for x in re.split(r"(?<=[.!?;])\s+", text) if x.strip(" .")]


def people_checks(desc: str, idea: str) -> list[Check]:
    """People and actions of the idea: present, not merged, told apart, in the right direction."""
    people = parse_people(idea)
    if not people:
        return []
    low = desc.lower()
    wanted = {p.cls: p.count for p in people}
    checks: list[Check] = []

    for p in people:
        sing, plural, alts = PEOPLE[p.cls]
        present = any(re.search(rf"\b{re.escape(f)}\b", low) for f in (sing, plural, *alts))
        what = f"{_COUNT_WORDS.get(p.count, p.count)} {sing if p.count == 1 else plural}"
        if not present:
            checks.append(Check(False, f"People: the {sing} is missing (keep the word \"{sing}\").", repair=True))
        else:
            checks.append(Check(True, f"People: {what}"))
        if present and p.count == 1:
            stems = _stem_text(low)
            missing = [a for a in p.adjectives if _stem(a) not in stems]
            label = " ".join(p.adjectives + [sing])
            if p.adjectives:
                checks.append(Check(not missing, f"People: the {label}, in your words" if not missing else
                                    f"People: show the {sing} as {' and '.join(missing)}, as you wrote "
                                    f"(call her \"the {label}\")." if p.cls in FEMALE_CLASSES else
                                    f"People: show the {sing} as {' and '.join(missing)}, as you wrote "
                                    f"(call them \"the {label}\").", repair=bool(missing)))

    # other words for the same people, or extra people
    idea_low = (idea or "").lower()
    for word, cls in sorted(_WORD_TO_CLASS.items()):
        if cls in wanted or word in idea_low.split():
            continue
        if re.search(rf"\b{re.escape(word)}\b(?!-)(?!\s+(?:blue|pink|teeth|steps|powder|grand|carrot))", low):
            checks.append(Check(False, f"People: \"{word}\" appears, but your idea only has "
                                       + " and ".join(PEOPLE[c][0] if wanted[c] == 1 else PEOPLE[c][1] for c in wanted)
                                       + "; use your words and no extra people.", repair=True))

    # ages the user did not write
    person_words = "|".join(sorted((w for w in _WORD_TO_CLASS), key=len, reverse=True))
    age_patterns = (
        rf"\b(?:young|little|old|older|younger|elderly|middle-aged|teenage|grown|adult|small)\s+(?:{person_words})\b",
        r"\b(?:of|aged)\s+(?:about|around|roughly|maybe)?\s*(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
        r"sixty|seventy|eighty)\b(?:\s+years?)?(?:\s+old)?",
        r"\b\d+[- ]years?[- ]old\b",
        r"\bin (?:her|his|their) (?:early |late |mid-|mid )?(?:teens|twenties|thirties|forties|fifties|sixties|"
        r"seventies|eighties)\b",
        r"\b(?:an adult|a child|the child|a kid|the kid|a teenager|a toddler)\b",
    )
    added_ages = []
    for pat in age_patterns:
        for m in re.finditer(pat, low):
            phrase = m.group(0)
            if phrase not in idea_low and not any(w in idea_low for w in phrase.split()[:1] if w not in ("of", "in", "a", "an", "the")):
                added_ages.append(phrase)
    if added_ages:
        checks.append(Check(False, "People: ages were added (" + ", ".join(sorted(set(added_ages))[:4]) +
                            "); keep just your words for them.", repair=True))

    # several of a kind where the idea has one (e.g. "two women" for a woman and a girl)
    kinds = set(wanted)
    for child, adult in (("girl", "woman"), ("boy", "man")):
        if child in wanted:
            kinds.add(adult)
    for cls in kinds:
        sing, plural, _ = PEOPLE[cls]
        if wanted.get(cls, 0) < 2 and re.search(rf"\b(?:{plural}|both {sing}s?)\b", low):
            have = wanted.get(cls, 0)
            checks.append(Check(False, f"People: the description speaks of several {plural}, but your idea has "
                                       f"{_COUNT_WORDS.get(have, 'no') if have else 'no'} {sing if have == 1 else plural}.",
                                repair=True))
        child = {"woman": "girl", "man": "boy"}.get(cls)
        if (child in wanted and re.search(rf"\byoung {sing}\b", low)
                and not re.search(rf"\byoung {sing}\b", (idea or "").lower())):
            checks.append(Check(False, f"People: \"young {sing}\" appears, but your idea has a {child}; "
                                       f"call her \"the {child}\"." if child == "girl" else
                                       f"People: \"young {sing}\" appears, but your idea has a {child}; "
                                       f"call him \"the {child}\".", repair=True))

    # two of the same kind must be told apart
    for p in people:
        if p.count < 2:
            continue
        sing, plural, _ = PEOPLE[p.cls]
        if p.adjectives:
            missing = [a for a in p.adjectives[: p.count] if not re.search(rf"\b{re.escape(a)} {sing}\b", low)]
            checks.append(Check(not missing, f"People: the {plural} are called " +
                                " and ".join(f'"the {a} {sing}"' for a in p.adjectives[: p.count]) +
                                ("" if not missing else f" (missing: {', '.join(missing)})"), repair=bool(missing)))
        bare = re.findall(rf"\bthe {sing}\b(?!\s+(?:in|with|on|at|wearing|who|from|by|near|dressed|holding|carrying)\b)",
                          low)
        if bare:
            checks.append(Check(False, f"People: one of the {plural} is called just \"the {sing}\" ({len(bare)}x); "
                                       f"give each {sing} her own label so H3 can tell them apart.", repair=True))

    # two or more people: each one has a place in the frame
    if sum(wanted.values()) >= 2:
        placed = re.search(r"\b(?:on the left|on the right|to the left|to the right|left side|right side|"
                           r"in the foreground|in the background|in front of|behind|beside|next to|side by side|"
                           r"across from|opposite)\b", low)
        checks.append(Check(placed is not None, "People: each person has a place in the frame" if placed else
                            "People: say where each person is (left / right) so H3 keeps them apart"))

    # "She ..." / "He ..." at the start of a sentence when two people could be meant
    sentences = _sentences_of(desc)
    for group, pronouns, word in ((FEMALE_CLASSES, ("she", "her"), "female"), (MALE_CLASSES, ("he", "his"), "male")):
        if sum(n for cls, n in wanted.items() if cls in group) >= 2:
            starts = [x for x in sentences if x.split(" ", 1)[0].lower() in pronouns]
            if starts:
                names = " / ".join(f'"the {PEOPLE[c][0]}"' for c in wanted if c in group)
                checks.append(Check(False, f"People: {len(starts)} sentence(s) start with "
                                           f"\"{starts[0].split(' ', 1)[0]}\" although two {word} people are in the scene; "
                                           f"name who acts ({names}).", repair=True))

    # who does what to whom
    for a in parse_actions(idea):
        if a.actor == a.receiver:
            if not (a.actor_adj and a.receiver_adj):
                continue
            actor_tok, recv_tok = a.actor_adj, a.receiver_adj
        else:
            actor_tok = "|".join((PEOPLE[a.actor][0], *PEOPLE[a.actor][2]))
            recv_tok = "|".join((PEOPLE[a.receiver][0], *PEOPLE[a.receiver][2]))
        verb_re = _verb_regex(VERB_GROUPS[a.verb])
        ok = reversed_ = seen = False
        # judge each part of "X does this, and Y does that" on its own
        clauses = [c for sent in sentences for c in re.split(r",\s+(?:and|while|then|as)\s+|;\s+|\s+and then\s+", sent)]
        for sent in clauses:
            sl = sent.lower()
            for vm in re.finditer(verb_re, sl):
                if _is_body_part(sl, vm):
                    continue   # "her empty hand", "with both hands": a hand, not handing
                seen = True
                v = vm.start()
                actor_pos = [m.start() for m in re.finditer(rf"\b(?:{actor_tok})\b", sl)]
                recv_pos = [m.start() for m in re.finditer(rf"\b(?:{recv_tok})\b", sl)]
                actor_before = any(x < v for x in actor_pos)
                recv_after = any(x > v for x in recv_pos) or re.search(r"\b(?:her|him|them)\b", sl[v:]) is not None
                if actor_before and recv_after:
                    ok = True
                elif not actor_before and any(x > v for x in actor_pos) and any(x < v for x in recv_pos):
                    reversed_ = True
        label = a.text
        if ok:
            checks.append(Check(True, f"Action: {label}"))
        elif reversed_:
            checks.append(Check(False, f"Action reversed: your idea says \"{label}\", the description has it the other "
                                       "way round.", repair=True))
        else:
            checks.append(Check(False, f"Action: \"{label}\" is not described with the "
                                       f"{a.actor_adj + ' ' if a.actor_adj else ''}{a.actor} doing it"
                                       + ("" if seen else f" (no form of \"{a.verb}\" found)"), repair=True))
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
