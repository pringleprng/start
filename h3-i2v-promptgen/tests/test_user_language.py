"""Ideas written the way this tool's user writes them: lowercase, no "the"/"a", run-on, "women" for one
woman, a dangling "woman's", "muscular woman" and "girl" as the only labels. For each idea, in both tabs:
what the model is told, a correct prompt passes, and each likely mistake is caught."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "extensions" / "h3_i2v_director"))
sys.path.insert(0, str(ROOT / "user_data" / "extensions" / "h3_pov_eyes"))

import h3_core as core  # noqa: E402
import pov_core as pov  # noqa: E402

LINE = core.I2VA_LINE

STICK = (LINE + """

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot frames the muscular woman and the girl shown in <Picture 1> standing side by side in a sunny park, the muscular woman on the left and the girl on the right, preserving the muscular woman's broad shoulders, defined arms and grey tank top, the girl's ponytail and red hoodie, the wooden stick in the muscular woman's right hand and the soft afternoon light from the left. The camera holds a static shot. At first the muscular woman turns to the girl and holds out the wooden stick. Midway, the muscular woman hands the stick to the girl, and the girl takes the stick from the muscular woman with both hands. In the last second the girl holds the stick up and looks at it, and the muscular woman lowers her empty hand to her side.

overall_soundscape: Light wind through the park trees and distant birdsong. A soft scrape of wood against skin as the stick passes from the muscular woman's hand into the girl's hands.

non_diegetic_music: A light acoustic guitar pattern at a moderate tempo that ends on one warm chord.""")

CUP = (LINE + """

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot frames the woman and the girl shown in <Picture 1> standing side by side in a sunlit kitchen, the woman on the left and the girl on the right, preserving the woman's shoulder-length brown hair and blue cardigan, the girl's two short braids and yellow T-shirt, the white ceramic cup in the woman's right hand and the soft window light from the left. The camera holds a static shot. At first the woman turns toward the girl and holds out the cup. Midway, the woman hands the cup to the girl, and the girl takes it with both hands. In the last second the girl looks down into the cup and smiles, and the woman lowers her empty hand to her side.

overall_soundscape: Quiet kitchen ambience with a ticking wall clock. A light ceramic clink as the cup passes from the woman's hand to the girl's hands.

non_diegetic_music: A soft solo piano melody at a slow tempo with sparse, quiet chords.""")

LIFT = (LINE + """

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot frames the muscular woman and the girl shown in <Picture 1> standing next to each other on a sandy beach, the muscular woman on the left and the girl on the right, preserving the muscular woman's broad shoulders and black sports top, the girl's curly hair and blue swimsuit and the warm evening light from the right. The camera holds a static shot. At first the muscular woman bends her knees and reaches toward the girl. Midway, the muscular woman picks up the girl and lifts the girl onto her hip in one smooth move. In the last second the girl wraps her arms around the muscular woman's neck and laughs, and the muscular woman stands steady on the sand.

overall_soundscape: Gentle waves wash onto the sand under a light breeze. A soft grunt of effort as the girl is lifted, then bright laughter.

non_diegetic_music: A light ukulele pattern at a moderate tempo with soft hand claps.""")

HAND_HOLD = (LINE + """

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium wide shot frames the muscular woman and the girl shown in <Picture 1> walking side by side along a sandy beach, the muscular woman on the left and the girl on the right, preserving the muscular woman's broad shoulders and black sports top, the girl's curly hair and blue swimsuit and the warm evening light from the right. The camera tracks alongside them at slow speed. At first the muscular woman reaches down and holds the girl's hand. Midway, the muscular woman and the girl swing their joined hands as they walk, wet sand pressing under their feet. In the last second the girl looks up at the muscular woman, and the two keep walking hand in hand toward the water.

overall_soundscape: Waves roll onto the beach under a steady breeze. Soft footsteps on wet sand and a few gull calls in the distance.

