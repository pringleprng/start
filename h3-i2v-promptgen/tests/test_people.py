"""People and actions read from plain-language ideas (kept exactly: a girl stays a girl)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "extensions" / "h3_i2v_director"))

import h3_core as c  # noqa: E402

core = c


def people(idea):
    return [(p.cls, p.count) for p in c.parse_people(idea)]


def actions(idea):
    return [(a.actor_adj, a.actor, a.verb, a.receiver_adj, a.receiver) for a in c.parse_actions(idea)]


class ParsePeople(unittest.TestCase):
    def test_woman_and_girl(self):
        idea = "a woman standing next to a girl, the woman hands the girl a cup"
        self.assertEqual(people(idea), [("woman", 1), ("girl", 1)])
        self.assertEqual(actions(idea), [("", "woman", "hand", "", "girl")])

    def test_direction_reversed_in_idea(self):
        idea = "a woman and a little girl; the girl gives the woman a flower"
        self.assertEqual(people(idea), [("woman", 1), ("girl", 1)])
        self.assertEqual(actions(idea), [("", "girl", "give", "", "woman")])

    def test_two_women_with_user_labels(self):
        idea = "two women sit at a cafe table and the older woman pours tea for the younger woman"
        self.assertEqual(people(idea), [("woman", 2)])
        self.assertEqual(c.parse_people(idea)[0].adjectives, ["older", "younger"])
        self.assertEqual(actions(idea), [("older", "woman", "pour", "younger", "woman")])

    def test_family_words(self):
        self.assertEqual(people("a mom hands her son a sandwich"), [("mother", 1), ("son", 1)])
        self.assertEqual(actions("a mom hands her son a sandwich"), [("", "mother", "hand", "", "son")])

    def test_compounds_and_false_friends(self):
        self.assertEqual(people("a baby girl sleeps while her father watches"), [("girl", 1), ("father", 1)])
        self.assertEqual(people("a man-made lake at dawn, a woman rows a boat"), [("woman", 1)])
        self.assertEqual(people("a human figure made of light"), [])

    def test_counts(self):
        self.assertEqual(people("three boys kick a ball"), [("boy", 3)])
        self.assertEqual(people("a woman meets another woman"), [("woman", 2)])
        self.assertEqual(people("the woman walks her dog"), [("woman", 1)])

    def test_other_languages_are_left_alone(self):
        self.assertEqual(people("una mujer le da una taza a una niña"), [])


if __name__ == "__main__":
    unittest.main()


class QuickTypedIdea(unittest.TestCase):
    """Typed quickly: "women" for one woman, no "the", "takes ... from", a dangling "woman's"."""

    IDEA = ("muscular women standing next to girl, muscular woman hands girl stick and the girl takes the stick "
            "from muscular woman's")
    GOOD = """For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot frames the muscular woman and the girl shown in <Picture 1> standing side by side in a sunny park, the muscular woman on the left and the girl on the right, preserving the muscular woman's broad shoulders, defined arms and grey tank top, the girl's ponytail and red hoodie, the wooden stick in the muscular woman's right hand and the soft afternoon light from the left. The camera holds a static shot. At first the muscular woman turns to the girl and holds out the wooden stick. Midway, the muscular woman hands the stick to the girl, and the girl takes the stick from the muscular woman with both hands. In the last second the girl holds the stick up and looks at it, and the muscular woman lowers her empty hand to her side.

overall_soundscape: Light wind through the park trees and distant birdsong. A soft scrape of wood against skin as the stick passes from the muscular woman's hand into the girl's hands.

non_diegetic_music: A light acoustic guitar pattern at a moderate tempo that ends on one warm chord."""

    def req(self):
        return core.Request(mode="I2VA", idea=self.IDEA, duration=5, n_images=1).clamp()

    def misses(self, prompt):
        return [x.message for x in core.fidelity(prompt, self.req()) if not x.ok]

    def test_reading(self):
        people = core.parse_people(self.IDEA)
        self.assertEqual([(p.cls, p.count, p.adjectives) for p in people], [("woman", 1, ["muscular"]), ("girl", 1, [])])
        acts = core.parse_actions(self.IDEA)
        self.assertEqual([(a.actor, a.verb, a.receiver, a.taken_from) for a in acts],
                         [("woman", "hand", "girl", False), ("girl", "take", "woman", True)])
        msg = core.build_user_message(self.req())
        self.assertIn("exactly one woman and one girl", msg)
        self.assertIn('Call them "the muscular woman" and "the girl" every time', msg)
        self.assertIn('"muscular women" in the idea means this one person: the muscular woman. Show one woman', msg)
        self.assertIn("(the muscular woman does it, the girl receives it)", msg)
        self.assertIn("(the girl takes it from the muscular woman)", msg)
        self.assertNotIn("hands girl\"", msg)

    def test_correct_prompt_passes(self):
        self.assertEqual([i.message for i in core.validate(self.GOOD, self.req()) if i.level == "error"], [])
        self.assertEqual(self.misses(self.GOOD), [])

    def test_mistakes_are_caught(self):
        two = self.GOOD.replace("the muscular woman and the girl shown", "two muscular women and the girl shown")
        self.assertTrue(any("several women" in m for m in self.misses(two)))
        plain = self.GOOD.replace("muscular ", "")
        self.assertTrue(any('show the woman as muscular' in m for m in self.misses(plain)))
        flipped = self.GOOD.replace(
            "the muscular woman hands the stick to the girl, and the girl takes the stick from the muscular woman",
            "the girl hands the stick to the muscular woman, and the muscular woman takes the stick from the girl")
        found = self.misses(flipped)
        self.assertTrue(any(m.startswith("Action reversed") and "hands girl stick" in m for m in found), found)
        self.assertTrue(any(m.startswith("Action reversed") and "takes the stick" in m for m in found), found)
        aged = self.GOOD.replace("the girl on the right", "the little girl on the right")
        self.assertTrue(any("ages were added" in m for m in self.misses(aged)))

    def test_hand_as_a_body_part_is_not_handing(self):
        idea = "the woman hands the girl a cup"
        req = core.Request(mode="T2VA", idea=idea, duration=5).clamp()
        desc = ("integrated_multimodal_description: [Shot 1] Live-action, a medium shot frames the woman on the left "
                "and the girl on the right. The woman raises her right hand and waves to the girl.\n\n"
                "overall_soundscape: Birdsong.\n\nnon_diegetic_music: N/A")
        self.assertTrue(any("is not described" in x.message for x in core.fidelity(desc, req) if not x.ok))

    def test_still_two_when_the_idea_says_so(self):
        for idea, n in (("two muscular women stand next to a girl", 2),
                        ("women stand around a girl and a woman hands her a cup", 2),
                        ("the older woman pours tea for the younger woman", 2),
                        ("muscular women train in a gym", 2)):
            with self.subTest(idea):
                self.assertEqual([p.count for p in core.parse_people(idea) if p.cls == "woman"], [n])

    def test_verbs_are_not_descriptions(self):
        for idea in ("the woman hands girl a cup", "she sees girl", "the man helps boy"):
            with self.subTest(idea):
                for p in core.parse_people(idea):
                    if p.cls in ("girl", "boy"):
                        self.assertEqual(p.adjectives, [])
