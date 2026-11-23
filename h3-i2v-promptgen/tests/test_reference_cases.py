"""Basic plain-language prompts with reference answers written to the H3 rules.

Every reference answer must pass the official format rules with no notes and match the
request (camera, shots, dialogue word for word, silence, music, the idea's key words).
Every broken variant must be caught. The same prompts run against the real model in the
tab's self-test.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "extensions" / "h3_i2v_director"))

import h3_core as core  # noqa: E402
import h3_selftest as st  # noqa: E402

CASES = {c.name: c for c in st.CASES}

REFERENCE = {
    "text-basic": """integrated_multimodal_description: [Shot 1] Live-action, cinematic, a low wide shot frames a red fox standing in fresh, knee-deep snow at the edge of a pine forest at sunrise, its thick orange coat glowing against the blue-white snow while low golden light rakes across the drifts. The fox lifts each black paw high and walks to the right through the powder, leaving a neat line of prints as loose snow sprays from its legs. The camera tracks alongside it at the same distance. Halfway across the frame the fox stops, its bushy white-tipped tail settling behind it, turns its head over its shoulder and looks straight back into the lens, ears upright and breath steaming in the cold air.

overall_soundscape: A quiet winter morning with a faint breeze through the pines. Soft crunching paw steps in fresh snow and the light hiss of powder falling from the fox's legs, then stillness as it stops.

non_diegetic_music: A sparse solo flute melody at a slow tempo over a soft sustained string chord that thins out as the fox looks back.""",

    "text-camera-no-music": """integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot at counter height frames a bright home kitchen in morning light, with a white ceramic cup of coffee standing near the edge of a wooden counter. The camera holds a static shot throughout. A grey tabby cat jumps up from the floor and lands on the counter, its paws skidding slightly on the smooth wood. It walks along the edge, brushes its side against the cup and knocks it over with one paw; the cup tips, rolls off the edge and drops out of frame, and coffee splashes across the counter as the cat freezes and stares down after it.

overall_soundscape: A quiet kitchen with the low hum of a refrigerator. Soft thuds as the cat lands, a ceramic scrape as the cup slides, then a sharp crash as the cup hits the floor below.

non_diegetic_music: N/A""",

    "text-dialogue-2-shots": """integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot frames a man in his thirties with short dark hair and a navy raincoat who waits under a glass bus stop shelter on a rainy city street at dusk, rain streaming off the shelter roof and headlights smearing across the wet asphalt behind him. He checks his phone, glances at the screen, then raises it to his ear. The camera pushes in with small amplitude at slow speed as the man with a calm, slightly hurried voice (S1) says: <d>[English] I'm on my way.</d> He lowers the phone and looks down the street. [Shot 2] At 00:05.500, the camera cuts to a wide shot from behind the same man at the shelter as a red city bus pulls in from the left, its wipers sweeping and headlights glaring through the rain, arriving at the curb and stopping with its doors folding open.

overall_soundscape: Heavy rain drums on the shelter roof and splashes in the gutters while traffic hisses past on the wet road. The bus engine grows louder, its brakes squeal softly and the doors open with a pneumatic hiss.

non_diegetic_music: A soft electric piano pattern at a moderate tempo over a muted bass pulse that rises slightly as the bus arrives.""",

    "text-silence": """integrated_multimodal_description: [Shot 1] Live-action, cinematic, a wide shot frames an empty playground at night under a single orange streetlamp, with a red slide, a still swing set and a small merry-go-round half buried in fresh snow. The camera holds a static shot. Large snowflakes fall slowly through the cone of lamplight, settling on the swing seats and the top of the slide, while the empty swings hang motionless and the snow on the ground deepens with a faint sparkle.

overall_soundscape: N/A