non_diegetic_music: A gentle acoustic guitar melody at a slow tempo.""")

# the user's phrasings -> a correct prompt, and the sentence that carries the action (to reverse it)
CASES = {
    "first phrasing, no comma": (
        "woman standing next to girl the woman hands the girl a cup", CUP,
        ("the woman hands the cup to the girl, and the girl takes it", "the girl hands the cup to the woman, and the woman takes it")),
    "women for one woman, dangling woman's": (
        "muscular women standing next to girl, muscular woman hands girl stick and the girl takes the stick from "
        "muscular woman's", STICK,
        ("the muscular woman hands the stick to the girl, and the girl takes the stick from the muscular woman",
         "the girl hands the stick to the muscular woman, and the muscular woman takes the stick from the girl")),
    "muscular woman and girl": (
        "muscular woman and girl, muscular woman hands girl a stick", STICK,
        ("the muscular woman hands the stick to the girl", "the girl hands the stick to the muscular woman")),
    "run-on, no commas": (
        "muscular woman standing next to girl muscular woman hands girl stick girl takes stick", STICK,
        ("the muscular woman hands the stick to the girl", "the girl hands the stick to the muscular woman")),
    "picks up": (
        "muscular woman standing next to girl muscular woman picks up girl", LIFT,
        ("the muscular woman picks up the girl and lifts the girl onto her hip",
         "the girl picks up the muscular woman and lifts the muscular woman onto her hip")),
    "holds hand": (
        "muscular woman and girl walk along the beach, muscular woman holds girl hand", HAND_HOLD,
        ("the muscular woman reaches down and holds the girl's hand", "the girl reaches up and holds the muscular woman's hand")),
}


def misses(prompt, idea):
    req = core.Request(mode="I2VA", idea=idea, duration=5, n_images=1).clamp()
    return [c.message for c in core.fidelity(prompt, req) if not c.ok]


class Reading(unittest.TestCase):
    def test_one_woman_one_girl_in_the_users_words(self):
        for name, (idea, _, _) in CASES.items():
            with self.subTest(name):
                people = [(p.cls, p.count) for p in core.parse_people(idea)]
                self.assertEqual(sorted(people), [("girl", 1), ("woman", 1)])
                msg = core.build_user_message(core.Request(mode="I2VA", idea=idea, n_images=1).clamp())
                self.assertIn("exactly one woman and one girl", msg)
                label = "the muscular woman" if "muscular" in idea else "the woman"
                self.assertIn(f'Call them "{label}" and "the girl" every time', msg)
                self.assertIn("older, younger", msg)
                self.assertNotRegex(msg, r'"the (?:stick|up|hands|takes) girl"')
                self.assertIn("Action, keep the direction exactly", msg)

    def test_the_action_direction_is_read(self):
        expected = {"first phrasing, no comma": [("woman", "hand", "girl")],
                    "women for one woman, dangling woman's": [("woman", "hand", "girl"), ("girl", "take", "woman")],
                    "muscular woman and girl": [("woman", "hand", "girl")],
                    "run-on, no commas": [("woman", "hand", "girl")],
                    "picks up": [("woman", "lift", "girl")],
                    "holds hand": [("woman", "hold", "girl")]}
        for name, (idea, _, _) in CASES.items():
            with self.subTest(name):
                self.assertEqual([(a.actor, a.verb, a.receiver) for a in core.parse_actions(idea)], expected[name])


class OriginalTab(unittest.TestCase):
    def test_correct_prompts_pass(self):
        for name, (idea, prompt, _) in CASES.items():
            with self.subTest(name):
                req = core.Request(mode="I2VA", idea=idea, duration=5, n_images=1).clamp()
                self.assertEqual([i.message for i in core.validate(prompt, req) if i.level == "error"], [])
                self.assertEqual(misses(prompt, idea), [])

    def test_mistakes_are_caught(self):
        for name, (idea, prompt, (action, flipped)) in CASES.items():
            woman = "muscular woman" if "muscular" in idea else "woman"
            with self.subTest(name, mistake="two women"):
                bad = prompt.replace(f"the {woman} and the girl shown", f"two {woman.replace('woman', 'women')} and the girl shown")
                self.assertTrue(any("several women" in m for m in misses(bad, idea)))
            with self.subTest(name, mistake="younger woman"):
                bad = prompt.replace("the girl", "the younger woman")
                self.assertTrue(any('call her "the girl"' in m for m in misses(bad, idea)))
            with self.subTest(name, mistake="age added"):
                bad = prompt.replace("the girl on the right", "the little girl on the right")
                self.assertTrue(any("ages were added" in m for m in misses(bad, idea)))
            with self.subTest(name, mistake="action reversed"):
                self.assertIn(action, prompt)
                bad = prompt.replace(action, flipped)
                self.assertTrue(any(m.startswith(("Action reversed", "Action:")) for m in misses(bad, idea)), misses(bad, idea))
            if "muscular" in idea:
                with self.subTest(name, mistake="muscular dropped"):
                    bad = prompt.replace("muscular ", "")
                    self.assertTrue(any("show the woman as muscular" in m for m in misses(bad, idea)))


POV_STICK = (LINE + """

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot frames the muscular woman and the girl shown in <Picture 1> standing face to face in a sunny park, the muscular woman on the left and the girl on the right, preserving the muscular woman's broad shoulders and grey tank top, the girl's ponytail and red hoodie, the wooden stick in the muscular woman's right hand and the soft afternoon light. The girl looks up at the muscular woman. [Shot 2] At 00:01.000, the camera cuts to a first-person POV from the girl's eyes, at the girl's eye height, looking up at the muscular woman, who stands close in front of the lens in the same grey tank top, in the same soft afternoon light. The POV holds steady with a small natural sway. At first the muscular woman looks down into the lens and holds out the wooden stick. Midway, the muscular woman hands the stick to the girl, and the girl's hands rise from the bottom of the frame and take the stick from the muscular woman. In the last second the POV tilts down with small amplitude at slow speed to the wooden stick held in the girl's hands.

