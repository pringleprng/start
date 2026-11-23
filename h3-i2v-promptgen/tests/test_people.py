"""People and actions read from plain-language ideas (kept exactly: a girl stays a girl)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "extensions" / "h3_i2v_director"))

import h3_core as c  # noqa: E402


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
