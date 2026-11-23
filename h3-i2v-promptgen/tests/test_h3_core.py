"""Tests for h3_core (run: python -m unittest discover -s h3-i2v-promptgen/tests)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "extensions" / "h3_i2v_director"))

import h3_core as c  # noqa: E402

GOOD_I2VA = """For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium close-up frames the bearded man shown in <Picture 1> seated at a small wooden café table by the window, preserving his grey wool coat, dark scarf and the white cup in his hands. The camera holds a static shot as he slowly lifts his gaze toward the door off-screen right; his fingers tighten around the cup. The middle-aged man with a low, gravelly voice (S1) says quietly: <d>[English] You came back.</d> [Shot 2] At 00:05.500, the camera cuts to a medium-wide shot from behind his shoulder toward the entrance as the glass door swings open; rain gusts in and a figure in a dark raincoat steps inside and stops just past the threshold while water drips from the hem of the coat onto the tiles.

overall_soundscape: Soft café room tone with rain pattering on the windows. A brass doorbell rings, the door creaks open and wet footsteps stop on the tiled floor.

non_diegetic_music: A slow, sparse piano motif over a sustained low cello note."""


def req(**kw):
    base = dict(mode="I2VA", duration=10)
    base.update(kw)
    return c.Request(**base)


class InstructionLines(unittest.TestCase):
    def test_fixed_lines(self):
        self.assertEqual(c.instruction_line("I2VA", 3, 8), c.I2VA_LINE)
        self.assertEqual(
            c.instruction_line("FL2VA", 1, 8),
            "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the "
            "0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.")
        self.assertEqual(
            c.instruction_line("L2VA", 2, 6),
            "How the reference pictures align with the target video — <Picture 1> (from [Shot 2]) aligns with the "
            "6.00-second mark of the target video.")
        self.assertEqual(c.instruction_line("T2VA", 1, 8), "")


class Validate(unittest.TestCase):
    def test_good_prompt_passes(self):
        issues = c.validate(GOOD_I2VA, req(dialogue="Man: You came back."))
        self.assertEqual([i.message for i in issues if i.level == "error"], [])

    def test_missing_field(self):
        bad = GOOD_I2VA.split("\n\nnon_diegetic_music:")[0]
        msgs = [i.message for i in c.validate(bad, req())]
        self.assertTrue(any("non_diegetic_music field is missing" in m for m in msgs))

    def test_cut_outside_duration(self):
        msgs = [i.message for i in c.validate(GOOD_I2VA, req(duration=5))]
        self.assertTrue(any("outside the 5-second video" in m for m in msgs))

    def test_shot_one_timestamp_is_error(self):
        bad = GOOD_I2VA.replace("[Shot 1] Live-action", "[Shot 1] At 00:00.000, Live-action")
        msgs = [i.message for i in c.validate(bad, req())]
        self.assertTrue(any("[Shot 1] must not have a timestamp" in m for m in msgs))

    def test_unclosed_dialogue_and_language_tag(self):
        bad = GOOD_I2VA.replace("<d>[English] You came back.</d>", "<d>You came back.")
        msgs = [i.message for i in c.validate(bad, req())]
        self.assertTrue(any("not closed" in m for m in msgs))

    def test_user_line_must_be_verbatim(self):
        msgs = [i.message for i in c.validate(GOOD_I2VA, req(dialogue="Man: I missed you."))]
        self.assertTrue(any("word for word" in m for m in msgs))

    def test_bracket_camera_warning(self):
        bad = GOOD_I2VA.replace("The camera holds a static shot as", "[Static shot] As")
        msgs = [i.message for i in c.validate(bad, req())]
        self.assertTrue(any("Hailuo 2.x" in m for m in msgs))

    def test_t2va_rejects_instruction_line(self):
        msgs = [i.message for i in c.validate(GOOD_I2VA, req(mode="T2VA"))]
        self.assertTrue(any("T2VA prompts start directly" in m for m in msgs))


class Autofix(unittest.TestCase):
    def test_repairs_messy_output(self):
        messy = (
            "Sure! Here is your prompt:\n\n```\n"
            "For the target video at 0 seconds, Picture 1 is the first frame.\n"
            "**Integrated Multimodal Description:** [shot 1] At 00:00, Live-action, a wide shot of a fox in snow.\n"
            "The fox lifts its head and trots left. [Shot 2] at 0:04.5 the camera cuts to a close-up of its paws.\n"
            "**Overall Soundscape:** Wind hisses over the snow. Paws crunch.\n"
            "**Non Diegetic Music:** n/a\n```\nHope this helps!"
        )
        prompt, _ = c.extract_prompt(messy)
        fixed, notes = c.autofix(prompt, req(duration=8))
        lines = fixed.split("\n\n")
        self.assertEqual(lines[0], c.I2VA_LINE)
        self.assertTrue(lines[1].startswith("integrated_multimodal_description: [Shot 1] Live-action"))
        self.assertIn("[Shot 2] At 00:04.500, the camera cuts", lines[1])
        self.assertEqual(lines[2], "overall_soundscape: Wind hisses over the snow. Paws crunch.")
        self.assertEqual(lines[3], "non_diegetic_music: N/A")
        self.assertNotIn("Hope this helps", fixed)
        errors = [i for i in c.validate(fixed, req(duration=8)) if i.level == "error"]
        self.assertEqual(errors, [])
        self.assertTrue(notes)

    def test_fl2va_line_uses_last_shot_and_duration(self):
        body = GOOD_I2VA.split("\n\n", 1)[1]
        fixed, _ = c.autofix(body, req(mode="FL2VA", duration=12))
        self.assertTrue(fixed.startswith(c.fl2va_line(2, 12)))
        self.assertIn("12.00-second mark", fixed.split("\n")[0])

    def test_silence_forces_na(self):
        fixed, _ = c.autofix(GOOD_I2VA, req(silent=True))
        self.assertIn("overall_soundscape: N/A", fixed)
        self.assertIn("non_diegetic_music: N/A", fixed)

    def test_seconds_style_time(self):
        txt = GOOD_I2VA.replace("At 00:05.500,", "At 5.5s,")
        fixed, _ = c.autofix(txt, req())
        self.assertIn("[Shot 2] At 00:05.500, the camera cuts", fixed)


class Extraction(unittest.TestCase):
    def test_takes_final_prompt_after_thinking(self):
        thinking = ("Okay, the user wants the man to talk. I could write integrated_multimodal_description: [Shot 1] draft... "
                    "but better to add a second shot.\n\n")
        prompt, discarded = c.extract_prompt(thinking + GOOD_I2VA + "\n\nLet me know if you want changes.")
        self.assertEqual(prompt, GOOD_I2VA)
        self.assertIn("Okay, the user", discarded)

    def test_split_reasoning_with_visible_inkling_tokens(self):
        raw = "<|content_thinking|>plan the shot<|end_message|><|message_model|><|content_text|>THE PROMPT<|end_message|>"
        self.assertEqual(c.split_reasoning(raw), ("plan the shot", "THE PROMPT"))

    def test_split_reasoning_think_tags(self):
        self.assertEqual(c.split_reasoning("<think>hmm</think>\nANSWER"), ("hmm", "ANSWER"))


class InklingPrompt(unittest.TestCase):
    def test_matches_template_layout(self):
        p = c.inkling_prompt("SYS", [("user", "IDEA", 2)], thinking="off")
        self.assertEqual(
            p,
            "<|message_system|><|content_text|>SYS<|end_message|>"
            "<|message_system|><|content_text|>Thinking effort level: 0<|end_message|>"
            "<|message_user|><__media__><|end_message|>"
            "<|message_user|><__media__><|end_message|>"
            "<|message_user|><|content_text|>IDEA<|end_message|>"
            "<|message_model|><|content_text|>")

    def test_thinking_and_followup_turns(self):
        p = c.inkling_prompt("S", [("user", "A", 0), ("assistant", "B"), ("user", "C", 0)], thinking="low")
        self.assertIn("Thinking effort level: 0.2", p)
        self.assertIn("<|message_model|><|content_text|>B<|end_message|><|content_model_end_sampling|>", p)
        self.assertTrue(p.endswith("<|message_model|>"))

    def test_detection(self):
        self.assertTrue(c.is_inkling("Inkling-2-Mini-Uncensored-Q4_K_M.gguf"))
        self.assertTrue(c.is_inkling("x", "<|message_user|><|content_text|>"))
        self.assertFalse(c.is_inkling("Qwen3-VL-8B", "<|im_start|>"))


class UserMessage(unittest.TestCase):
    def test_contains_settings(self):
        msg = c.build_user_message(c.Request(mode="I2VA", idea="she waves", duration=6, camera="Push In",
                                             amplitude="small", speed="slow", dialogue="Girl: Hi there!",
                                             music="none", n_images=1))
        self.assertIn("MODE: I2VA", msg)
        self.assertIn("earlier than 00:06.000", msg)
        self.assertIn("the camera pushes in with small amplitude at slow speed", msg)
        self.assertIn("Girl: Hi there!", msg)
        self.assertIn("non_diegetic_music: N/A", msg)

    def test_duration_is_clamped(self):
        r = c.Request(duration=40).clamp()
        self.assertEqual(r.duration, 15)

    def test_system_prompt_has_no_braces(self):
        # it is embedded in a Jinja template, so it must not contain { or }
        self.assertNotRegex(c.load_system_prompt(), r"[{}]")


if __name__ == "__main__":
    unittest.main()
