"""5-second image-to-video: the rules Inkling gets, its worked examples and the pacing line."""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "extensions" / "h3_i2v_director"))

import h3_core as core  # noqa: E402
import h3_selftest as selftest  # noqa: E402

SYSTEM = core.load_system_prompt()

# the worked examples in the system prompt, with the request each one answers
EXAMPLES = {
    "EXAMPLE 1": core.Request(mode="I2VA", idea="dog shakes off the water and runs to the camera barking",
                              duration=5, n_images=1),
    "EXAMPLE 2": core.Request(mode="I2VA", idea="he looks up and says 'You came back.' then we see the door open",
                              duration=10, shots="2", dialogue="You came back.", n_images=1),
    "EXAMPLE 3": core.Request(mode="I2VA", idea="the woman hands the girl a cup", duration=5, n_images=1),
}


def example(name):
    return SYSTEM.split("# " + name)[1].split("\n\n", 1)[1].split("\n\n# ")[0].strip()


class Examples(unittest.TestCase):
    def test_examples_follow_every_rule(self):
        # models copy their examples closely, so each one must pass the same checks as a generated prompt
        for name, req in EXAMPLES.items():
            with self.subTest(name):
                prompt = example(name)
                self.assertEqual([i.message for i in core.validate(prompt, req)], [])
                self.assertEqual([c.message for c in core.fidelity(prompt, req) if not c.ok], [])
                self.assertEqual(core.autofix(prompt, req), (prompt, []))

    def test_five_second_examples_use_time_words_and_one_shot(self):
        for name in ("EXAMPLE 1", "EXAMPLE 3"):
            with self.subTest(name):
                body = example(name)
                self.assertNotIn("[Shot 2]", body)
                for word in ("At first", "Midway", "In the last second"):
                    self.assertIn(word, body)
                words = len(body.split("integrated_multimodal_description:")[1].split("overall_soundscape")[0].split())
                self.assertTrue(120 <= words <= 250, words)

    def test_examples_add_no_people(self):
        # the café example's idea has one man: nobody else may walk in
        self.assertNotRegex(example("EXAMPLE 2"), r"\b(?:figure|stranger|someone|woman|person)\b")


class NoAges(unittest.TestCase):
    def test_rules_never_ask_for_an_age(self):
        # ages may only appear in the "do not add" rule and the "only if the user gave one" rule
        for line in SYSTEM.splitlines():
            if re.search(r"\bage\b|apparent age|age group", line, re.I):
                self.assertRegex(line, r"Do not add ages|add an age only if the user gave one", line)

    def test_picture_description_asks_for_no_age(self):
        text = core.build_describe_message(1) + core.build_describe_message(2)
        self.assertNotRegex(text.lower(), r"\bage\b|adult or child")


class Pace(unittest.TestCase):
    def test_pace_line_in_every_request(self):
        msg = core.build_user_message(core.Request(mode="I2VA", idea="the woman hands the girl a cup",
                                                   duration=5, n_images=1).clamp())
        self.assertIn("DURATION: 5 seconds. Every cut time must be earlier than 00:05.000.", msg)
        self.assertIn("PACE: 5 seconds fits 2 to 3 clear action beats.", msg)
        self.assertIn("about 120 to 250 words", msg)

    def test_pace_scales_with_duration(self):
        self.assertIn("3 to 5", core.pace_hint(10))
        self.assertIn("5 or more", core.pace_hint(15))

    def test_too_long_for_five_seconds_is_flagged(self):
        req = core.Request(mode="T2VA", idea="a cat stretches", duration=5).clamp()
        body = "[Shot 1] Live-action, a medium shot frames a cat. " + "The cat stretches slowly on the warm floor. " * 50
        prompt = f"integrated_multimodal_description: {body}\n\noverall_soundscape: A quiet room.\n\nnon_diegetic_music: N/A"
        msgs = [i.message for i in core.validate(prompt, req)]
        self.assertTrue(any("a lot for 5 seconds" in m for m in msgs), msgs)
        # the same text is fine for 15 seconds
        req15 = core.Request(mode="T2VA", idea="a cat stretches", duration=15).clamp()
        self.assertFalse(any("a lot for" in i.message for i in core.validate(prompt, req15)))


class Defaults(unittest.TestCase):
    def test_tab_defaults_to_five_seconds(self):
        script = (Path(core.__file__).parent / "script.py").read_text()
        self.assertRegex(script, r"duration = gr\.Slider\(core\.MIN_SECONDS, core\.MAX_SECONDS, value=5,")

    def test_picture_self_tests_are_five_seconds(self):
        for case in selftest.CASES:
            if case.needs_picture:
                self.assertEqual(case.request["duration"], 5, case.name)


if __name__ == "__main__":
    unittest.main()
