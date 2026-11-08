"""Tests ohne Kamera: Antworten der Kamera werden simuliert."""
import os
import struct
import tempfile
import time
import unittest

import omcap.server as server
from omcap import exif
from omcap.camera import Camera, CameraError

AF_REPLY = (b'<?xml version="1.0"?><response><affocus>ok</affocus>'
            b'<afframepoint>0259x0179</afframepoint><afframesize>0115x0115</afframesize></response>')


class CameraParsing(unittest.TestCase):
    def setUp(self):
        self.cam = Camera(allow_write=True)
        self.cam.lvqty = "0800x0600"
        self.props = []
        self.cam.prop = lambda name: (self.props.append(name), "0135-0100_0527x0397")[1]

    def test_af_focus_reads_frame_centre(self):
        self.cam.write = lambda cgi, data=None, **q: AF_REPLY if q.get("com") == "assignafframe" else b""
        self.assertEqual(self.cam.af_focus(0.5, 0.5), {"ok": True, "x": 316.5, "y": 236.5})

    def test_af_focus_broken_reply(self):
        self.cam.write = lambda *a, **q: b"not xml"
        self.assertEqual(self.cam.af_focus(0.5, 0.5), {"ok": False, "x": None, "y": None})

    def test_touch_frame_cached_per_lvqty(self):
        self.cam.touch_frame()
        self.cam.touch_frame()
        self.assertEqual(len(self.props), 1)
        self.cam.lvqty = "1024x0768"
        self.cam.touch_frame()
        self.assertEqual(len(self.props), 2)

    def test_listdir_retries_on_520(self):
        import omcap.camera as camera
        calls = []

        def get(cgi, **q):
            calls.append(cgi)
            if len(calls) < 3:
                raise CameraError("busy", 520)
            return b"VER_100\n/DCIM,100OLYMP,0,16,1,1\n"
        self.cam.get = get
        old, camera.LIST_RETRY_WAIT = camera.LIST_RETRY_WAIT, 0
        try:
            items = self.cam.listdir("/DCIM")
        finally:
            camera.LIST_RETRY_WAIT = old
        self.assertEqual(len(calls), 3)
        self.assertTrue(items[0]["isdir"])

    def test_paths_outside_dcim_refused(self):
        with self.assertRaises(CameraError):
            self.cam.thumbnail("/etc/passwd")


def make_exif_jpeg(lens_model):
    """Kleinstes JPG mit EXIF-IFD und LensModel (0xA434)."""
    model = lens_model.encode() + b"\0"
    tiff = bytearray(b"II*\0" + struct.pack("<I", 8))
    # IFD0: ein Eintrag, Zeiger auf das Exif-IFD
    tiff += struct.pack("<H", 1) + struct.pack("<HHII", 0x8769, 4, 1, 26) + struct.pack("<I", 0)
    # Exif-IFD bei Offset 26: LensModel als ASCII, Daten bei Offset 44
    tiff += struct.pack("<H", 1) + struct.pack("<HHII", 0xA434, 2, len(model), 44) + struct.pack("<I", 0)
    tiff += model
    app1 = b"Exif\0\0" + bytes(tiff)
    return b"\xff\xd8\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9"


class ExifLens(unittest.TestCase):
    def test_lens_model(self):
        info = exif.lens_info(make_exif_jpeg("TEST LENS 12-40"))
        self.assertEqual(info["model"], "TEST LENS 12-40")

    def test_garbage(self):
        self.assertIsNone(exif.lens_info(b"no jpeg"))


class PreviewCache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.old = server.PREVIEW_CACHE, server.PREVIEW_CACHE_MAX
        server.PREVIEW_CACHE = self.dir

    def tearDown(self):
        server.PREVIEW_CACHE, server.PREVIEW_CACHE_MAX = self.old

    def test_fetched_once_with_size(self):
        calls = []
        fetch = lambda: (calls.append(1), b"\xff\xd8data")[1]
        for _ in range(3):
            server.cached_preview("thumb", "/DCIM/100OLYMP/P1.JPG", "123", fetch)
        self.assertEqual(len(calls), 1)

    def test_not_cached_without_size(self):
        calls = []
        fetch = lambda: (calls.append(1), b"\xff\xd8data")[1]
        for _ in range(2):
            server.cached_preview("thumb", "/DCIM/100OLYMP/P1.JPG", None, fetch)
        self.assertEqual(len(calls), 2)

    def test_prune_keeps_newest(self):
        server.PREVIEW_CACHE_MAX = 1000
        for i in range(6):
            server.cached_preview("r1024", "/DCIM/A/P%d.JPG" % i, str(i + 1), lambda: b"\xff\xd8" + b"x" * 298)
            time.sleep(0.01)
        self.assertLessEqual(sum(os.path.getsize(os.path.join(self.dir, f)) for f in os.listdir(self.dir)), 800)
        self.assertTrue(any("P5" in f for f in os.listdir(self.dir)))


class Helpers(unittest.TestCase):
    def test_jpg_last(self):
        self.assertEqual(server.jpg_last(["a.JPG", "a.ORF"]), ["a.ORF", "a.JPG"])

    def test_preview_path_prefers_jpg(self):
        d = tempfile.mkdtemp()
        for n in ("P1.ORF", "P1.JPG", "P2.ORF"):
            open(os.path.join(d, n), "wb").close()
        self.assertTrue(server.preview_path(os.path.join(d, "P1.ORF")).endswith("P1.JPG"))
        self.assertTrue(server.preview_path(os.path.join(d, "P2.ORF")).endswith("P2.ORF"))

    def test_bracket_plan(self):
        enum = ["-1.0", "-0.7", "-0.3", "0.0", "+0.3", "+0.7", "+1.0"]
        self.assertEqual(server.bracket_plan(enum, "0.0", 3, 3), ["-1.0", "0.0", "+1.0"])


if __name__ == "__main__":
    unittest.main()
