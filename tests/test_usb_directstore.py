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

    def __init__(self, files, events, card=False, fail=None, left=(), timed=()):
        self.files, self.events, self.card, self.fail = list(files), list(events), card, fail
        self.left, self.fetched = list(left), []  # left: pictures still offered before the shot
        self.timed = [(time.monotonic() + t, ev) for t, ev in timed]  # events that arrive after t seconds
        self.storage_error, self.offered = False, False  # offered: the shot's files only exist after event c004

    def wait_for_event(self, timeout):
        if self.events:
            ev = self.events.pop(0)
            self.offered = self.offered or "c004" in str(ev[1])
            return ev
        if self.timed and time.monotonic() >= self.timed[0][0]:
            return self.timed.pop(0)[1]
        threading.Event().wait(0.005)
        return pg.GP_EVENT_TIMEOUT, None

    def omd_direct_info(self):
        src = self.left or (self.files if self.offered else [])
        return {"kind": 0, "ext": src[0][0], "size": len(src[0][1]), "id": 0x7F02} if src else None

    def omd_direct_fetch(self, info):
        """Pieces of 4 bytes, like the adapter (lazy: a failure comes while iterating)."""
        if self.fail:
            raise pg.GPhoto2Error(self.fail)
        ext, data = self.left.pop(0) if self.left else self.files.pop(0)
        self.fetched.append(ext)
        if self.files and not self.left:  # the camera announces the next file after the last piece
            self.events.append((pg.GP_EVENT_UNKNOWN, "PTP Property d0de changed"))
        for i in range(0, len(data), 4):
            yield data[i:i + 4]

    def get_storageinfo(self):
        if self.storage_error:
            raise pg.GPhoto2Error("PTP: busy")
        return [type("I", (), {"freekbytes": 1000 if self.card == 1 else 0})()] if self.card else []


C004 = (pg.GP_EVENT_UNKNOWN, "PTP Event c004, Param1 00000000")
D0DE = (pg.GP_EVENT_UNKNOWN, "PTP Property d0de changed")
CARD_FILE = (pg.GP_EVENT_FILE_ADDED, type("P", (), {"folder": "/d", "name": "P1.JPG"})())


