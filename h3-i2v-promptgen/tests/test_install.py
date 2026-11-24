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


class AutoSize(unittest.TestCase):
    FILES = ["Inkling-Q4_K_M.gguf", "Inkling-Q3_K_M.gguf", "Inkling-IQ3_XXS.gguf", "Inkling-IQ2_M.gguf",
             "Q8_0/Inkling-Q8_0-00001-of-00002.gguf", "Q8_0/Inkling-Q8_0-00002-of-00002.gguf",
             "mmproj-Inkling-BF16.gguf", "README.md"]
    SIZES = {"Inkling-Q4_K_M.gguf": 16.0e9, "Inkling-Q3_K_M.gguf": 12.9e9, "Inkling-IQ3_XXS.gguf": 10.1e9,
             "Inkling-IQ2_M.gguf": 8.7e9, "Q8_0/Inkling-Q8_0-00001-of-00002.gguf": 14e9,
             "Q8_0/Inkling-Q8_0-00002-of-00002.gguf": 13.8e9, "mmproj-Inkling-BF16.gguf": 0.9e9, "README.md": 10}

    def test_limits(self):
        self.assertEqual(inst.auto_size_limit_gb(16), 11.0)
        self.assertEqual(inst.auto_size_limit_gb(32), inst.Q4_K_M_GB)
        self.assertEqual(inst.auto_size_limit_gb(8), 6.0)

    def test_16gb_ram_gets_iq3(self):
        parts, total = inst.choose_by_size(self.FILES, self.SIZES, int(inst.auto_size_limit_gb(16) * 1e9))
        self.assertEqual(parts, ["Inkling-IQ3_XXS.gguf"])

    def test_32gb_ram_gets_q4(self):
        parts, _ = inst.choose_by_size(self.FILES, self.SIZES, int(inst.auto_size_limit_gb(32) * 1e9))
        self.assertEqual(parts, ["Inkling-Q4_K_M.gguf"])

    def test_split_files_counted_together(self):
        parts, total = inst.choose_by_size(self.FILES, self.SIZES, int(30e9))
        self.assertEqual(len(parts), 2)
        self.assertEqual(total, 27.8e9)

    def test_nothing_small_enough(self):
        self.assertEqual(inst.choose_by_size(self.FILES, self.SIZES, int(5e9)), ([], 0))

    def test_mmproj(self):
        self.assertEqual(inst.choose_mmproj(["a-mmproj-F16.gguf", "mmproj-BF16.gguf", "x.gguf"]), "mmproj-BF16.gguf")
        self.assertEqual(inst.choose_mmproj(["x.gguf"]), "")


def _asset(name):
    return {"name": name, "size": 1, "browser_download_url": "https://example.invalid/" + name}


class PickReleases(unittest.TestCase):
    LLAMA = [
        {"tag_name": "b12657", "assets": [_asset("llama-b12657-bin-win-cpu-x64.zip")]},  # Linux files not built yet
        {"tag_name": "b12655", "assets": [_asset("llama-b12655-bin-ubuntu-cuda-12.8-x64.tar.gz"),
                                          _asset("cudart-llama-b12655-bin-ubuntu-cuda-12.8-x64.tar.gz"),
                                          _asset("llama-b12655-bin-ubuntu-cuda-13.5-x64.tar.gz")]},
        {"tag_name": "b12654", "assets": [_asset("llama-b12654-bin-ubuntu-cuda-12.8-x64.tar.gz")]},  # no runtime
        {"tag_name": "v1.0.0", "assets": []},
        {"tag_name": "b12638", "assets": [_asset("llama-b12638-bin-ubuntu-cuda-12.8-x64.tar.gz"),
                                          _asset("cudart-llama-b12638-bin-ubuntu-cuda-12.8-x64.tar.gz")]},
    ]

    def test_llama_newest_complete_build(self):
        name, main, runtime = inst.pick_llama_release(self.LLAMA)
        self.assertEqual(name, "b12655")
        self.assertEqual(main["name"], "llama-b12655-bin-ubuntu-cuda-12.8-x64.tar.gz")
        self.assertEqual(runtime["name"], "cudart-llama-b12655-bin-ubuntu-cuda-12.8-x64.tar.gz")

    def test_llama_never_older_than_the_inkling_fixes(self):
        old = [r for r in self.LLAMA if r["tag_name"] in ("b12638", "v1.0.0")]
        self.assertEqual(inst.pick_llama_release(old), ("", None, None))
        self.assertGreaterEqual(inst.MIN_LLAMA_BUILD, 12653)

    def test_textgen_skips_release_without_linux_package(self):
        rels = [{"tag_name": "v5.0", "assets": [_asset("textgen-portable-5.0-windows-cuda13.1.zip")]},
                {"tag_name": "v4.9", "assets": [_asset("textgen-portable-4.9-linux-cuda12.4.tar.gz"),
                                                _asset("textgen-portable-4.9-linux-cuda13.1.zip")]}]
        rel, asset = inst.pick_textgen_release(rels, "13.1")
        self.assertEqual((rel["tag_name"], asset["name"]), ("v4.9", "textgen-portable-4.9-linux-cuda13.1.zip"))
        rel, asset = inst.pick_textgen_release(rels, "12.4")
        self.assertEqual(asset["name"], "textgen-portable-4.9-linux-cuda12.4.tar.gz")
        self.assertEqual(inst.pick_textgen_release(rels[:1], "13.1"), (None, None))


