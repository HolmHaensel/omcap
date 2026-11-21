"""Shoot without a card (REQ-F61): the camera hands the picture over PTP 0x9495/0x9493. No camera: scripted answers."""
import os
import struct
import tempfile
import threading
import time
import unittest

from omcap import ptp, ptp_gphoto as pg, server, usb_camera
from omcap.camera import CameraError

# Info answer as traced from OM Capture (2026-11-16, round_b.jsonl), 20 bytes
ORF_INFO = bytes.fromhex("0200000046524f2e6842ed0000000000027f0000")
JPG_INFO = bytes.fromhex("0500000047504a2e4b472c0000000000027f0000")


class Scripted(ptp.PtpCamera):
    def __init__(self, answers):
        super().__init__(None)
        self.answers, self.sent = list(answers), []

    def transact(self, code, params=(), data=None, want_data=False, timeout=5000):
        self.sent.append((code, params))
        a = self.answers.pop(0) if self.answers else b""
        if isinstance(a, Exception):
            raise a
        return a, ()


class Layer(unittest.TestCase):
    def test_info_layout(self):
        self.assertEqual(ptp.parse_ds_info(ORF_INFO), {"kind": 2, "ext": ".ORF", "size": 0x00ED4268, "id": 0x7F02})
        self.assertEqual(ptp.parse_ds_info(JPG_INFO), {"kind": 5, "ext": ".JPG", "size": 0x002C474B, "id": 0x7F02})

    def test_info_empty_is_none(self):
        self.assertIsNone(ptp.parse_ds_info(b""))
        self.assertIsNone(ptp.parse_ds_info(bytes(20)))
        self.assertIsNone(ptp.parse_ds_info(ORF_INFO[:10]))

    def test_info_unknown_extension_uses_kind(self):
        raw = struct.pack("<I4sIII", 5, b"\x00\x00\x00\x00", 10, 0, 0x7F02)
        self.assertEqual(ptp.parse_ds_info(raw)["ext"], ".JPG")

    def test_info_call_has_no_parameters(self):
        c = Scripted([ORF_INFO])
        self.assertEqual(c.direct_store_info()["size"], 0x00ED4268)
        self.assertEqual(c.sent, [(0x9495, ())])

    def test_three_pieces_like_om_capture(self):
        size = 0x200000 * 2 + 5
        c = Scripted([b"a" * 0x200000, b"b" * 0x200000, b"c" * 5])
        out = list(c.direct_store_read(0x7F02, size))
        self.assertEqual([len(x) for x in out], [0x200000, 0x200000, 5])
        # clear = 0 on every piece but the last of the file, exactly as in the trace
        self.assertEqual(c.sent, [(0x9493, (0x7F02, 0, 0x200000, 0)), (0x9493, (0x7F02, 0x200000, 0x200000, 0)),
                                  (0x9493, (0x7F02, 0x400000, 5, 1))])

    def test_exact_multiple_clears_on_the_last_piece(self):
        c = Scripted([b"a" * 4, b"b" * 4])
        list(c.direct_store_read(1, 8, chunk=4))
        self.assertEqual([p[3] for _, p in c.sent], [0, 1])

    def test_busy_is_retried(self):
        c = Scripted([ptp.PtpError("busy", code=ptp.RC_BUSY), ORF_INFO])
        self.assertEqual(c.direct_store_info()["ext"], ".ORF")
        c = Scripted([ptp.PtpError("busy", code=ptp.RC_BUSY), b"xy"])
        self.assertEqual(b"".join(c.direct_store_read(1, 2)), b"xy")

    def test_busy_forever_raises(self):
        c = Scripted([ptp.PtpError("busy", code=ptp.RC_BUSY)] * 100)
        with self.assertRaises(ptp.PtpError):
            c.direct_store_info(wait=0.1)

    def test_refusal_and_short_piece_raise(self):
        with self.assertRaises(ptp.PtpError):
            list(Scripted([ptp.PtpError("no", code=0x2005)]).direct_store_read(1, 8))
        with self.assertRaises(ptp.PtpError):
            list(Scripted([b"ab"]).direct_store_read(1, 8))