def make_cam(fake, saved):
    cam = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
    cam.gp, cam._c, cam._lock, cam.allow_write = pg, fake, threading.Lock(), True
    cam.gone, cam._new_files, cam._pending, cam._event_log = False, [], [], []
    cam.direct_paths, cam._direct_hit, cam._direct_wait = [], False, False
    cam.stage, cam.saf_shot, cam.af_failed, cam.last_jpg, cam.loupe_on = 0, False, False, None, False
    cam._take_t0, cam.last_press, cam.shooting, cam._is_bulb, cam._pulse = None, 0.0, False, lambda: True, lambda: None
    def sink(ext, size, pieces, late=False):
        saved.append((ext + ("_late" if late else ""), b"".join(pieces)))
        return "/x/" + ext
    cam.on_direct_file = sink
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
                return super().omd_direct_fetch(info)  # a generator: the failure may also come while iterating
        saved = []
        cam = make_cam(Half([(".ORF", b"ORF"), (".JPG", b"J")], [C004]), saved)
        cam.shoot()
        self.assertEqual(saved, [(".ORF", b"ORF")])

    def test_held_button_release(self):
        saved = []
        fake = Fake([(".JPG", b"J")], [])
        cam = make_cam(fake, saved)
        old, usb_camera.FOCUS_WAIT = usb_camera.FOCUS_WAIT, 0.05
        try:
            cam.press(2)  # the card is checked here, before the release
        finally:
            usb_camera.FOCUS_WAIT = old
        fake.events += [C004, D0DE]
        cam.press(0)
        self.assertEqual(saved, [(".JPG", b"J")])
        self.assertEqual(cam.take_direct_files(), ["/x/.JPG"])

    def test_card_with_busy_event_and_late_file_is_the_card_path(self):
        # d0de also changes with a card: it must not end the wait and raise "did not release" (review finding)
        usb_camera.SHOT_TIMEOUT = 3
        fake = Fake([(".ORF", b"ORF")], [C004, D0DE], card=True, timed=[(1.0, CARD_FILE)])
        saved = []
        cam = make_cam(fake, saved)
        t0 = time.monotonic()
        self.assertEqual(cam.shoot(), ["/d/P1.JPG"])
        self.assertGreaterEqual(time.monotonic() - t0, 1.0)
        self.assertEqual((saved, fake.fetched), ([], []))

    def test_locked_card_counts_as_a_card(self):
        fake = Fake([(".ORF", b"ORF")], [C004], card=2)  # write-protected: storage listed with 0 KB free
        cam = make_cam(fake, [])
        with self.assertRaises(CameraError):
            cam.shoot()
        self.assertEqual(fake.fetched, [])

    def test_unknown_card_state_counts_as_a_card(self):
        fake = Fake([(".ORF", b"ORF")], [C004])
        fake.storage_error = True
        cam = make_cam(fake, [])
        with self.assertRaises(CameraError):
            cam.shoot()
        self.assertEqual(fake.fetched, [])

    def test_card_found_after_the_event_waits_for_the_card_file(self):
        usb_camera.SHOT_TIMEOUT = 3
        calls = []

        class Late(Fake):  # no card before the release, a card when asked after the event
            def get_storageinfo(self):
                calls.append(1)
                self.card = 1 if len(calls) > 1 else 0
                return super().get_storageinfo()
        fake = Late([(".ORF", b"ORF")], [C004], timed=[(1.0, CARD_FILE)])
        self.assertEqual(make_cam(fake, []).shoot(), ["/d/P1.JPG"])
        self.assertEqual(fake.fetched, [])

    def test_focus_stacking_refused_without_a_card(self):
        shutter = []
        cam = make_cam(Fake([(".ORF", b"ORF")], [C004]), [])
        cam._stacking_on = lambda: True
        cam._shutter = shutter.append
        with self.assertRaises(CameraError) as e:
            cam.shoot()
        self.assertIn("Focus Stacking needs a card", str(e.exception))
        self.assertEqual(shutter, [])  # nothing was released

    def test_focus_stacking_with_a_card_is_unchanged(self):
        usb_camera.STACK_WAIT = 0.0
        fake = Fake([], [CARD_FILE, C004], card=True)
        cam = make_cam(fake, [])
        cam._stacking_on = lambda: True
        self.assertEqual(cam.shoot(), ["/d/P1.JPG"])

    def test_leftover_picture_is_saved_first_as_late(self):
        saved = []
        fake = Fake([(".JPG", b"NEWJ")], [C004], left=[(".ORF", b"OLDORF")])
        cam = make_cam(fake, saved)
        cam.shoot()
        self.assertEqual(saved, [(".ORF_late", b"OLDORF"), (".JPG", b"NEWJ")])
        self.assertEqual(cam.take_direct_files(), ["/x/.JPG"])  # the leftover is not part of this shot

    def test_leftover_unreadable_does_not_block_the_shot(self):
        class Stuck(Fake):
            def omd_direct_info(self):
                if self.left:
                    raise pg.GPhoto2Error("PTP: busy")
                return super().omd_direct_info()
        saved = []
        cam = make_cam(Stuck([(".JPG", b"NEWJ")], [C004], left=[(".ORF", b"OLD")]), saved)
        with self.assertRaises(CameraError):  # the stuck picture is still offered: the read fails cleanly
            cam.shoot()

    def test_bulb_stop_saves_without_a_card(self):
        saved = []
        cam = make_cam(Fake([(".ORF", b"ORF"), (".JPG", b"J")], [C004, D0DE]), saved)
        cam.take_start()
        cam.take_stop()
        self.assertEqual(saved, [(".ORF", b"ORF"), (".JPG", b"J")])
        self.assertEqual(cam.take_direct_files(), ["/x/.ORF", "/x/.JPG"])
        self.assertFalse(cam.shooting)

    def test_bulb_stop_with_a_card_reads_nothing(self):
        fake = Fake([(".ORF", b"ORF")], [C004], card=True)
        cam = make_cam(fake, [])
        cam.take_start()
        cam.take_stop()
        self.assertEqual(fake.fetched, [])


def read(path):
    with open(path, "rb") as f:
        return f.read()