overall_soundscape: Light wind through the park trees and distant birdsong. The girl's soft breathing close to the camera, then a light scrape of wood as the stick passes into the girl's hands.

non_diegetic_music: A light acoustic guitar pattern at a moderate tempo that ends on one warm chord.""")


class PovTab(unittest.TestCase):
    IDEAS = (CASES["women for one woman, dangling woman's"][0], CASES["muscular woman and girl"][0],
             CASES["run-on, no commas"][0])

    def r(self, idea):
        return pov.PovRequest(idea=idea, mode="snap", snap_at=1.0, duration=5, n_images=1).clamp()

    def pov_misses(self, prompt, idea):
        return [c.message for c in pov.checks(prompt, self.r(idea)) if not c.ok]

    def test_request_and_correct_prompt(self):
        for idea in self.IDEAS:
            with self.subTest(idea):
                msg = pov.build_user_message(self.r(idea))
                self.assertIn('Call them "the muscular woman" and "the girl" every time', msg)
                self.assertIn("exactly one woman and one girl", msg)
                self.assertEqual([i.message for i in pov.validate(POV_STICK, self.r(idea)) if i.level == "error"], [])
                self.assertEqual(self.pov_misses(POV_STICK, idea), [])

    def test_mistakes_are_caught(self):
        idea = self.IDEAS[0]
        self.assertTrue(any('call her "the girl"' in m for m in
                            self.pov_misses(POV_STICK.replace("the girl", "the younger woman"), idea)))
        self.assertTrue(any("show the woman as muscular" in m for m in
                            self.pov_misses(POV_STICK.replace("muscular ", ""), idea)))
        self.assertTrue(any("several women" in m for m in self.pov_misses(
            POV_STICK.replace("the muscular woman and the girl shown", "two muscular women and the girl shown"), idea)))


if __name__ == "__main__":
    unittest.main()
