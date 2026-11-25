"""The H3 POV tab: the camera is the girl's eyes (pov_core.py and pov_system_prompt.md)."""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "extensions" / "h3_pov_eyes"))

import pov_core as pov  # noqa: E402

core = pov.core
SYSTEM = pov.load_system_prompt()


def example(name):
    return SYSTEM.split("# " + name)[1].split("\n\n", 1)[1].split("\n\n# ")[0].strip()


SNAP = pov.PovRequest(idea="the woman hands the girl a cup", mode="snap", snap_at=1.0, duration=5, n_images=1)
EYES = pov.PovRequest(idea="she walks to the window and opens it", mode="eyes", duration=5, head="walk", n_images=1)
GOOD_SNAP = example("EXAMPLE 1")
GOOD_EYES = example("EXAMPLE 2")


def misses(prompt, req):
    return [c.message for c in pov.checks(prompt, req) if not c.ok]


class Examples(unittest.TestCase):
    def test_examples_pass_every_check(self):
        for prompt, req in ((GOOD_SNAP, SNAP), (GOOD_EYES, EYES)):
            with self.subTest(prompt[:120]):
                self.assertEqual([i.message for i in pov.validate(prompt, req)], [])
                self.assertEqual(misses(prompt, req), [])
                self.assertEqual(core.autofix(prompt, req.core_request()), (prompt, []))

    def test_snap_example_shape(self):
        self.assertIn("[Shot 2] At 00:01.000, the camera cuts to a first-person POV from the girl's eyes, at the girl's "
                      "eye height", GOOD_SNAP)
        self.assertNotIn("[Shot 3]", GOOD_SNAP)
        self.assertNotIn("[Shot 2]", GOOD_EYES)
        self.assertTrue(GOOD_EYES.split("integrated_multimodal_description: [Shot 1] ", 1)[1]
                        .startswith("Live-action, cinematic, a first-person POV from the girl's eyes"))

    def test_rules_are_plain_text_without_ages(self):
        self.assertNotIn("{", SYSTEM)
        self.assertNotIn("}", SYSTEM)
        for line in SYSTEM.splitlines():
            if re.search(r"\bages?\b", line, re.I):
                self.assertRegex(line, r"Do not add ages|no added ages")
        self.assertIn(core.I2VA_LINE, SYSTEM)


class Message(unittest.TestCase):
    def test_snap_message(self):
        msg = pov.build_user_message(pov.PovRequest(**{**SNAP.__dict__}))
        self.assertIn("POV MODE: SNAP", msg)
        self.assertIn('starts exactly with "At 00:01.000, the camera cuts to a first-person POV from the girl\'s eyes"',
                      msg)
        self.assertIn("DURATION: 5 seconds (4 seconds of POV)", msg)
        self.assertIn("Never show the girl's face", msg)
        self.assertIn('Use the words "woman" and "girl" for them every time', msg)
        self.assertIn("the woman hands the girl a cup (the woman does it, the girl receives it)", msg)
        self.assertTrue(msg.rstrip().endswith("starting with the exact I2VA instruction line."))

    def test_eyes_message_and_other_word(self):
        msg = pov.build_user_message(pov.PovRequest(idea="she opens the door", mode="eyes", who="The Woman", n_images=1))
        self.assertIn("POV MODE: EYES", msg)
        self.assertIn("a first-person POV from the woman's eyes shows the view in <Picture 1>", msg)
        self.assertNotIn("[Shot 2]", msg)

    def test_her_lines_come_from_behind_the_camera(self):
        msg = pov.build_user_message(pov.PovRequest(idea="the woman hands the girl a cup", dialogue="Girl: Thank you!",
                                                    n_images=1))
        self.assertIn("Lines spoken by the girl come from off screen behind the camera", msg)
        self.assertIn("    Girl: Thank you!", msg)

    def test_no_picture_uses_notes(self):
        msg = pov.build_user_message(pov.PovRequest(idea="x", image_notes="a girl in a red coat", n_images=0))
        self.assertIn("rely on the picture notes below", msg)

    def test_snap_time_leaves_room_for_the_pov(self):
        self.assertEqual(pov.PovRequest(snap_at=4, duration=5).clamp().snap_at, 3.0)
        self.assertEqual(pov.PovRequest(snap_at=0.1).clamp().snap_at, 0.5)
        self.assertEqual(pov.PovRequest(snap_at=1.5).clamp().snap_time, "00:01.500")