def sd(data, ext, chunk=4, **kw):
    """save_direct with `data` handed over in pieces, as the camera does."""
    return server.save_direct(ext, len(data), (data[i:i + chunk] for i in range(0, len(data), chunk)), **kw)


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
        a = sd(b"orf", ".ORF")
        b = sd(b"\xff\xd8jpg", ".JPG")
        self.assertEqual(os.path.splitext(a)[0], os.path.splitext(b)[0])
        self.assertTrue(os.path.basename(a).startswith("E-M1_"))
        self.assertEqual(read(a), b"orf")
        self.assertEqual(sorted(os.listdir(self.tmp.name)), sorted([os.path.basename(a), os.path.basename(b)]))

    def test_jpg_is_shown_as_last_shot(self):
        p = sd(b"\xff\xd8jpg", ".JPG")
        self.assertEqual((server.state["last_shot_jpeg"], server.state["latest"]), (b"\xff\xd8jpg", os.path.basename(p)))
        self.assertIsNone(server.state["last_shot"])

    def test_raw_only_keeps_the_last_picture(self):
        sd(b"orf", ".ORF")
        self.assertIsNone(server.state["last_shot_jpeg"])
        self.assertTrue(server.state["latest"].endswith(".ORF"))

    def test_collision_gets_a_number(self):
        orig = server.direct_name
        server.direct_name = lambda ext, now=None, late=False: "same" + ext
        try:
            a = sd(b"1", ".ORF")
            b = sd(b"2", ".ORF")
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
        self.assertTrue(os.path.basename(sd(b"x", ".ORF")).startswith("trip_E-M1_"))

    def test_bad_extension_is_neutralised(self):
        self.assertTrue(sd(b"x", "/../x").endswith(".BIN"))

    def test_failed_read_leaves_nothing(self):
        def pieces():
            yield b"abcd"
            raise CameraError("USB: gone")
        with self.assertRaises(CameraError):
            server.save_direct(".ORF", 8, pieces())
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_pieces_are_on_disk_before_the_last_is_requested(self):
        seen = []

        def pieces():
            yield b"abcd"
            seen.append([open(os.path.join(self.tmp.name, n), "rb").read() for n in os.listdir(self.tmp.name)])
            yield b"ef"  # the request of this piece carries clear=1
        a = server.save_direct(".ORF", 6, pieces())
        self.assertEqual(seen, [[b"abcd"]])
        self.assertTrue(os.listdir(self.tmp.name)[0].endswith(".ORF"))
        self.assertEqual(read(a), b"abcdef")

    def test_no_space_stops_before_any_piece(self):
        asked = []

        def pieces():
            asked.append(1)  # would be the first 0x9493
            yield b"x"
        old = server.shutil.disk_usage
        server.shutil.disk_usage = lambda p: type("U", (), {"free": 1000})()
        try:
            with self.assertRaises(CameraError) as e:
                server.save_direct(".ORF", 100, pieces())
        finally:
            server.shutil.disk_usage = old
        self.assertIn("stays in the camera", str(e.exception))
        self.assertEqual((asked, os.listdir(self.tmp.name)), ([], []))

    def test_folder_not_writable_stops_before_any_piece(self):
        asked = []
        blocker = os.path.join(self.tmp.name, "file")
        open(blocker, "w").close()
        server.save_cfg["dir"] = blocker  # a file where the folder should be
        with self.assertRaises(CameraError):
            server.save_direct(".ORF", 4, (asked.append(1) or b"x" for _ in range(1)))
        self.assertEqual(asked, [])

    def test_final_write_failure_goes_to_temp(self):
        real = os.fsync

        def boom(fd):
            raise OSError("disk full")
        os.fsync = boom
        try:
            with self.assertRaises(CameraError) as e:
                sd(b"abcdef", ".ORF")
        finally:
            os.fsync = real
        msg = str(e.exception)
        self.assertIn(tempfile.gettempdir(), msg)
        rescue = [w for w in msg.replace(";", " ").split() if w.startswith(tempfile.gettempdir())][0]
        self.addCleanup(os.remove, rescue)
        self.assertEqual(read(rescue), b"ef")
        self.assertTrue(any(n.endswith(".part") for n in os.listdir(self.tmp.name)))  # first part kept

    def test_late_name(self):
        self.assertIn("_late.ORF", os.path.basename(sd(b"old", ".ORF", late=True)))


if __name__ == "__main__":
    unittest.main()


class PcModeBusy(unittest.TestCase):
    """A camera just switched on answers busy to the first d052 write; OM Capture retried and succeeded."""

    def test_busy_then_ok(self):
        calls = []

        class Cam(ptp.PtpCamera):
            def __init__(self):
                pass

            def set_prop(self, code, value, dtype, timeout=5000):
                calls.append(code)
                if len(calls) < 3:
                    raise ptp.PtpError("busy", code=ptp.RC_BUSY)

            def prop_desc(self, code):
                return {"value": 1}
        self.assertTrue(Cam().pc_mode(True))
        self.assertEqual(len(calls), 3)

    def test_other_error_not_retried(self):
        class Cam(ptp.PtpCamera):
            def __init__(self):
                pass

            def set_prop(self, code, value, dtype, timeout=5000):
                raise ptp.PtpError("denied", code=0x200F)
        with self.assertRaises(ptp.PtpError):
            Cam().pc_mode(True)