non_diegetic_music: N/A""",

    # the picture: a young woman with curly red hair in a green knit sweater on a park bench in autumn
    "picture-push-in": """For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot frames the young woman shown in <Picture 1> sitting on a wooden park bench among fallen autumn leaves, preserving her curly red hair, green knit sweater, the amber trees behind her and the soft afternoon light. The camera pushes in with small amplitude at slow speed toward her face. The person lifts her eyes to the lens and smiles, her cheeks rising and the corners of her eyes creasing. She raises her right hand and waves at the camera with an easy side-to-side motion, a few curls bouncing against her shoulder as a light breeze lifts leaves along the path behind her. She keeps smiling as her hand slows and settles back onto her knee.

overall_soundscape: A light breeze rustles the autumn leaves while distant birds chirp in the park. The wooden bench creaks softly as she shifts, and her sweater sleeve brushes against her side as she waves.

non_diegetic_music: Fingerpicked acoustic guitar at a slow tempo with a soft glockenspiel line that enters as she waves.""",

    # the picture: two young people side by side in a sunny town plaza with a fountain
    "picture-spanish-line": """For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot frames the two young people shown in <Picture 1> standing side by side in a sunny town plaza, preserving the man's white linen shirt, the woman's yellow sundress, the stone fountain behind them and the bright midday light. The camera holds a static shot. They turn to look straight at the camera and both raise a hand to greet their friends behind it. The young woman with a bright, clear voice (S1) says warmly: <d>[Spanish] ¡Hola, amigos!</d> The man beside her laughs and nods while she keeps waving, and the fountain sparkles behind them.

overall_soundscape: Water splashes in the stone fountain while distant voices and footsteps echo across the plaza. A short laugh from the man follows her greeting.

