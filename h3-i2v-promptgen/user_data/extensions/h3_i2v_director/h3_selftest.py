"""Basic plain-language test prompts for the H3 I2V Director.

Used by the tab's self-test (runs them through the loaded model) and by the unit tests
(reference answers). Plain Python, no TextGen imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import h3_core as core


@dataclass
class Case:
    name: str
    what: str              # what the case checks, in plain words
    request: dict          # fields for h3_core.Request
    needs_picture: bool = False


CASES = [
    Case("text-basic", "a simple idea, everything else left to the model",
         dict(mode="T2VA", idea="a red fox walks through fresh snow at sunrise and looks back at the camera",
              duration=6)),
    Case("text-camera-no-music", "a static camera and no background music",
         dict(mode="T2VA", idea="a cat jumps onto a kitchen counter and knocks a cup over", duration=5,
              camera="Static Shot", music="none")),
    Case("text-dialogue-2-shots", "two shots with a timed cut and one spoken line kept word for word",
         dict(mode="T2VA", idea="a man waits at a rainy bus stop, checks his phone and says he is on his way, "
                                "then we see the bus arriving", duration=10, shots="2",
              dialogue="Man: I'm on my way.", dialogue_language="English")),
    Case("text-silence", "complete silence (both sound fields N/A)",
         dict(mode="T2VA", idea="snow falls on an empty playground at night", duration=5, silent=True)),
    Case("woman-and-girl", "a woman and a girl stay a woman and a girl, and the woman hands the cup to the girl",
         dict(mode="T2VA", idea="a woman standing next to a girl, the woman hands the girl a cup", duration=6)),
    Case("muscular-woman-and-girl", "\"the muscular woman\" and \"the girl\" stay exactly that, and the stick goes "
                                    "from the woman to the girl",
         dict(mode="T2VA", idea="a muscular woman standing next to a girl, the muscular woman hands the girl a stick",
              duration=6)),
    Case("picture-push-in", "image to video: the picture as first frame, push in with small amplitude at slow speed",
         dict(mode="I2VA", idea="the person in the picture smiles and waves at the camera", duration=5,
              camera="Push In", amplitude="small", speed="slow"), needs_picture=True),
    Case("picture-spanish-line", "image to video with a Spanish line kept in Spanish",
         dict(mode="I2VA", idea="they look at the camera and greet their friends", duration=5,
              dialogue="¡Hola, amigos!", dialogue_language="Spanish"), needs_picture=True),
]


@dataclass
class Result:
    case: Case
    prompt: str = ""
    issues: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    skipped: str = ""
    error: str = ""

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == "warning"]

    @property
    def misses(self):
        return [c for c in self.checks if not c.ok]

    @property
    def passed(self) -> bool:
        return not self.skipped and not self.error and not self.errors and not self.misses


def make_request(case: Case, n_images: int = 0) -> core.Request:
    return core.Request(**case.request, n_images=n_images).clamp()


def check(case: Case, prompt: str) -> Result:
    req = make_request(case, n_images=1 if case.needs_picture else 0)
    return Result(case, prompt, core.validate(prompt, req), core.fidelity(prompt, req))


def summary_markdown(results: list[Result]) -> str:
    rows = ["| Test | What it checks | Format | Matches the request | Result |", "|---|---|---|---|---|"]
    for r in results:
        if r.skipped:
            rows.append(f"| {r.case.name} | {r.case.what} | | | ⏭ {r.skipped} |")
            continue
        if r.error:
            rows.append(f"| {r.case.name} | {r.case.what} | | | ❌ {r.error} |")
            continue
        fmt = "✅" if not r.errors else f"❌ {len(r.errors)} error(s)"
        if r.warnings:
            fmt += f" · {len(r.warnings)} note(s)"
        fid = "✅" if not r.misses else "⚠️ " + "; ".join(c.message for c in r.misses)
        rows.append(f"| {r.case.name} | {r.case.what} | {fmt} | {fid} | {'✅ pass' if r.passed else '❌ fail'} |")
    run = [r for r in results if not r.skipped]
    passed = sum(r.passed for r in run)
    head = f"**Self-test: {passed}/{len(run)} passed**" + (f" ({len(results) - len(run)} skipped)" if len(run) < len(results) else "")
    return head + "\n\n" + "\n".join(rows)


def details_text(results: list[Result]) -> str:
    out = []
    for r in results:
        out.append(f"===== {r.case.name}: {r.case.what} =====")
        if r.skipped or r.error:
            out.append(r.skipped or r.error)
            continue
        out.append(r.prompt)
        for i in r.issues:
            out.append(f"  [{i.level}] {i.message}")
        for c in r.checks:
            out.append(f"  [{'ok' if c.ok else 'miss'}] {c.message}")
        out.append("")
    return "\n".join(out)
