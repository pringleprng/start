"""Tests for the Bazzite installer's pure parts."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "bazzite" / "install.py"
_spec = importlib.util.spec_from_file_location("h3_install", _path)
inst = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = inst
_spec.loader.exec_module(inst)


class ChooseFiles(unittest.TestCase):
    FILES = [
        "README.md",
        "Inkling-2-Mini-Uncensored-Q4_K_M.gguf",
        "Inkling-2-Mini-Uncensored-Q8_0.gguf",
        "UD-Inkling-2-Mini-Uncensored-Q4_K_M.gguf",
        "mmproj-Inkling-2-Mini-Uncensored-F16.gguf",
        "mmproj-Inkling-2-Mini-Uncensored-BF16.gguf",
    ]

    def test_plain_quant_and_bf16_projector(self):
        self.assertEqual(inst.choose_model_files(self.FILES, "Q4_K_M"),
                         (["Inkling-2-Mini-Uncensored-Q4_K_M.gguf"], "mmproj-Inkling-2-Mini-Uncensored-BF16.gguf"))

    def test_split_files(self):
        files = ["Q8_0/Inkling-Q8_0-00002-of-00002.gguf", "Q8_0/Inkling-Q8_0-00001-of-00002.gguf", "mmproj-F16.gguf"]
        self.assertEqual(inst.choose_model_files(files, "Q8_0"),
                         (["Q8_0/Inkling-Q8_0-00001-of-00002.gguf", "Q8_0/Inkling-Q8_0-00002-of-00002.gguf"],
                          "mmproj-F16.gguf"))

    def test_missing_quant(self):
        self.assertEqual(inst.choose_model_files(self.FILES, "IQ2_M"), ([], ""))


class CmdFlags(unittest.TestCase):
    def _run(self, text):
        d = Path(tempfile.mkdtemp())
        (d / "CMD_FLAGS.txt").write_text(text)
        inst.update_cmd_flags(d)
        return [ln for ln in (d / "CMD_FLAGS.txt").read_text().splitlines() if ln and not ln.startswith("#")]

    def test_adds_extension(self):
        self.assertEqual(self._run("# comment\n"), ["--extensions h3_i2v_director"])

    def test_extends_existing_list_and_drops_model(self):
        out = self._run("--listen --extensions gallery --api\n--model Foo.gguf --ctx-size 8192\n")
        self.assertEqual(out, ["--listen --extensions gallery h3_i2v_director --api", "--ctx-size 8192"])

    def test_idempotent(self):
        once = self._run("--extensions h3_i2v_director\n")
        self.assertEqual(once, ["--extensions h3_i2v_director"])


if __name__ == "__main__":
    unittest.main()
