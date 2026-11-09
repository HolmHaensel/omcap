"""Tests without a camera: the camera answers are simulated."""
import os
import struct
import tempfile
import time
import unittest

import omcap.server as server
from omcap import exif
from omcap.camera import Camera, CameraError, WriteBlocked, parse_playtime, parse_rsvimglist

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
    """Smallest JPG with an Exif IFD and LensModel (0xA434)."""
    model = lens_model.encode() + b"\0"
    tiff = bytearray(b"II*\0" + struct.pack("<I", 8))
    # IFD0: one entry, pointer to the Exif IFD
    tiff += struct.pack("<H", 1) + struct.pack("<HHII", 0x8769, 4, 1, 26) + struct.pack("<I", 0)
    # Exif IFD at offset 26: LensModel as ASCII, data at offset 44
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

    def test_newest_jpg_and_last_shot(self):
        self.assertEqual(server.newest_jpg(["/D/P1.ORF", "/D/P1.JPG"]), "/D/P1.JPG")
        self.assertIsNone(server.newest_jpg(["/D/P1.ORF"]))
        server.state["last_shot"] = None
        server.remember_shot(["/D/P2.ORF"])
        self.assertIsNone(server.state["last_shot"])
        server.remember_shot(["/D/P2.ORF", "/D/P2.JPG"])
        self.assertEqual(server.state["last_shot"], "/D/P2.JPG")
        server.state["last_shot"] = None

    def test_preview_path_prefers_jpg(self):
        d = tempfile.mkdtemp()
        for n in ("P1.ORF", "P1.JPG", "P2.ORF"):
            open(os.path.join(d, n), "wb").close()
        self.assertTrue(server.preview_path(os.path.join(d, "P1.ORF")).endswith("P1.JPG"))
        self.assertTrue(server.preview_path(os.path.join(d, "P2.ORF")).endswith("P2.ORF"))

    def test_bracket_plan(self):
        enum = ["-1.0", "-0.7", "-0.3", "0.0", "+0.3", "+0.7", "+1.0"]
        self.assertEqual(server.bracket_plan(enum, "0.0", 3, 3), ["-1.0", "0.0", "+1.0"])


class PowerOff(unittest.TestCase):
    def test_blocked_without_allow_write(self):
        with self.assertRaises(WriteBlocked):
            Camera(allow_write=False).power_off()

    def test_calls_exec_pwoff(self):
        c = Camera(allow_write=True)
        calls = []
        c.write = lambda cgi, data=None, **q: calls.append(cgi) or b""
        c.power_off()
        self.assertEqual(calls, ["exec_pwoff"])

    def test_handler_tolerates_dropped_connection(self):
        class Live:
            running = True
            def stop(self): pass
        class Fake:
            stage = 0
            allow_write = True
            def supports(self, name): return name == "exec_pwoff"
            def stop_liveview(self): pass
            def power_off(self): raise CameraError("connection reset")
        old = (server.cam, server.live, server.conn_type)
        server.cam, server.live, server.conn_type = Fake(), Live(), "wifi"
        try:
            server.power_off()
            self.assertIsNone(server.cam)
            self.assertIsNone(server.conn_type)
        finally:
            server.cam, server.live, server.conn_type = old



class PowerOffGuards(unittest.TestCase):
    def test_missing_command_is_not_swallowed(self):
        class Live:
            running = False
            def stop(self): pass
        class Fake:
            stage = 0
            allow_write = True
            def supports(self, name): return False
        old = (server.cam, server.live, server.conn_type)
        server.cam, server.live, server.conn_type = Fake(), Live(), "wifi"
        try:
            with self.assertRaises(CameraError):
                server.power_off()
            self.assertEqual(server.conn_type, "wifi")  # not disconnected
        finally:
            server.cam, server.live, server.conn_type = old

class WebcamView(unittest.TestCase):
    """The client routes ?view=webcam to the bare live stream (no UI, optional w/h)."""
    def test_index_has_webcam_view(self):
        with open(os.path.join(server.ROOT, "web", "index.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertIn("view==='webcam'", html)
        self.assertIn("params.get('w')", html)
        self.assertIn("/live.mjpg", html)


if __name__ == "__main__":
    unittest.main()


class ShareOrderAndMovieLength(unittest.TestCase):
    def test_rsvimglist_full_lines(self):
        t = "VER_100\r\n/DCIM/100OLYMP,P1010001.JPG,1234,32,19000,20000\r\n\r\n"
        self.assertEqual(parse_rsvimglist(t), [{"dir": "/DCIM/100OLYMP", "name": "P1010001.JPG",
                                               "size": 1234, "path": "/DCIM/100OLYMP/P1010001.JPG"}])

    def test_rsvimglist_defensive(self):
        t = "/DCIM/100OLYMP/P1010002.JPG\n<xml/>\n/DCIM/100OLYMP\nfoo,bar"
        self.assertEqual([e["path"] for e in parse_rsvimglist(t)], ["/DCIM/100OLYMP/P1010002.JPG"])
        self.assertEqual(parse_rsvimglist(""), [])

    def test_playtime_formats(self):
        self.assertEqual(parse_playtime("<?xml version=\"1.0\"?><r><playtime>75</playtime></r>"), 75)
        self.assertEqual(parse_playtime("<r><movplaytime>00:01:15</movplaytime></r>"), 75)
        self.assertEqual(parse_playtime("2:05"), 125)
        self.assertIsNone(parse_playtime("<r></r>"))

    def test_playtime_error_code(self):
        with self.assertRaises(CameraError):
            parse_playtime("<response><errorcode>1001</errorcode></response>")

    def test_clear_resvflg_needs_allow_write(self):
        c = Camera(allow_write=False)
        c._commands = {"clear_resvflg"}
        with self.assertRaises(WriteBlocked):
            c.reset_share_order()

    def test_clear_resvflg_with_write(self):
        c = Camera(allow_write=True)
        c._commands = {"clear_resvflg"}
        calls = []
        c._open = lambda cgi, query=None, data=None, timeout=None: (_ for _ in ()).throw(
            CameraError(cgi))
        with self.assertRaises(CameraError) as e:
            c.reset_share_order()
        self.assertIn("clear_resvflg.cgi", str(e.exception))

    def test_movie_length_only_in_playback(self):
        old = (server.cam, server.conn_type, server.state["play"])
        try:
            server.cam, server.conn_type, server.state["play"] = Camera(), "wifi", None
            with self.assertRaises(CameraError):
                server.movie_length("/DCIM/100OLYMP/P1010003.MOV", "5")
        finally:
            server.cam, server.conn_type, server.state["play"] = old

    def test_movie_length_cached(self):
        old = (server.cam, server.conn_type, server.state["play"])
        n = []
        try:
            c = Camera()
            c.get = lambda cgi, **q: (n.append(cgi), b"<r><playtime>9</playtime></r>")[1]
            server.cam, server.conn_type, server.state["play"] = c, "wifi", {"resume": False}
            server.movtime_cache.clear()
            self.assertEqual(server.movie_length("/DCIM/100OLYMP/P1010003.MOV", "5"), 9)
            self.assertEqual(server.movie_length("/DCIM/100OLYMP/P1010003.MOV", "5"), 9)
            self.assertEqual(len(n), 1)
        finally:
            server.cam, server.conn_type, server.state["play"] = old
            server.movtime_cache.clear()

    def test_feature_flag(self):
        self.assertIn("share_order", server.WIFI_FEATURES)
        self.assertNotIn("share_order", server.usb_camera.FEATURES)