class Fake:
    """Camera object with the own layer's adapter methods and a scripted event queue."""

    def __init__(self, files, events, card=False, fail=None):
        self.files, self.events, self.card, self.fail = list(files), list(events), card, fail
        self.fetched = []

    def wait_for_event(self, timeout):
        if self.events:
            return self.events.pop(0)
        threading.Event().wait(0.005)
        return pg.GP_EVENT_TIMEOUT, None

    def omd_direct_info(self):
        return {"kind": 0, "ext": self.files[0][0], "size": len(self.files[0][1]), "id": 0x7F02} if self.files else None

    def omd_direct_fetch(self, info):
        if self.fail:
            raise pg.GPhoto2Error(self.fail)
        ext, data = self.files.pop(0)
        self.fetched.append(ext)
        if self.files:  # the camera announces the next file after the last piece
            self.events.append((pg.GP_EVENT_UNKNOWN, "PTP Property d0de changed"))
        return data

    def get_storageinfo(self):
        return [type("I", (), {"freekbytes": 1000})()] if self.card else []


C004 = (pg.GP_EVENT_UNKNOWN, "PTP Event c004, Param1 00000000")
D0DE = (pg.GP_EVENT_UNKNOWN, "PTP Property d0de changed")
CARD_FILE = (pg.GP_EVENT_FILE_ADDED, type("P", (), {"folder": "/d", "name": "P1.JPG"})())


def make_cam(fake, saved):
    cam = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
    cam.gp, cam._c, cam._lock, cam.allow_write = pg, fake, threading.Lock(), True
    cam.gone, cam._new_files, cam._pending, cam._event_log = False, [], [], []
    cam.direct_paths, cam._direct_hit, cam._direct_wait = [], False, False
    cam.stage, cam.saf_shot, cam.af_failed, cam.last_jpg, cam.loupe_on = 0, False, False, None, False
    cam.on_direct_file = lambda data, ext: (saved.append((ext, data)), "/x/" + ext)[1]
    cam._hold_add = lambda n: None
    cam._stacking_on = lambda: False
    cam._value = lambda name: "1"
    cam._shutter = lambda step: None
    cam._fast_picture = lambda: None
    return cam


class Shoot(unittest.TestCase):
    def setUp(self):
        self.old = (usb_camera.DIRECT_GRACE, usb_camera.DIRECT_NEXT_WAIT, usb_camera.SHOT_TIMEOUT)
        usb_camera.DIRECT_GRACE, usb_camera.DIRECT_NEXT_WAIT, usb_camera.SHOT_TIMEOUT = 0.02, 0.2, 1

    def tearDown(self):
        usb_camera.DIRECT_GRACE, usb_camera.DIRECT_NEXT_WAIT, usb_camera.SHOT_TIMEOUT = self.old

    def test_orf_then_jpg_without_card(self):
        fake = Fake([(".ORF", b"ORFDATA"), (".JPG", b"JPGDATA")], [C004, D0DE])
        saved = []
        cam = make_cam(fake, saved)
        self.assertEqual(cam.shoot(), [])  # no card files; the pictures are in take_direct_files()
        self.assertEqual(saved, [(".ORF", b"ORFDATA"), (".JPG", b"JPGDATA")])
        self.assertEqual(cam.take_direct_files(), ["/x/.ORF", "/x/.JPG"])
        self.assertEqual(cam.take_direct_files(), [])

    def test_raw_only(self):
        saved = []
        cam = make_cam(Fake([(".ORF", b"ORF")], [C004, D0DE]), saved)
        cam.shoot()
        self.assertEqual(saved, [(".ORF", b"ORF")])

    def test_finishes_without_the_21_s_wait(self):
        usb_camera.SHOT_TIMEOUT = 20
        cam = make_cam(Fake([(".JPG", b"J")], [C004]), [])
        t0 = time.monotonic()
        cam.shoot()
        self.assertLess(time.monotonic() - t0, 3)

    def test_card_file_means_no_download(self):
        fake = Fake([(".ORF", b"ORF")], [CARD_FILE, C004], card=True)
        saved = []
        cam = make_cam(fake, saved)
        self.assertEqual(cam.shoot(), ["/d/P1.JPG"])
        self.assertEqual((saved, fake.fetched), ([], []))

    def test_card_present_means_no_download(self):
        fake = Fake([(".ORF", b"ORF")], [C004], card=True)
        saved = []
        cam = make_cam(fake, saved)
        with self.assertRaises(CameraError):  # as today: no card file arrived
            cam.shoot()
        self.assertEqual((saved, fake.fetched), ([], []))

    def test_card_file_after_the_event_wins(self):
        fake = Fake([(".ORF", b"ORF")], [C004, CARD_FILE])
        saved = []
        cam = make_cam(fake, saved)
        self.assertEqual(cam.shoot(), ["/d/P1.JPG"])
        self.assertEqual(saved, [])

    def test_libgphoto2_layer_skipped(self):
        cam = make_cam(Fake([(".ORF", b"ORF")], [C004]), [])
        cam._c = type("Plain", (), {"wait_for_event": Fake([], [C004]).wait_for_event,
                                    "get_storageinfo": lambda s: []})()
        with self.assertRaises(CameraError):
            cam.shoot()

    def test_read_error_is_a_clean_failure(self):
        saved = []
        cam = make_cam(Fake([(".ORF", b"ORF")], [C004], fail="PTP: busy"), saved)
        with self.assertRaises(CameraError) as e:
            cam.shoot()
        self.assertIn("no card", str(e.exception))
        self.assertEqual(saved, [])

    def test_error_on_second_file_keeps_the_first(self):
        class Half(Fake):
            def omd_direct_fetch(self, info):
                if self.fetched:
                    raise pg.GPhoto2Error("PTP: boom")
                return super().omd_direct_fetch(info)
        saved = []
        cam = make_cam(Half([(".ORF", b"ORF"), (".JPG", b"J")], [C004]), saved)
        cam.shoot()
        self.assertEqual(saved, [(".ORF", b"ORF")])

    def test_held_button_release(self):
        saved = []
        cam = make_cam(Fake([(".JPG", b"J")], [C004, D0DE]), saved)
        cam.stage = 2
        cam.press(0)
        self.assertEqual(saved, [(".JPG", b"J")])
        self.assertEqual(cam.take_direct_files(), ["/x/.JPG"])


