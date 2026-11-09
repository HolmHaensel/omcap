"""Tests without a camera: card space and battery from simulated answers."""
import unittest
from types import SimpleNamespace

import omcap.server as server
from omcap import usb_camera
from omcap.camera import Camera, CameraError, parse_capacity


class Capacity(unittest.TestCase):
    def test_variants(self):
        cases = [
            (b'<?xml version="1.0"?><response><unusedcapacity>1234567</unusedcapacity></response>', 1234567),
            (b'<?xml version="1.0"?>\n<unused>4294967295</unused>', 4294967295),
            (b'<unusedcapacity>42</unusedcapacity>', 42),
            (b'<?xml version="1.0"?><response><capacity> 99 </capacity></response>', 99),
            (b"123456789\r\n", 123456789),
            ("500", 500),
            (b"0", 0),
        ]
        for raw, want in cases:
            self.assertEqual(parse_capacity(raw), want, raw)

    def test_unparsable(self):
        for raw in (b"", None, b"abc", b"<response/>", b"<a><b>x</b></a>", b"<a><b>", b"-5", b"1.5"):
            self.assertIsNone(parse_capacity(raw), raw)

    def test_wifi_free_bytes_uses_read_cgi(self):
        cam = Camera()
        calls = []
        cam.get = lambda cgi, **q: (calls.append(cgi), b"<r><unusedcapacity>7</unusedcapacity></r>")[1]
        self.assertEqual(cam.free_bytes(), 7)
        self.assertEqual(calls, ["get_unusedcapacity"])
        self.assertIsNone(cam.battery())


class Usb(unittest.TestCase):
    def test_battery(self):
        for raw, want in (("80%", 80), ("100", 100), (55, 55), (" 7 % ", 7), ("0%", 0)):
            self.assertEqual(usb_camera.parse_battery(raw), want)
        for raw in ("Low", "", None, "150%", "-3"):
            self.assertIsNone(usb_camera.parse_battery(raw))

    def test_free_kbytes(self):
        infos = [SimpleNamespace(freekbytes=1000), SimpleNamespace(freekbytes=24),
                 SimpleNamespace(label="x")]
        self.assertEqual(usb_camera.free_kbytes(infos), 1024)
        self.assertIsNone(usb_camera.free_kbytes([SimpleNamespace()]))
        self.assertIsNone(usb_camera.free_kbytes([]))


class DeviceCache(unittest.TestCase):
    def setUp(self):
        self.old = server.cam
        self.n = 0
        outer = self

        class Fake:
            stage = 0

            def free_bytes(self):
                outer.n += 1
                return 1000

            def battery(self):
                raise CameraError("no")
        server.cam = Fake()
        server.invalidate_device()

    def tearDown(self):
        server.cam = self.old
        server.invalidate_device()

    def test_cached_and_forced(self):
        self.assertEqual(server.device_status(), {"card": 1000, "battery": None})
        server.device_status()
        self.assertEqual(self.n, 1)
        server.device_status(force=True)
        self.assertEqual(self.n, 2)


if __name__ == "__main__":
    unittest.main()


class LiveViewSize(unittest.TestCase):
    def test_d06d_decoding(self):
        from omcap.usb_camera import lv_size_from_d06d
        self.assertEqual(lv_size_from_d06d(67109632), (1024, 768))
        self.assertEqual(lv_size_from_d06d("83887040"), (1280, 960))
        self.assertEqual(lv_size_from_d06d(0, {"x1": 847, "y1": 636}), (1024, 768))
        self.assertEqual(lv_size_from_d06d(0, {"x1": 1060, "y1": 796}), (1280, 960))


class UsbLens(unittest.TestCase):
    def test_falls_back_to_focal_range(self):
        class Fake:
            last_jpg = None
            def lens_focal(self): return 14, 140, 19
        old = (server.cam, server.conn_type)
        server.cam, server.conn_type = Fake(), "usb"
        try:
            self.assertEqual(server.usb_lens(), {"focal_min": 14, "focal_max": 140, "focal": 19})
        finally:
            server.cam, server.conn_type = old


class UsbIndex(unittest.TestCase):
    def test_busy_while_indexing(self):
        old = server.state["indexing"]
        server.state["indexing"] = True
        try:
            with self.assertRaises(server.CameraError):
                server.ensure_idle()
        finally:
            server.state["indexing"] = old


class AfRaster(unittest.TestCase):
    def test_both_rasters_seen_on_the_camera(self):
        from omcap.usb_camera import af_raster
        self.assertEqual(af_raster({"x0": 216, "x1": 1060, "y0": 160, "y1": 796}), (1280, 960))
        self.assertEqual(af_raster({"x0": 172, "x1": 847, "y0": 128, "y1": 636}), (1024, 768))