class Broken(unittest.TestCase):
    def test_wrong_snap_time(self):
        bad = GOOD_SNAP.replace("At 00:01.000", "At 00:02.000")
        self.assertTrue(any("must start with \"At 00:01.000" in m for m in misses(bad, SNAP)))

    def test_pov_words_missing(self):
        bad = GOOD_SNAP.replace("a first-person POV from the girl's eyes", "a close-up of the cup")
        self.assertTrue(any("start the POV with the words" in m for m in misses(bad, SNAP)))

    def test_pov_already_in_shot_1(self):
        bad = GOOD_SNAP.replace("a medium shot frames the woman", "a POV shot frames the woman")
        self.assertTrue(any("the POV starts only in [Shot 2]" in m for m in misses(bad, SNAP)))

    def test_cutting_back_outside(self):
        bad = GOOD_SNAP.replace("\n\noverall_soundscape", " [Shot 3] At 00:04.000, the camera cuts to a wide shot of the "
                                "kitchen.\n\noverall_soundscape")
        self.assertTrue(any("use exactly two shots" in m for m in misses(bad, SNAP)))

    def test_her_face_shown_from_outside(self):
        bad = GOOD_SNAP.replace("In the last second the POV tilts down", "In the last second the girl smiles and the POV tilts down")
        self.assertTrue(any("shows the girl from the outside" in m for m in misses(bad, SNAP)))
        mirror_idea = pov.PovRequest(**{**SNAP.__dict__, "idea": "the woman hands the girl a cup in front of a mirror"})
        mirrored = bad.replace("the white cup held", "the mirror reflection and the white cup held")
        self.assertFalse(any("from the outside" in m for m in misses(mirrored, mirror_idea)))

    def test_eye_height_missing(self):
        bad = GOOD_SNAP.replace(", at the girl's eye height,", ",")
        self.assertTrue(any("eye height" in m for m in misses(bad, SNAP)))

    def test_hands_wanted_or_not(self):
        no_hands = pov.PovRequest(**{**SNAP.__dict__, "hands": "no"})
        self.assertTrue(any("keep the girl's hands out of the frame" in m for m in misses(GOOD_SNAP, no_hands)))
        want = pov.PovRequest(**{**EYES.__dict__, "hands": "yes"})
        bad = GOOD_EYES.replace("the girl's hands rise from the bottom of the frame, part", "the sheer curtains part,")
        self.assertTrue(any("show the girl's hands" in m for m in misses(bad, want)))

    def test_eyes_mode_has_no_cut(self):
        bad = GOOD_EYES.replace("Midway,", "[Shot 2] At 00:02.500, the camera cuts to the window. Midway,")
        self.assertTrue(any("one continuous POV shot" in m for m in misses(bad, EYES)))

    def test_short_first_shot_is_fine_for_a_snap(self):
        self.assertFalse(any("lasts only" in i.message for i in pov.validate(GOOD_SNAP, SNAP)))
        self.assertTrue(any("lasts only" in i.message for i in core.validate(GOOD_SNAP, SNAP.core_request())))

    def test_repairs_are_asked_for(self):
        bad = GOOD_SNAP.replace("At 00:01.000", "At 00:02.000")
        found = pov.checks(bad, SNAP)
        msg = core.build_fix_message(pov.validate(bad, SNAP), found)
        self.assertIn("At 00:01.000, the camera cuts to a first-person POV from the girl's eyes", msg)


class NoFalseAlarms(unittest.TestCase):
    """Things that are right from her eyes must not be flagged (they would trigger a needless repair)."""

    def _outside(self, prompt, req=SNAP):
        return [m for m in misses(prompt, req) if "from the outside" in m]

    def test_her_hands_hair_and_nod_are_fine(self):
        for text in ("In the last second the POV shows the girl's hands around the white cup",
                     "In the last second a strand of the girl's hair falls at the edge of the frame",
                     "In the last second the girl nods and the POV dips slightly"):
            with self.subTest(text):
                ok = GOOD_SNAP.replace("In the last second the POV tilts down with small amplitude at slow speed to the "
                                       "white cup held in the girl's hands", text)
                self.assertNotEqual(ok, GOOD_SNAP)
                self.assertEqual(self._outside(ok), [])

    def test_her_face_or_smile_is_flagged(self):
        for text in ("In the last second the girl smiles", "In the last second a close-up of the girl",
                     "In the last second the girl's face lights up"):
            with self.subTest(text):
                bad = GOOD_SNAP.replace("In the last second the POV tilts down", text + " and the POV tilts down")
                self.assertTrue(self._outside(bad))

    def test_never_hands_ignores_other_peoples_hands(self):
        no_hands = pov.PovRequest(**{**SNAP.__dict__, "hands": "no"})
        other = GOOD_SNAP.replace("the girl's hands rise from the bottom of the frame and take it with both hands",
                                  "the girl takes it").replace("held in the girl's hands", "held up by the woman in "
                                                                                          "her hands")
        self.assertFalse(any("Hands:" in m for m in misses(other, no_hands)))

    def test_pronoun_is_not_a_label(self):
        for word in ("her", "She", "", "  "):
            self.assertEqual(pov.PovRequest(who=word).clamp().who, "girl")
        self.assertEqual(pov.PovRequest(who="The Woman").clamp().who, "woman")
        self.assertEqual(pov.PovRequest(who="girl's").clamp().who, "girl")

    def test_positions_belong_to_the_outside_shot(self):
        msg = pov.build_user_message(pov.PovRequest(**{**SNAP.__dict__}))
        self.assertIn("In the girl's POV, place people as she sees them", msg)
        self.assertIn("belong to [Shot 1]", msg)


class Installer(unittest.TestCase):
    def test_pov_tab_is_installed_and_enabled(self):
        import importlib.util
        path = Path(__file__).resolve().parents[1] / "bazzite" / "install.py"
        spec = importlib.util.spec_from_file_location("h3_install_pov", path)
        inst = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inst)
        for f in ("script.py", "pov_core.py", "pov_system_prompt.md"):
            self.assertIn(f"user_data/extensions/h3_pov_eyes/{f}", inst.H3_FILES)
        self.assertEqual(inst.EXTENSIONS, ("h3_i2v_director", "h3_pov_eyes"))


if __name__ == "__main__":
    unittest.main()
