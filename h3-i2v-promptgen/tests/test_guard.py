"""The one block every tab keeps lives in code, not in the model's rules (no tokens spent on it)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "user_data" / "extensions"
sys.path.insert(0, str(EXT / "h3_i2v_director"))

import h3_core as core  # noqa: E402

RULES = [EXT / "h3_i2v_director" / "system_prompt.md", EXT / "h3_pov_eyes" / "pov_system_prompt.md",
         EXT / "fooocus_inpaint" / "fooocus_system_prompt.md",
         ROOT / "user_data" / "instruction-templates" / "Inkling 2 - H3 Director.yaml"]


class Guard(unittest.TestCase):
    def test_not_in_any_rules(self):
        for path in RULES:
            text = path.read_text(encoding="utf-8").lower()
            for phrase in ("hard limit", "minor", "never write", "real, identifiable"):
                with self.subTest(path.name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_block_in_code(self):
        for text, blocked in (("woman standing next to girl the woman hands the girl a cup", False),
                              ("muscular women standing next to girl, muscular woman hands girl stick", False),
                              ("pregnant belly, pale skin", False), ("girl in a red swimsuit runs on the beach", False),
                              ("pregnant woman next to girl, pregnant belly", False),
                              ("nude girl", True), ("girl in lingerie", True), ("pregnant girl", True),
                              ("pregnant belly on girl", True), ("sexy boy", True)):
            with self.subTest(text):
                self.assertEqual(bool(core.blocked_reason(text)), blocked)
                self.assertEqual(bool(core.blocked_output(text)), blocked)

    def test_every_tab_checks_request_and_answer(self):
        for tab in ("h3_i2v_director", "h3_pov_eyes", "fooocus_inpaint"):
            src = (EXT / tab / "script.py").read_text(encoding="utf-8")
            with self.subTest(tab):
                self.assertIn("blocked_reason(", src)
                self.assertIn("blocked_output(", src)


if __name__ == "__main__":
    unittest.main()
