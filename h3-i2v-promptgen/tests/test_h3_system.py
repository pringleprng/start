"""Tests for h3_system (GPU profiles, Fooocus detection, model file picking)."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "extensions" / "h3_i2v_director"))

import h3_system as s  # noqa: E402


class Profiles(unittest.TestCase):
    def test_auto_follows_fooocus(self):
        self.assertEqual(s.resolve_profile("auto", True), "share")
        self.assertEqual(s.resolve_profile("auto", False), "full")
        self.assertEqual(s.resolve_profile("share", False), "share")
        self.assertEqual(s.resolve_profile("nonsense", True), "full")

    def test_load_args(self):
        full = s.load_args("full", "mmproj-x.gguf", 16384, 1536)
        self.assertEqual(full["gpu_layers"], -1)
        self.assertEqual(full["fit_target"], "1536")
        self.assertFalse(full["cpu_moe"])
        self.assertEqual(full["mmproj"], "mmproj-x.gguf")
        self.assertEqual(full["loader"], "llama.cpp")
        share = s.load_args("share", "", 8192)
        self.assertTrue(share["cpu_moe"])
        self.assertGreater(share["gpu_layers"], 0)
        self.assertNotIn("fit_target", share)
        self.assertIsNone(share["mmproj"])
        self.assertEqual(share["ctx_size"], 8192)


class PickFiles(unittest.TestCase):
    def test_prefers_uncensored_q4(self):
        models = ["Qwen3-8B-Q4_K_M.gguf", "Inkling-2-Mini-Q8_0.gguf", "Inkling-2-Mini-Uncensored-Q4_K_M.gguf",
                  "Inkling-2-Mini-Uncensored-Q6_K.gguf", "mmproj-Inkling-2-Mini-F16.gguf"]
        mmprojs = ["mmproj-gemma-3-F16.gguf", "mmproj-Inkling-2-Mini-Uncensored-BF16.gguf"]
        self.assertEqual(s.pick_inkling(models, mmprojs),
                         ("Inkling-2-Mini-Uncensored-Q4_K_M.gguf", "mmproj-Inkling-2-Mini-Uncensored-BF16.gguf"))

    def test_no_inkling(self):
        self.assertEqual(s.pick_inkling(["Qwen3-8B-Q4_K_M.gguf"], []), ("", ""))


class Fooocus(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _proc(self, pid, cmd, cwd):
        d = self.tmp / "proc" / str(pid)
        d.mkdir(parents=True)
        (d / "cmdline").write_bytes(b"\0".join(c.encode() for c in cmd) + b"\0")
        os.symlink(cwd, d / "cwd")

    def test_detects_processes(self):
        fooocus = self.tmp / "AI" / "Fooocus"
        fooocus.mkdir(parents=True)
        self._proc(101, ["python", "entry_with_update.py", "--listen"], str(fooocus))
        self._proc(102, ["/home/me/fooocus_env/bin/python3", "/home/me/Fooocus/launch.py"], "/home/me")
        self._proc(103, ["python", "server.py", "--portable"], "/home/me/textgen")
        self._proc(104, ["bash", "fooocus.sh"], "/home/me")
        (self.tmp / "proc" / "self").mkdir()
        found = s.fooocus_processes(self.tmp / "proc")
        self.assertEqual(sorted(p["pid"] for p in found), [101, 102])

    def test_output_dirs_and_newest_images(self):
        home = self.tmp / "home"
        root = home / "Fooocus"
        day1, day2 = root / "outputs" / "2026-11-21", root / "outputs" / "2026-11-22"
        day1.mkdir(parents=True)
        day2.mkdir(parents=True)
        custom = self.tmp / "elsewhere"
        custom.mkdir()
        old, mid, new = day1 / "a.png", day2 / "b.jpg", custom / "c.webp"
        for i, f in enumerate((old, mid, new)):
            f.write_bytes(b"x")
            os.utime(f, (time.time() - 100 + i, time.time() - 100 + i))
        (day2 / "log.html").write_text("not an image")

        dirs = s.fooocus_output_dirs("", processes=[], home=home)
        self.assertEqual(dirs, [root / "outputs"])
        self.assertEqual(s.newest_images(dirs, 2), [old, mid])

        # config.txt path_outputs of a running Fooocus wins over the default folder
        (root / "config.txt").write_text(json.dumps({"path_outputs": str(custom)}))
        dirs = s.fooocus_output_dirs("", processes=[{"pid": 1, "cwd": str(root)}], home=home)
        self.assertEqual(dirs[0], custom)
        self.assertEqual(s.newest_images(dirs, 1), [new])

        # an explicit folder is used as is
        self.assertEqual(s.fooocus_output_dirs(str(day1), processes=[], home=home), [day1])
        self.assertEqual(s.fooocus_output_dirs(str(self.tmp / "missing"), processes=[], home=home), [])

    def test_gpu_summary_without_gpu(self):
        self.assertIn("no NVIDIA GPU", s.gpu_summary([]))
        self.assertEqual(s.gpu_summary([{"name": "NVIDIA GeForce RTX 5080", "used_mb": 4096, "total_mb": 16303,
                                          "driver": "580.95"}]),
                         "GPU: NVIDIA GeForce RTX 5080 · 4.0 / 15.9 GB in use")


if __name__ == "__main__":
    unittest.main()
