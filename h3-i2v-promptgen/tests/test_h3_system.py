"""Tests for h3_system (GPU profiles, VRAM readout, model file picking)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "extensions" / "h3_i2v_director"))

import h3_system as s  # noqa: E402


class Profiles(unittest.TestCase):
    def test_small_is_default(self):
        self.assertEqual(s.DEFAULT_PROFILE, "small")
        self.assertEqual(s.resolve_profile("small"), "small")
        self.assertEqual(s.resolve_profile("full"), "full")
        self.assertEqual(s.resolve_profile("anything else"), "small")

    def test_load_args(self):
        full = s.load_args("full", "mmproj-x.gguf", 16384, 1536)
        self.assertEqual(full["gpu_layers"], -1)
        self.assertEqual(full["fit_target"], "1536")
        self.assertFalse(full["cpu_moe"])
        self.assertEqual(full["mmproj"], "mmproj-x.gguf")
        self.assertEqual(full["loader"], "llama.cpp")
        small = s.load_args("small", "", 8192)
        self.assertTrue(small["cpu_moe"])
        self.assertGreater(small["gpu_layers"], 0)
        self.assertNotIn("fit_target", small)
        self.assertIsNone(small["mmproj"])
        self.assertEqual(small["ctx_size"], 8192)
        self.assertEqual(small["cache_type"], "q8_0")


class PickFiles(unittest.TestCase):
    def test_prefers_uncensored_q4(self):
        models = ["Qwen3-8B-Q4_K_M.gguf", "Inkling-2-Mini-Q8_0.gguf", "Inkling-2-Mini-Uncensored-Q4_K_M.gguf",
                  "Inkling-2-Mini-Uncensored-Q6_K.gguf", "mmproj-Inkling-2-Mini-F16.gguf"]
        mmprojs = ["mmproj-gemma-3-F16.gguf", "mmproj-Inkling-2-Mini-Uncensored-BF16.gguf"]
        self.assertEqual(s.pick_inkling(models, mmprojs),
                         ("Inkling-2-Mini-Uncensored-Q4_K_M.gguf", "mmproj-Inkling-2-Mini-Uncensored-BF16.gguf"))

    def test_no_inkling(self):
        self.assertEqual(s.pick_inkling(["Qwen3-8B-Q4_K_M.gguf"], []), ("", ""))


class Vram(unittest.TestCase):
    def test_parse_gpus(self):
        out = "NVIDIA GeForce RTX 5080, 11264, 16303, 580.95.05\n"
        self.assertEqual(s.parse_gpus(out), [{"name": "NVIDIA GeForce RTX 5080", "used_mb": 11264,
                                              "total_mb": 16303, "driver": "580.95.05"}])

    def test_parse_process_vram(self):
        out = "4242, 7980\n5150, 3412\n"
        self.assertEqual(s.parse_process_vram(out, 5150), 3412)
        self.assertIsNone(s.parse_process_vram(out, 1))
        self.assertIsNone(s.parse_process_vram("", 5150))

    def test_summary(self):
        self.assertIn("no NVIDIA GPU", s.gpu_summary([]))
        gpu = [{"name": "NVIDIA GeForce RTX 5080", "used_mb": 11264, "total_mb": 16303, "driver": "580.95"}]
        self.assertEqual(s.gpu_summary(gpu), "GPU: NVIDIA GeForce RTX 5080 · 11.0 / 15.9 GB in use")
        self.assertEqual(s.gpu_summary(gpu, 3412),
                         "GPU: NVIDIA GeForce RTX 5080 · 11.0 / 15.9 GB in use · Inkling uses 3.3 GB of it")


if __name__ == "__main__":
    unittest.main()