non_diegetic_music: A light Spanish guitar strum at a moderate tempo with soft hand percussion.""",
}


def messages(result):
    return [i.message for i in result.issues] + [c.message for c in result.checks if not c.ok]


class ReferenceAnswers(unittest.TestCase):
    def test_every_case_has_a_reference(self):
        self.assertEqual(sorted(REFERENCE), sorted(CASES))

    def test_references_pass_everything(self):
        for name, text in REFERENCE.items():
            with self.subTest(case=name):
                result = st.check(CASES[name], text)
                self.assertEqual(messages(result), [])
                self.assertTrue(result.passed)
                # autofix must leave a correct prompt as it is
                fixed, notes = core.autofix(text, st.make_request(CASES[name], 1 if CASES[name].needs_picture else 0))
                self.assertEqual(fixed, text)
                self.assertEqual(notes, [])

    def test_requests_carry_the_settings(self):
        msg = core.build_user_message(st.make_request(CASES["text-dialogue-2-shots"]))
        self.assertIn("MODE: T2VA. There is no picture.", msg)
        self.assertIn("DURATION: 10 seconds. Every cut time must be earlier than 00:10.000.", msg)
        self.assertIn("- Shots: exactly 2 shots with timed cuts.", msg)
        self.assertIn("Man: I'm on my way.", msg)
        self.assertIn("language tag: English", msg)
        msg = core.build_user_message(st.make_request(CASES["picture-push-in"], n_images=1))
        self.assertIn("<Picture 1>: the exact first frame of the video at 0.00 seconds", msg)
        self.assertIn("the camera pushes in with small amplitude at slow speed", msg)
        msg = core.build_user_message(st.make_request(CASES["text-silence"]))
        self.assertIn("complete silence. Write N/A for overall_soundscape and N/A for non_diegetic_music", msg)


class BrokenAnswersAreCaught(unittest.TestCase):
    def caught(self, case, text, needle):
        result = st.check(CASES[case], text)
        found = [m for m in messages(result) if needle in m]
        self.assertTrue(found, f"expected a finding containing {needle!r}, got {messages(result)}")
        self.assertFalse(result.passed if needle not in ("Hailuo 2.x", "moods", "never speaks", "off-screen voiceover",
                                                         "cut phrase", "dissolve", "style and composition") else False)

    def test_bracket_camera(self):
        self.caught("text-basic", REFERENCE["text-basic"].replace("The camera tracks alongside it", "[Truck right] It moves"),
                    "Hailuo 2.x")

    def test_shot_one_timestamp(self):
        self.caught("text-basic", REFERENCE["text-basic"].replace("[Shot 1] Live", "[Shot 1] At 00:00.000, Live"),
                    "must not have a timestamp")

    def test_missing_field(self):
        self.caught("text-basic", REFERENCE["text-basic"].split("\n\nnon_diegetic_music")[0], "non_diegetic_music field")

    def test_picture_in_t2va(self):
        self.caught("text-basic", REFERENCE["text-basic"].replace("a red fox", "the red fox shown in <Picture 1>"),
                    "unresolved reference label")

    def test_translated_line(self):
        self.caught("text-dialogue-2-shots", REFERENCE["text-dialogue-2-shots"].replace("I'm on my way.", "I am coming."),
                    "not word for word")

    def test_wrong_language_tag(self):
        self.caught("picture-spanish-line", REFERENCE["picture-spanish-line"].replace("[Spanish]", "[English]"),
                    "language tag")

    def test_camera_ignored(self):
        self.caught("text-camera-no-music",
                    REFERENCE["text-camera-no-music"].replace("The camera holds a static shot throughout.",
                                                              "The camera pans right."),
                    "static shot is missing")

    def test_amplitude_ignored(self):
        self.caught("picture-push-in", REFERENCE["picture-push-in"].replace(" with small amplitude", ""),
                    "with small amplitude")

    def test_wrong_shot_count(self):
        one_shot = REFERENCE["text-dialogue-2-shots"].split(" [Shot 2]")[0]
        one_shot += "\n\n" + REFERENCE["text-dialogue-2-shots"].split("\n\n", 1)[1]
        self.caught("text-dialogue-2-shots", one_shot, "asked for 2")

    def test_cut_outside_duration(self):
        self.caught("text-dialogue-2-shots", REFERENCE["text-dialogue-2-shots"].replace("00:05.500", "00:11.000"),
                    "outside the 10-second video")

    def test_invented_dialogue(self):
        self.caught("text-basic", REFERENCE["text-basic"].replace(
            "ears upright", "and a hunter (S1) says: <d>[English] There it is.</d> Its ears upright"),
            "Dialogue was added")

    def test_sound_when_silence_asked(self):
        self.caught("text-silence", REFERENCE["text-silence"].replace("overall_soundscape: N/A",
                                                                      "overall_soundscape: Wind howls."),
                    "Complete silence was asked")

    def test_music_mood_words(self):
        self.caught("text-basic", REFERENCE["text-basic"].replace("A sparse solo flute", "A nostalgic, heartwarming flute"),
                    "moods")

    def test_speaker_id_without_speech(self):
        self.caught("picture-spanish-line", REFERENCE["picture-spanish-line"].replace("The man beside her",
                                                                                      "The man (S2) beside her"),
                    "never speaks")

    def test_voiceover_wording(self):
        text = REFERENCE["text-dialogue-2-shots"].replace("(S1) says: <d>", "(S1) speaks in voice-over: <d>")
        self.caught("text-dialogue-2-shots", text, "off-screen voiceover")

    def test_cut_phrase(self):
        self.caught("text-dialogue-2-shots", REFERENCE["text-dialogue-2-shots"].replace(
            "At 00:05.500, the camera cuts to", "At 00:05.500, we see"), "cut phrase")

    def test_dissolve_not_asked(self):
        self.caught("text-dialogue-2-shots", REFERENCE["text-dialogue-2-shots"].replace(
            "the camera cuts to", "the shot cross-dissolves to"), "dissolve")

    def test_style_missing(self):
        self.caught("text-basic", REFERENCE["text-basic"].replace("Live-action, cinematic, a low wide shot frames",
                                                                  "A red fox and"), "style and composition")

    def test_idea_not_followed(self):
        text = REFERENCE["text-silence"].replace("an empty playground at night", "a busy beach at noon")
        text = text.replace("snow", "sand").replace("snowflakes fall", "waves roll")
        result = st.check(CASES["text-silence"], text)
        self.assertTrue(any("key words" in c.message and not c.ok for c in result.checks), messages(result))


if __name__ == "__main__":
    unittest.main()
