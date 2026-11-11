"""Picture info (playback Overall display): EXIF parser and /api/exif with a fake camera, no user photos."""
import json
import socket
import struct
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from omcap import exif, server
from omcap.camera import CameraError


def build_ifd(entries, base_off):
    """entries: [(tag, type, count, payload bytes or int)]; returns the IFD bytes placed at base_off.

    Values up to 4 bytes go inline, larger ones behind the IFD (offsets are relative to the TIFF start).
    """
    n = len(entries)
    ifd = bytearray(struct.pack("<H", n))
    data = bytearray()
    data_off = base_off + 2 + 12 * n + 4
    for tag, typ, cnt, val in entries:
        if isinstance(val, int):
            ifd += struct.pack("<HHII", tag, typ, cnt, val)
        elif len(val) <= 4:
            ifd += struct.pack("<HHI", tag, typ, cnt) + val.ljust(4, b"\0")
        else:
            ifd += struct.pack("<HHII", tag, typ, cnt, data_off + len(data))
            data += val
    ifd += struct.pack("<I", 0)
    return bytes(ifd) + bytes(data)


def synthetic_jpeg(with_note=True, fields=True):
    """Little-endian EXIF with the common tags and an Olympus MakerNote holding the Picture Mode."""
    rat = lambda n, d: struct.pack("<II", n, d)
    srat = lambda n, d: struct.pack("<ii", n, d)
    short = lambda v: struct.pack("<H", v)
    lens = b"M.ZUIKO 12-40mm F2.8\0"
    # MakerNote (offsets from its own start): header 12 bytes, IFD with 0x2020 -> CameraSettings IFD
    mn_ifd_off = 12
    cs = build_ifd([(0x0520, 3, 2, struct.pack("<HH", 2, 0))], 0)  # Natural
    mn_top_len = 2 + 12 + 4
    cs_off = mn_ifd_off + mn_top_len
    top = build_ifd([(0x2020, 13, 1, cs_off)], mn_ifd_off)
    note = b"OLYMPUS\0II\x03\0" + top
    note += cs  # CameraSettings IFD right behind the top IFD
    assert len(top) == mn_top_len
    exif_entries = []
    if fields:
        exif_entries += [
            (0x829A, 5, 1, rat(1, 250)), (0x829D, 5, 1, rat(40, 10)), (0x8822, 3, 1, short(3)),
            (0x8827, 3, 1, short(200)), (0x9003, 2, 20, b"2026:11:09 09:14:12\0"),
            (0x9204, 10, 1, srat(-3, 10)), (0x9207, 3, 1, short(5)), (0x9209, 3, 1, short(16)),
            (0x920A, 5, 1, rat(25, 1)), (0xA001, 3, 1, short(1)), (0xA002, 4, 1, struct.pack("<I", 4608)),
            (0xA003, 4, 1, struct.pack("<I", 3456)), (0xA403, 3, 1, short(0)), (0xA434, 2, len(lens), lens),
        ]
    if with_note:
        exif_entries.append((0x927C, 7, len(note), note))
    exif_entries.sort(key=lambda e: e[0])
    ifd0_len = 2 + 12 + 4
    exif_off = 8 + ifd0_len
    exif_ifd = build_ifd(exif_entries, exif_off)
    ifd0 = build_ifd([(0x8769, 4, 1, exif_off)], 8)
    tiff = b"II*\0" + struct.pack("<I", 8) + ifd0 + exif_ifd
    app1 = b"Exif\0\0" + tiff
    return b"\xff\xd8\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9"


