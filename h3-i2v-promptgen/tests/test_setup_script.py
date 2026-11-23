"""The one-file setup script must match its sources (rebuild with tools/build_setup_script.py)."""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder = _load("h3_build_setup", ROOT / "tools" / "build_setup_script.py")


class SetupScript(unittest.TestCase):
    def test_up_to_date(self):
        current = (ROOT / "h3-director-setup.sh").read_text(encoding="utf-8")
        self.assertEqual(current, builder.build(),
                         "h3-director-setup.sh is out of date: run python h3-i2v-promptgen/tools/build_setup_script.py")

    def test_embedded_files_match_sources(self):
        installer = _load("h3_install_embedded", ROOT / "bazzite" / "install.py")
        installer.EMBEDDED_FILES = builder.payload()
        files = installer._embedded_files()
        self.assertEqual(sorted(files), sorted(installer.H3_FILES))
        for rel, data in files.items():
            self.assertEqual(data, (ROOT / rel).read_bytes(), rel)


if __name__ == "__main__":
    unittest.main()