class Zip(unittest.TestCase):
    def test_keeps_exec_bit_and_symlinks_and_refuses_escape(self):
        import stat
        import zipfile
        d = Path(tempfile.mkdtemp())
        archive = d / "t.zip"
        with zipfile.ZipFile(archive, "w") as z:
            info = zipfile.ZipInfo("textgen-4.9/textgen")
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            z.writestr(info, "#!/bin/sh\necho hi\n")
            link = zipfile.ZipInfo("textgen-4.9/run")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(link, "textgen")
            z.writestr("textgen-4.9/user_data/a.txt", "a")
        out = d / "out"
        out.mkdir()
        inst.extract_zip(archive, out)
        self.assertTrue((out / "textgen-4.9/textgen").stat().st_mode & stat.S_IXUSR)
        self.assertTrue((out / "textgen-4.9/run").is_symlink())
        self.assertEqual((out / "textgen-4.9/user_data/a.txt").read_text(), "a")
        bad = d / "bad.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("../escape.txt", "x")
        with self.assertRaises(inst.InstallError):
            inst.extract_zip(bad, out)
        self.assertFalse((d / "escape.txt").exists())


class Download(unittest.TestCase):
    """A connection that drops mid-file must resume (Range request), not crash the installer."""

    def test_resumes_after_cut_off_reads(self):
        import http.server
        import threading

        data = bytes(range(256)) * 4096  # 1 MiB
        state = {"calls": 0, "ranges": []}

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                state["calls"] += 1
                rng = self.headers.get("Range")
                state["ranges"].append(rng)
                start = int(rng.split("=")[1].split("-")[0]) if rng else 0
                body = data[start:]
                self.send_response(206 if rng else 200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if state["calls"] < 3:   # the first two answers stop early: http.client.IncompleteRead
                    self.wfile.write(body[: len(body) // 3])
                    self.wfile.flush()
                    self.close_connection = True
                    self.connection.shutdown(2)
                    return
                self.wfile.write(body)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        old_sleep = inst.time.sleep
        inst.time.sleep = lambda s: None
        try:
            dest = Path(tempfile.mkdtemp()) / "file.bin"
            inst.download(f"http://127.0.0.1:{srv.server_address[1]}/f", dest, len(data))
        finally:
            inst.time.sleep = old_sleep
            srv.shutdown()
        self.assertEqual(dest.read_bytes(), data)
        self.assertEqual(state["calls"], 3)
        self.assertIsNone(state["ranges"][0])
        self.assertTrue(all(r and r.startswith("bytes=") for r in state["ranges"][1:]))

    def test_missing_file_is_a_clear_error(self):
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(404)
                self.end_headers()

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(inst.InstallError):
                inst.download(f"http://127.0.0.1:{srv.server_address[1]}/x", Path(tempfile.mkdtemp()) / "x", 10)
        finally:
            srv.shutdown()


class DesktopEntry(unittest.TestCase):
    def test_plain_path_unquoted(self):
        self.assertEqual(inst.desktop_quote("/home/u/AI/textgen/start-h3-director.sh"),
                         "/home/u/AI/textgen/start-h3-director.sh")

    def test_spaces_and_specials_follow_the_spec(self):
        self.assertEqual(inst.desktop_quote("/home/my user/s.sh"), '"/home/my user/s.sh"')
        # quote rule: \" \$ ; string rule doubles the backslash; % becomes %%
        self.assertEqual(inst.desktop_quote('/a"b/$x/100%/s.sh'), '"/a\\\\"b/\\\\$x/100%%/s.sh"')


class Settings(unittest.TestCase):
    def _ud(self):
        ud = Path(tempfile.mkdtemp())
        (ud / "extensions" / "h3_i2v_director").mkdir(parents=True)
        return ud

    def test_first_install_defaults(self):
        s = inst.write_settings(self._ud(), Path("/x/llama-b12675/llama-server"), "M.gguf", "P.gguf", None, None)
        self.assertEqual((s["gpu_profile"], s["vram_budget_gb"], s["autoload"], s["ctx_size"]), ("fit", 6.5, True, 12288))
        self.assertEqual((s["model_file"], s["mmproj_file"]), ("M.gguf", "P.gguf"))

    def test_rerun_keeps_choices_made_in_the_tab(self):
        import json
        ud = self._ud()
        inst.write_settings(ud, Path("/x/old/llama-server"), "M.gguf", "P.gguf", None, None)
        f = ud / "extensions" / "h3_i2v_director" / "settings.json"
        f.write_text(json.dumps(dict(json.loads(f.read_text()), vram_budget_gb=5.0, autoload=False, gpu_profile="full")))
        s = inst.write_settings(ud, Path("/x/new/llama-server"), "M.gguf", "", None, None)
        self.assertEqual((s["gpu_profile"], s["vram_budget_gb"], s["autoload"]), ("full", 5.0, False))
        self.assertEqual(s["llama_server_path"], "/x/new/llama-server")   # the new llama.cpp is always used
        self.assertEqual(s["mmproj_file"], "P.gguf")                       # not cleared when skipped

    def test_options_given_on_purpose_win(self):
        ud = self._ud()
        inst.write_settings(ud, Path("/x/llama-server"), "M.gguf", "P.gguf", "full", None)
        s = inst.write_settings(ud, Path("/x/llama-server"), "M.gguf", "P.gguf", "fit", 7.0)
        self.assertEqual((s["gpu_profile"], s["vram_budget_gb"]), ("fit", 7.0))


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