def read(path):
    with open(path, "rb") as f:
        return f.read()


class Saving(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (dict(server.save_cfg), dict(server.state), dict(server.direct_shot))
        server.save_cfg.update(dir=self.tmp.name, scheme="original", prefix="")
        server.direct_shot.update(base=None, t=0.0, exts=set())
        server.state.update(last_shot=None, last_shot_jpeg=None, fast_n=0, latest=None)

    def tearDown(self):
        server.save_cfg.clear()
        server.save_cfg.update(self.old[0])
        server.state.clear()
        server.state.update(self.old[1])
        server.direct_shot.clear()
        server.direct_shot.update(self.old[2])
        self.tmp.cleanup()

    def test_orf_and_jpg_share_the_name(self):
        a = server.save_direct(b"orf", ".ORF")
        b = server.save_direct(b"\xff\xd8jpg", ".JPG")
        self.assertEqual(os.path.splitext(a)[0], os.path.splitext(b)[0])
        self.assertTrue(os.path.basename(a).startswith("E-M1_"))
        self.assertEqual(read(a), b"orf")
        self.assertEqual(sorted(os.listdir(self.tmp.name)), sorted([os.path.basename(a), os.path.basename(b)]))

    def test_jpg_is_shown_as_last_shot(self):
        p = server.save_direct(b"\xff\xd8jpg", ".JPG")
        self.assertEqual((server.state["last_shot_jpeg"], server.state["latest"]), (b"\xff\xd8jpg", os.path.basename(p)))
        self.assertIsNone(server.state["last_shot"])

    def test_raw_only_keeps_the_last_picture(self):
        server.save_direct(b"orf", ".ORF")
        self.assertIsNone(server.state["last_shot_jpeg"])
        self.assertTrue(server.state["latest"].endswith(".ORF"))

    def test_collision_gets_a_number(self):
        orig = server.direct_name
        server.direct_name = lambda ext, now=None: "same" + ext
        try:
            a = server.save_direct(b"1", ".ORF")
            b = server.save_direct(b"2", ".ORF")
        finally:
            server.direct_name = orig
        self.assertEqual((os.path.basename(a), os.path.basename(b)), ("same.ORF", "same-1.ORF"))
        self.assertEqual(read(a), b"1")

    def test_second_shot_gets_a_new_name(self):
        n1 = server.direct_name(".ORF", now=1001.0)
        n0 = server.direct_name(".JPG", now=1001.5)
        self.assertEqual(n1[:-4], n0[:-4])
        self.assertNotEqual(server.direct_name(".ORF", now=1002.0), n1)  # ORF again: a new shot

    def test_prefix_scheme(self):
        server.save_cfg.update(scheme="prefix", prefix="trip_")
        self.assertTrue(os.path.basename(server.save_direct(b"x", ".ORF")).startswith("trip_E-M1_"))

    def test_bad_extension_is_neutralised(self):
        self.assertTrue(server.save_direct(b"x", "/../x").endswith(".BIN"))

    def test_failed_write_leaves_no_final_file(self):
        with self.assertRaises(TypeError):
            server.save_direct(object(), ".ORF")
        self.assertEqual([n for n in os.listdir(self.tmp.name) if not n.endswith(".part")], [])


if __name__ == "__main__":
    unittest.main()
