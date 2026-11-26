"""The Fooocus Inpaint tab (fooocus_core.py, fooocus_system_prompt.md)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "extensions" / "fooocus_inpaint"))

import fooocus_core as fc  # noqa: E402

SYSTEM = fc.load_system_prompt()


def example(n):
    return SYSTEM.split(f"# EXAMPLE {n}")[1].split("\n\n", 1)[1].split("\n\n# ")[0].strip()


REQS = {
    1: fc.InpaintRequest(idea="change her shirt to a red hoodie", area="her shirt", method="default", n_images=1),
    2: fc.InpaintRequest(idea="fix the girl's face", area="the girl's face", method="detail", n_images=1),
    3: fc.InpaintRequest(idea="add muscular woman holding stick", area="the grass on the right", method="modify", n_images=1),
    4: fc.InpaintRequest(idea="make it wider, more beach and sea", method="default", outpaint=["Left", "Right"], n_images=1),
    5: fc.InpaintRequest(idea="pregnant belly, pale skin", area="her stomach", method="auto", n_images=1),
}


def run(text, req):
    fields, notes = fc.autofix(fc.parse_answer(text), req)
    return fields, notes, fc.validate(fields, req), fc.checks(fields, req)


def misses(text, req):
    _, _, issues, found = run(text, req)
    return [i.message for i in issues if i.level == "error"] + [c.message for c in found if not c.ok]


class FooocusFacts(unittest.TestCase):
    """Fooocus 2.5.5: modules/flags.py (names) and webui.py inpaint_mode_change (values)."""

    def test_method_names(self):
        self.assertEqual(list(fc.METHODS.values()), ["Inpaint or Outpaint (default)",
                                                     "Improve Detail (face, hand, eyes, etc.)",
                                                     "Modify Content (add objects, change background, etc.)"])
        self.assertEqual(fc.OUTPAINT, ("Left", "Right", "Top", "Bottom"))

    def test_settings_per_method(self):
        self.assertEqual(fc.SETTINGS["default"], {"strength": 1.0, "field": 0.618, "engine": "v2.6", "no_initial_latent": False})
        self.assertEqual(fc.SETTINGS["detail"], {"strength": 0.5, "field": 0.0, "engine": "None", "no_initial_latent": False})
        self.assertEqual(fc.SETTINGS["modify"], {"strength": 1.0, "field": 0.0, "engine": "v2.6", "no_initial_latent": True})

    def test_settings_table(self):
        md = fc.settings_markdown(REQS[4])
        for text in ("| Method | Inpaint or Outpaint (default) |", "| Outpaint Direction | Left, Right |",
                     "| Inpaint Denoising Strength | 1 |", "| Inpaint Respective Field | 0.618", "| Inpaint Engine | v2.6 |",
                     "Developer Debug Mode → Inpaint"):
            self.assertIn(text, md)
        md = fc.settings_markdown(REQS[2])
        self.assertIn("| Inpaint Denoising Strength | 0.5 |", md)
        self.assertIn("| Inpaint Respective Field | 0 (only the masked area) |", md)
        self.assertNotIn("Outpaint Direction", md)
        self.assertIn("| Disable initial latent in inpaint | on |", fc.settings_markdown(REQS[3]))


class Examples(unittest.TestCase):
    def test_examples_pass(self):
        for n, req in REQS.items():
            with self.subTest(n):
                fields, notes, issues, found = run(example(n), req)
                self.assertEqual(notes, [])
                self.assertEqual([i.message for i in issues], [])
                self.assertEqual([c.message for c in found if not c.ok], [])
                self.assertEqual(bool(fields["additional"]), req.method != "default")

    def test_rules(self):
        self.assertNotIn("{", SYSTEM)
        self.assertIn("Fooocus splits a prompt at every line break", SYSTEM)
        self.assertIn("sexual, nude, underwear or pregnancy content for a girl, boy or child", SYSTEM)
        for word in ("older, younger", '"younger woman"'):
            self.assertIn(word, SYSTEM)


class Reading(unittest.TestCase):
    def test_messy_answer(self):
        text = ("Sure! Here are your prompts:\n\n```\n**Prompt:** a woman wearing a red cotton hoodie,\nsoft folds, photo\n"
                "**Inpaint Additional Prompt:** N/A\n**Negative prompt:** white shirt, blurry\n```\n\nEnjoy!")
        fields, notes = fc.autofix(fc.parse_answer(text), REQS[1])
        self.assertEqual(fields, {"prompt": "a woman wearing a red cotton hoodie, soft folds, photo", "additional": "",
                                  "negative": "white shirt, blurry"})
        self.assertTrue(any("one line" in n for n in notes))

    def test_default_method_has_no_additional_box(self):
        text = "PROMPT: a calm sea, photo\nADDITIONAL: wide sandy beach\nNEGATIVE: N/A"
        fields, notes = fc.autofix(fc.parse_answer(text), REQS[4])
        self.assertEqual(fields["additional"], "")
        self.assertTrue(fields["prompt"].startswith("wide sandy beach, a calm sea"))
        self.assertTrue(any("no additional box" in n for n in notes))

    def test_detail_and_modify_need_additional(self):
        for n in (2, 3):
            text = "PROMPT: a garden, photo\nADDITIONAL: N/A\nNEGATIVE: blurry"
            self.assertTrue(any("ADDITIONAL is empty" in m for m in misses(text, REQS[n])))

    def test_no_negative_chosen(self):
        req = fc.InpaintRequest(idea="change her shirt to a red hoodie", negative="none", n_images=1)
        fields, notes = fc.autofix(fc.parse_answer(example(1)), req)
        self.assertEqual(fields["negative"], "")
        self.assertIn("NEGATIVE: N/A (the user wants no negative prompt).", fc.build_user_message(req))


class Mistakes(unittest.TestCase):
    def test_wanted_things_in_negative(self):
        bad = example(1).replace("NEGATIVE: white shirt", "NEGATIVE: red hoodie, white shirt")
        self.assertTrue(any("NEGATIVE contains what you asked for: red hoodie" in m for m in misses(bad, REQS[1])))
        ok = example(2).replace("NEGATIVE: blurry face", "NEGATIVE: deformed face, blurry face")
        self.assertFalse(any("NEGATIVE contains" in m for m in misses(ok, REQS[2])))
        removal = fc.InpaintRequest(idea="remove the lamp from the table", area="the lamp", n_images=1)
        text = "PROMPT: an empty wooden table, soft light, photo\nADDITIONAL: N/A\nNEGATIVE: lamp, lampshade, blurry"
        self.assertFalse(any("NEGATIVE contains" in m for m in misses(text, removal)))

    def test_ruling_out_the_old_look_is_fine(self):
        req = fc.InpaintRequest(idea="make the sky a clear blue sky with a few small white clouds", area="the sky", n_images=1)
        text = ("PROMPT: a clear blue sky with a few small white clouds, bright daylight, photo\nADDITIONAL: N/A\n"
                "NEGATIVE: grey sky, storm clouds, visible seams")
        self.assertFalse(any("NEGATIVE contains" in m for m in misses(text, req)))
        self.assertTrue(any("NEGATIVE contains what you asked for: blue sky" in m
                            for m in misses(text.replace("grey sky", "blue sky"), req)))

    def test_people_words(self):
        for wrong, needle in (("detailed younger woman face", 'call her "the girl"'), ("detailed child face", '"child" is used'),
                              ("detailed little girl face", "ages were added")):
            with self.subTest(wrong):
                bad = example(2).replace("detailed girl face", wrong)
                self.assertTrue(any(needle in m for m in misses(bad, REQS[2])), misses(bad, REQS[2]))
        plain = example(3).replace("muscular ", "")
        self.assertTrue(any('write "muscular woman"' in m for m in misses(plain, REQS[3])))

    def test_video_prompt_text(self):
        bad = example(1).replace("PROMPT: a woman", "PROMPT: [Shot 1] Live-action, a woman")
        self.assertTrue(any("video-prompt text" in m for m in misses(bad, REQS[1])))

    def test_long_prompt_note(self):
        long = "PROMPT: " + ", ".join(["a red cotton hoodie"] * 30) + "\nADDITIONAL: N/A\nNEGATIVE: blurry"
        _, _, issues, _ = run(long, REQS[1])
        self.assertTrue(any("75 tokens" in i.message for i in issues if i.level == "warning"))


class UsersWords(unittest.TestCase):
    def test_request_in_the_users_style(self):
        req = fc.InpaintRequest(idea="muscular women hands girl stick, change girl shirt to red hoodie", area="girl shirt",
                                method="modify", n_images=1)
        msg = fc.build_user_message(req)
        self.assertIn("exactly one woman and one girl", msg)
        self.assertIn('Call them "the muscular woman" and "the girl" every time.', msg)
        self.assertNotIn("the change girl", msg)
        self.assertNotIn("name the person at the start", msg)   # video-only rules are left out
        self.assertNotIn("- Action", msg)
        self.assertIn("METHOD: Modify Content (add objects, change background, etc.).", msg)
        self.assertIn("MASKED AREA (the user's words): girl shirt", msg)

    def test_mask_and_outpaint_in_the_request(self):
        msg = fc.build_user_message(fc.InpaintRequest(idea="x", n_images=1, has_mask=True, outpaint=["Top"]))
        self.assertIn("The red-tinted part is the masked area", msg)
        self.assertIn("OUTPAINT DIRECTION: Top.", msg)
        self.assertEqual(fc.InpaintRequest(method="detail", outpaint=["Top"]).clamp().outpaint, [])


class InpaintFocus(unittest.TestCase):
    """Short keyword ideas like "pregnant belly, pale skin" get the best inpaint prompt."""

    def test_auto_picks_the_method(self):
        for idea, method in (("pregnant belly, pale skin", "default"), ("longer blonde hair", "default"),
                             ("red hoodie", "default"), ("change girl shirt to red hoodie", "default"),
                             ("detailed hands", "detail"), ("sharper face with clear eyes", "detail"),
                             ("add a red wooden bench", "modify"), ("remove the lamp", "modify"),
                             ("new background, a beach at sunset", "modify")):
            with self.subTest(idea):
                r = fc.InpaintRequest(idea=idea, method="auto").clamp()
                self.assertEqual(r.method, method)
                self.assertTrue(r.auto_reason)
        self.assertEqual(fc.InpaintRequest(idea="x", method="auto", outpaint=["Left"]).clamp().method, "default")
        self.assertEqual(fc.InpaintRequest(idea="add a bench", method="detail").clamp().auto_reason, "")

    def test_keywords_word_for_word(self):
        self.assertEqual(fc.required_phrases("pregnant belly, pale skin"), ["pregnant belly", "pale skin"])
        self.assertEqual(fc.required_phrases("detailed hands"), ["detailed hands"])
        self.assertEqual(fc.required_phrases("change girl shirt to red hoodie"), [])
        msg = fc.build_user_message(REQS[5])
        self.assertIn('word for word near the start of PROMPT: "pregnant belly", "pale skin"', msg)
        self.assertIn('plain words "woman" or "man" for adults', msg)
        bad_negative = "PROMPT: a girl with a rounded stomach, fair skin, photo\nADDITIONAL: N/A\nNEGATIVE: pregnant belly, blurry"
        self.assertTrue(any("NEGATIVE contains what you asked for: pregnant belly" in m for m in misses(bad_negative, REQS[5])))
        swapped = example(5).replace("pregnant belly", "rounded stomach").replace("pale skin", "fair skin")
        self.assertTrue(any('Your words missing word for word: "pregnant belly", "pale skin"' in m
                            for m in misses(swapped, REQS[5])))

    def test_body_edit_tips(self):
        md = fc.settings_markdown(REQS[5])
        self.assertIn("(picked by Auto)", md)
        self.assertIn("mask a little beyond where the new shape will reach", md)
        self.assertIn("switch the method to Modify Content", md)
        self.assertNotIn("beyond where", fc.settings_markdown(fc.InpaintRequest(idea="detailed hands", method="auto")))

    def test_only_one_line_is_kept(self):
        """Everything is written as asked, except sexual, nude, underwear or pregnancy edits for a girl, boy or child."""
        for idea, blocked in (("pregnant belly, pale skin", False), ("baby bump, pale skin", False),
                              ("bigger baby bump", False), ("girl's belly bigger", False), ("girl with muscular arms", False),
                              ("longer hair on girl", False), ("red hoodie on girl", False),
                              ("pregnant woman next to girl, pregnant belly", False),
                              ("muscular woman standing next to girl, pregnant belly on the woman, pale skin", False),
                              ("change girl shirt to red hoodie", False),
                              ("pregnant belly on girl", True), ("girl pregnant belly", True), ("pregnant girl", True),
                              ("girl, pregnant belly", True), ("girl baby bump", True), ("topless girl", True),
                              ("girl in lingerie", True), ("sexy girl", True), ("nude boy", True)):
            with self.subTest(idea):
                self.assertEqual(bool(fc.blocked_reason(idea)), blocked)
        self.assertIn("Everything else it writes as you ask", fc.blocked_reason("pregnant belly on girl"))

    def test_what_the_model_wrote(self):
        self.assertTrue(fc.blocked_output({"prompt": "a girl with a pregnant belly, pale skin", "additional": ""}))
        self.assertFalse(fc.blocked_output({"prompt": example(5).split("\n")[0], "additional": ""}))
        self.assertFalse(fc.blocked_output({"prompt": "a girl with muscular arms, photo", "additional": ""}))
        # an unnamed person in a pregnancy edit called "girl": one repair, no forced word
        bad = example(5).replace("a woman with a pregnant belly", "a girl with a pregnant belly")
        found = misses(bad, REQS[5])
        self.assertTrue(any("Name the person as the picture shows them" in m for m in found), found)
        # any other edit: "girl" is simply kept
        arms = fc.InpaintRequest(idea="muscular arms", n_images=1)
        text = "PROMPT: a girl with muscular arms, photo\nADDITIONAL: N/A\nNEGATIVE: blurry"
        self.assertFalse(any(m.startswith("People") for m in misses(text, arms)))

    def test_rules_say_write_what_is_asked(self):
        self.assertIn("Write what the user asks for.", SYSTEM)
        self.assertNotIn("anyone who could be a minor", SYSTEM)
        self.assertNotIn("Body edits are for adults", SYSTEM)


class Installer(unittest.TestCase):
    def test_tab_is_installed_and_enabled(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("h3_install_fooocus", ROOT / "bazzite" / "install.py")
        inst = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inst)
        for f in ("script.py", "fooocus_core.py", "fooocus_system_prompt.md"):
            self.assertIn(f"user_data/extensions/fooocus_inpaint/{f}", inst.H3_FILES)
        self.assertIn("fooocus_inpaint", inst.EXTENSIONS)


if __name__ == "__main__":
    unittest.main()
