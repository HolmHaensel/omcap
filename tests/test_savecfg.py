"""Save location and file naming, offline."""
import json
import os
import tempfile
import unittest

import omcap.server as server


class SaveCfg(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = (dict(server.save_cfg), server.CAPTURES, server.SETTINGS_FILE, server.cam)
        server.CAPTURES = os.path.join(self.tmp, "captures")
        server.SETTINGS_FILE = os.path.join(self.tmp, "omcap-settings.json")
        server.save_cfg.update(dir="", scheme="original", prefix="")

        class Cam:
            def fetch_file(self, path, dest):
                with open(dest, "wb") as f:
                    f.write(b"x")
        server.cam = Cam()

    def tearDown(self):
        server.save_cfg.clear()
        server.save_cfg.update(self.old[0])
        server.CAPTURES, server.SETTINGS_FILE, server.cam = self.old[1:]

    def test_default_folder(self):
        self.assertEqual(server.captures_dir(), server.CAPTURES)
        self.assertTrue(server.save_capture("/DCIM/100OLYMP/PB092179.JPG").startswith(server.CAPTURES))

    def test_relative_path_rejected(self):
        with self.assertRaises(ValueError):
            server.validate_save_dir("pictures/here")

    def test_protected_folders_rejected(self):
        for d in server.PROTECTED_DIRS:
            with self.assertRaises(ValueError):
                server.validate_save_dir(os.path.join(d, "sub"))

    def test_created_and_stored(self):
        d = os.path.join(self.tmp, "new", "shots")
        c = server.set_save_cfg({"dir": d, "scheme": "original"})
        self.assertTrue(os.path.isdir(d))
        self.assertEqual(c["effective_dir"], d)
        with open(server.SETTINGS_FILE) as f:
            self.assertEqual(json.load(f)["dir"], d)
        server.save_cfg.update(dir="", scheme="original")
        server.load_save_cfg()
        self.assertEqual(server.save_cfg["dir"], d)
        p = server.save_capture("/DCIM/PB092179.JPG")
        self.assertEqual(os.path.dirname(p), d)
        self.assertEqual([e["name"] for e in server.local_files()], ["PB092179.JPG"])
        self.assertEqual(server.capture_path("PB092179.JPG"), p)

    def test_not_writable_rejected(self):
        d = os.path.join(self.tmp, "ro")
        os.makedirs(d)
        os.chmod(d, 0o500)
        try:
            if os.access(d, os.W_OK):
                self.skipTest("running as a user that ignores permissions")
            with self.assertRaises(ValueError):
                server.validate_save_dir(d)
        finally:
            os.chmod(d, 0o700)

    def test_bad_scheme_and_prefix(self):
        with self.assertRaises(ValueError):
            server.set_save_cfg({"dir": "", "scheme": "weird"})
        with self.assertRaises(ValueError):
            server.set_save_cfg({"dir": "", "scheme": "prefix", "prefix": ""})
        with self.assertRaises(ValueError):
            server.set_save_cfg({"dir": "", "scheme": "prefix", "prefix": "../x"})

    def test_naming(self):
        import time
        t = time.strptime("2026-11-09 09:14:12", "%Y-%m-%d %H:%M:%S")
        self.assertEqual(server.target_name("PB092179.JPG", t), "PB092179.JPG")
        server.save_cfg["scheme"] = "datetime"
        self.assertEqual(server.target_name("PB092179.JPG", t), "20261109_091412_PB092179.JPG")
        server.save_cfg.update(scheme="prefix", prefix="trip_")
        self.assertEqual(server.target_name("PB092179.JPG", t), "trip_PB092179.JPG")

    def test_never_overwrite(self):
        server.save_cfg.update(scheme="prefix", prefix="a_")
        a = server.save_capture("/X/P1.JPG")
        b = server.save_capture("/X/P1.JPG")
        self.assertEqual(os.path.basename(a), "a_P1.JPG")
        self.assertEqual(os.path.basename(b), "a_P1-1.JPG")


if __name__ == "__main__":
    unittest.main()


class SaveCfgHardening(SaveCfg):
    """Stored config validation, case-insensitive protection, same-file check (offline)."""

    def _write_cfg(self, **c):
        with open(server.SETTINGS_FILE, "w") as f:
            json.dump(c, f)

    def test_load_rejects_bad_prefix(self):
        for bad in ("../x", "a/b", "..", "a\\b"):
            self._write_cfg(dir="", scheme="prefix", prefix=bad)
            server.save_cfg.update(dir="", scheme="original", prefix="")
            server.load_save_cfg()
            self.assertEqual(server.save_cfg["scheme"], "original")

    def test_load_rejects_protected_dir(self):
        d = os.path.join(server.PROTECTED_DIRS[0], "x")
        self._write_cfg(dir=d, scheme="original", prefix="")
        server.load_save_cfg()
        self.assertEqual(server.save_cfg["dir"], "")

    def test_protected_case_insensitive_and_out(self):
        d = server.PROTECTED_DIRS[0]
        up = os.path.join(os.path.dirname(d), os.path.basename(d).upper(), "sub")
        with self.assertRaises(ValueError):
            server.validate_save_dir(up)
        out = [p for p in server.PROTECTED_DIRS if os.path.basename(p) == "out"][0]
        with self.assertRaises(ValueError):
            server.validate_save_dir(os.path.join(out, "other"))
        self.assertTrue(server._inside(os.path.join(out, "hsl"), server.PROTECTED_EXCEPT[0]))

    def test_same_file_skipped_for_prefix_not_datetime(self):
        server.save_cfg.update(scheme="prefix", prefix="p_")
        a = server.save_capture("/DCIM/A.JPG", 1)
        self.assertEqual(server.save_capture("/DCIM/A.JPG", 1), a)
        server.save_cfg.update(scheme="datetime")
        b = server.save_capture("/DCIM/A.JPG", 1)
        self.assertNotEqual(server.save_capture("/DCIM/A.JPG", 1), b)