class PictureInfo(unittest.TestCase):
    def test_all_fields(self):
        info = exif.picture_info(synthetic_jpeg())
        self.assertEqual(info["mode"], "A")
        self.assertEqual(info["shutter"], "1/250")
        self.assertEqual(info["aperture"], 4.0)
        self.assertEqual(info["compensation"], -0.3)
        self.assertEqual(info["iso"], 200)
        self.assertEqual(info["white_balance"], "Auto")
        self.assertEqual(info["metering"], "ESP")
        self.assertIs(info["flash"], False)
        self.assertEqual(info["focal"], 25.0)
        self.assertEqual(info["lens"], "M.ZUIKO 12-40mm F2.8")
        self.assertEqual(info["color_space"], "sRGB")
        self.assertEqual(info["pixels"], "4608x3456")
        self.assertEqual(info["datetime"], "2026-11-09 09:14:12")

    def test_picture_mode_from_maker_note(self):
        info = exif.picture_info(synthetic_jpeg())
        self.assertEqual(info.get("picture_mode"), "Natural")

    def test_missing_fields_are_left_out(self):
        info = exif.picture_info(synthetic_jpeg(with_note=False))
        self.assertNotIn("picture_mode", info)
        info2 = exif.picture_info(_only_iso())
        self.assertEqual(info2, {"iso": 400})

    def test_long_shutter(self):
        self.assertEqual(exif._shutter(2.0), "2 s")
        self.assertEqual(exif._shutter(0.5), "0.5 s")
        self.assertEqual(exif._shutter(1 / 4000), "1/4000")

    def test_no_exif(self):
        self.assertIsNone(exif.picture_info(b"not a jpeg"))


def _only_iso():
    exif_ifd = build_ifd([(0x8827, 3, 1, struct.pack("<H", 400))], 26)
    ifd0 = build_ifd([(0x8769, 4, 1, 26)], 8)
    tiff = b"II*\0" + struct.pack("<I", 8) + ifd0 + exif_ifd
    return b"\xff\xd8\xff\xe1\x00\x10Exif\0\0" + tiff


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeCam:
    features = []
    calls = 0

    def read_head(self, path, size):
        FakeCam.calls += 1
        if "BAD" in path:
            raise CameraError("not on the card")
        return synthetic_jpeg()


class ExifEndpoint(unittest.TestCase):
    def setUp(self):
        self.old = (server.cam, server.conn_type)
        server.cam, server.conn_type = FakeCam(), "wifi"
        server.exif_cache.clear()
        FakeCam.calls = 0
        self.port = free_port()
        server.allowed_hosts.add("127.0.0.1:%d" % self.port)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.cam, server.conn_type = self.old

    def get(self, path):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, path)) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_endpoint_returns_info_and_caches(self):
        code, body = self.get("/api/exif?path=/DCIM/100OLYMP/P1010001.JPG")
        self.assertEqual(code, 200)
        self.assertEqual(body["exif"]["shutter"], "1/250")
        self.get("/api/exif?path=/DCIM/100OLYMP/P1010001.JPG")
        self.assertEqual(FakeCam.calls, 1)

    def test_raw_refused(self):
        code, body = self.get("/api/exif?path=/DCIM/100OLYMP/P1010001.ORF")
        self.assertNotEqual(code, 200)
        self.assertIn("error", body)

    def test_camera_error_is_reported(self):
        code, body = self.get("/api/exif?path=/DCIM/100OLYMP/BAD.JPG")
        self.assertNotEqual(code, 200)


class PlaybackPage(unittest.TestCase):
    """The page has the playback controls and texts (no browser here)."""
    def test_page(self):
        import re
        from pathlib import Path
        html = (Path(__file__).resolve().parent.parent / "omcap" / "web" / "index.html").read_text(encoding="utf-8")
        for i in ("galExif", "galSelect", "vInfoBtn", "vFit", "vPanel", "vStrip", "vExif"):
            self.assertIn('id="%s"' % i, html)
        for k in ("info.image", "info.simple", "info.overall", "exif.mode", "exif.picture", "card.sizeS"):
            self.assertRegex(html, r'"%s": "' % re.escape(k))
        self.assertIn("/api/exif?path=", html)


if __name__ == "__main__":
    unittest.main()
