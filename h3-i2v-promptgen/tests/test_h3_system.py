"""Tests for h3_system (GPU profiles, VRAM readout, model file picking)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "extensions" / "h3_i2v_director"))

import h3_system as s  # noqa: E402


class Profiles(unittest.TestCase):
    GPU = [{"name": "NVIDIA GeForce RTX 5080", "used_mb": 800, "total_mb": 16303, "free_mb": 15503, "driver": "580"}]

    def test_fit_is_default(self):
        self.assertEqual(s.DEFAULT_PROFILE, "fit")
        self.assertEqual(s.resolve_profile("full"), "full")
        self.assertEqual(s.resolve_profile("anything else"), "fit")

    def test_budget_margin_gpu_free(self):
        # 6.5 GB budget, 900 MB vision file: llama.cpp may use 6656 - 900 - 512 = 5244 MiB
        self.assertEqual(s.fit_margin_mb("fit", 6.5, 900, self.GPU), 15503 - 5244)

    def test_budget_margin_with_fooocus_loaded(self):
        busy = [dict(self.GPU[0], used_mb=8800, free_mb=7503)]
        self.assertEqual(s.fit_margin_mb("fit", 6.5, 900, busy), 7503 - 5244)

    def test_budget_never_below_floor(self):
        full = [dict(self.GPU[0], used_mb=13000, free_mb=3303)]
        self.assertEqual(s.fit_margin_mb("fit", 6.5, 900, full), 512)

    def test_full_and_no_gpu(self):
        self.assertEqual(s.fit_margin_mb("full", 6.5, 900, self.GPU), 1024)
        self.assertEqual(s.fit_margin_mb("fit", 6.5, 900, []), 1024)

    def test_load_args(self):
        args = s.load_args("mmproj-x.gguf", 10240, 9000)
        self.assertEqual(args["gpu_layers"], -1)
        self.assertEqual(args["fit_target"], "9000")
        self.assertFalse(args["cpu_moe"])
        self.assertEqual(args["mmproj"], "mmproj-x.gguf")
        self.assertEqual(args["ctx_size"], 10240)
        self.assertEqual(args["cache_type"], "q8_0")
        self.assertIsNone(s.load_args("", 8192, 1024)["mmproj"])


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
                                              "total_mb": 16303, "free_mb": 5039, "driver": "580.95.05"}])

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
