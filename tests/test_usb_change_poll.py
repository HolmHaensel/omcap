"""USB mode dial without a session rebuild: change poll 0x9489/0x9486 as OM Capture does (REQ-F30), no camera."""
import struct
import threading
import time
import unittest
from unittest import mock

from omcap import ptp, ptp_gphoto as pg, usb_camera
from tests.test_ptp import FakeTransport, pkt
from tests.test_ptp_gphoto import FakePtp, camera

# 0x948A answer recorded from OM Capture on the E-M1 (round_c 2026-11-22): 17 descriptors, d057 first, d064 last
REAL_948A = bytes.fromhex(
    "1100000057d0040000000001000206000100020003000400050006005cd0040000000003000203000100020003005dd004000000000000"
    "010000ff0401005ed004000000000000010000bf03010074d004000000000000010000ff04010075d004000000000000010000bf030100"
    "85d00400000000020002020001000200d0d004000000000000010000ff040100d1d004000000000000010000bf030100d2d00400000000"
    "0000010000ff040100d3d004000000000000010000bf030100edd0040000000000000201000000e1d006000000000000940600000100"
    "000000ffffffff0100000083d0040000000002000202000100020084d00400000000070002090001000200030004000500060007000800"
    "090079d0040000000002000202000100020064d004000000000300020300010002000300")


def desc(code, value, enum=(1, 2, 3, 4, 8), writable=False):
    return struct.pack("<HHBHHB", code, 4, int(writable), 0, value, 2) + struct.pack("<H%dH" % len(enum), len(enum), *enum)


def dump(*descs):
    return struct.pack("<I", len(descs)) + b"".join(descs)


class Parse(unittest.TestCase):
    def test_real_poll_answer(self):
        d = ptp.parse_prop_descs(REAL_948A)
        self.assertEqual(len(d), 17)
        self.assertEqual((d[0xD057]["value"], d[0xD057]["enum"]), (1, [1, 2, 3, 4, 5, 6]))
        self.assertEqual(d[0xD05D]["range"], (0, 1279, 1))
        self.assertEqual(d[0xD0E1]["value"], 1684)
        self.assertEqual(d[0xD064]["enum"], [1, 2, 3])

    def test_mode_in_dump(self):
        d = ptp.parse_prop_descs(dump(desc(0xD006, 3), desc(0xD002, 40, (35, 40, 220), True)))
        self.assertEqual((d[0xD006]["value"], d[0xD006]["writable"]), (3, False))
        self.assertEqual((d[0xD002]["value"], d[0xD002]["writable"]), (40, True))
        self.assertEqual(ptp.parse_prop_descs(b"\0\0\0\0"), {})

    def test_single_desc_unchanged(self):
        self.assertEqual(ptp.parse_prop_desc(desc(0xD006, 2))["value"], 2)


class Transactions(unittest.TestCase):
    def test_set_poll_list_sends_count_and_codes(self):
        t = FakeTransport([pkt(ptp.RESP, ptp.RC_OK, 1)])
        ptp.PtpCamera(t).set_poll_list([0xD006, 0xD01C])
        self.assertEqual(struct.unpack_from("<IHHI", t.sent[0]), (12, ptp.CMD, 0x9489, 1))
        self.assertEqual(t.sent[1], pkt(ptp.DATA, 0x9489, 1, struct.pack("<IHH", 2, 0xD006, 0xD01C)))

    def test_changed_props(self):
        body = dump(desc(0xD006, 4))
        t = FakeTransport([pkt(ptp.DATA, 0x9486, 1, body), pkt(ptp.RESP, ptp.RC_OK, 1)])
        self.assertEqual(ptp.PtpCamera(t).changed_props()[0xD006]["value"], 4)
        self.assertEqual(struct.unpack_from("<IHHI", t.sent[0]), (12, ptp.CMD, 0x9486, 1))


class PollFake(FakePtp):
    """FakePtp whose 0x1014 keeps the session-start value; only the poll sees camera-side changes."""

    def __init__(self, refuse=False):
        super().__init__()
        self.refuse, self.camera_mode, self.poll_list = refuse, 1, None

    def set_poll_list(self, codes):
        if self.refuse:
            raise ptp.PtpError("PTP 0x9489 answered 0x2005", code=0x2005)
        self.poll_list = list(codes)

    def changed_props(self):
        out = {c: dict(self.props[c], code=c) for c in self.poll_list if c in self.props}
        out[0xD006]["value"] = self.camera_mode
        return out


INFO = {"operations": [0x9486, 0x9489], "properties": [0xD006, 0xD01C, 0xD002, 0xD007, 0xD008]}


class Backend(unittest.TestCase):
    def test_poll_list_only_with_listed_codes(self):
        fake = PollFake()
        c = camera(fake)
        self.assertTrue(c._start_poll(fake, INFO))
        self.assertEqual(fake.poll_list, [0xD006, 0xD01C, 0xD002, 0xD008, 0xD007])  # POLL_CODES order, listed only
        self.assertFalse(c._start_poll(fake, {"operations": [], "properties": INFO["properties"]}))

    def test_refused_poll_list_falls_back(self):
        fake = PollFake(refuse=True)
        c = camera(fake)
        with mock.patch("builtins.print"):
            self.assertFalse(c._start_poll(fake, INFO))
        self.assertEqual(c._polled, {})

    def test_reads_use_the_poll(self):
        fake = PollFake()
        c = camera(fake)
        c.polling = c._start_poll(fake, INFO)
        fake.camera_mode = 3  # dial turned to A: 0x1014 still says 1 (M)
        self.assertEqual(c.get_single_config("d006").get_value(), "1")
        c.poll_props()
        self.assertEqual(c.get_single_config("d006").get_value(), "3")
        self.assertEqual(c.get_single_config("batterylevel").get_value(), "80%")  # not polled: 0x1014 as before

    def test_written_value_until_next_poll(self):
        fake = PollFake()
        c = camera(fake)
        c.polling = c._start_poll(fake, INFO)
        w = c.get_single_config("aperture")
        w.set_value("4.0")
        c.set_single_config("aperture", w)
        self.assertEqual(c.get_single_config("aperture").get_value(), "4.0")

    def test_write_uses_the_polled_choices(self):
        fake = PollFake()
        c = camera(fake)
        c.polling = c._start_poll(fake, INFO)
        fake.props[0xD002] = dict(fake.props[0xD002], enum=[35, 40, 220])  # 0x1014: session-start choices
        polled = fake.changed_props
        fake.changed_props = lambda: {**polled(), 0xD002: dict(fake.props[0xD002], code=0xD002, enum=[28, 35])}
        c.poll_props()
        w = c.get_single_config("aperture")
        w.set_value("2.8")  # offered only by the poll (e.g. after a lens change)
        c.set_single_config("aperture", w)
        self.assertEqual(fake.calls[-1], ("set", 0xD002, 28, 4))

class Mode(unittest.TestCase):
    def make(self, fake=None, polling=True):
        cam = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)  # no USB session
        cam.gp, cam._lock, cam._hold, cam._hold_lock, cam.stage = pg, threading.Lock(), 0, threading.Lock(), 0
        fake = fake or PollFake()
        cam._c = camera(fake)
        cam._c.polling = cam._c._start_poll(fake, INFO) and polling
        return cam, fake

    def test_dial_turn_seen_without_rebuild(self):
        cam, fake = self.make()
        with mock.patch("builtins.print") as log:
            self.assertFalse(cam.poll_mode())  # first look: nothing to compare
            self.assertIsNone(cam.mode_changed_at)
            fake.camera_mode = 3
            t0 = time.time()
            self.assertTrue(cam.poll_mode())
            self.assertFalse(cam.poll_mode())
        self.assertGreaterEqual(cam.mode_changed_at, t0)
        self.assertIn("M -> A", log.call_args_list[0][0][0])
        self.assertEqual(usb_camera.EXPOSURE_PROGRAM[str(cam._value("d006"))], "A")  # what props() shows

    def test_writable_flags_count_as_a_turn(self):
        cam, fake = self.make()
        cam.poll_mode()
        fake.props[0xD007]["writable"] = False  # e.g. P -> iAUTO: d006 still reads P, ISO locked
        with mock.patch("builtins.print"):
            self.assertTrue(cam.poll_mode())

    def test_choices_alone_are_no_turn(self):
        cam, fake = self.make()
        cam.poll_mode()
        fake.props[0xD002]["enum"] = [40, 220]  # zooming changes the aperture list
        self.assertFalse(cam.poll_mode())

    def test_no_poll_means_none(self):
        cam, _ = self.make(polling=False)
        self.assertIsNone(cam.poll_mode())

    def test_not_while_held(self):
        cam, fake = self.make()
        cam.poll_mode()
        fake.camera_mode = 4
        cam._hold_add(1)
        self.assertFalse(cam.poll_mode())
        cam._hold_add(-1)
        with mock.patch("builtins.print"):
            self.assertTrue(cam.poll_mode())

    def test_failed_poll_logged_once(self):
        cam, fake = self.make()

        def broken():
            raise ptp.PtpError("timeout", code=-7)
        fake.changed_props = broken
        with mock.patch("builtins.print") as log:
            self.assertIsNone(cam.poll_mode())
            self.assertIsNone(cam.poll_mode())
        self.assertEqual(log.call_count, 1)
        with mock.patch("builtins.print"):
            self.assertIsNone(cam.poll_mode())
        self.assertFalse(cam.can_poll)  # third failure in a row: back to the event check and rebuild

    def test_props_poll_without_live_view(self):
        cam, fake = self.make()
        cam.live = type("L", (), {"running": False})()
        fake.camera_mode = 4
        with mock.patch.object(usb_camera.UsbCamera, "PROPS", {}):
            self.assertEqual(cam.props()["takemode"]["value"], "S")


class LiveLoop(unittest.TestCase):
    """First pass of UsbLive._loop: the poll runs; a dial event rebuilds only when there is no working poll."""

    def run_once(self, poll_result):
        calls = []

        class Cam:
            hold = stage = 0
            shooting = gone = False
            last_press = 0.0
            can_poll = poll_result is not None
            mode_changed_at = None

            def poll_mode(self):
                calls.append("poll")
                return poll_result

            def dial_turned(self):
                return True

            def reopen_if_idle(self, reason):
                calls.append("reopen")
                return True

            def preview_frame(self):
                live._run = False
                return b"jpeg"
        live = usb_camera.UsbLive(Cam())
        live._run = True
        live._loop()
        return calls, live.camera

    def test_poll_replaces_rebuild(self):
        calls, cam = self.run_once(False)
        self.assertEqual(calls, ["poll"])  # the dial event reuses this pass's poll, no rebuild
        self.assertIsNone(cam.mode_changed_at)

    def test_rebuild_without_poll(self):
        calls, cam = self.run_once(None)
        self.assertEqual(calls, ["reopen"])  # no poll: the dial event rebuilds the session as before
        self.assertIsNotNone(cam.mode_changed_at)


class FrameHeader(unittest.TestCase):
    """/live.jpg carries the last dial turn, so the page sees it with the next frame instead of the 1.5 s tick."""

    def test_mode_at_header(self):
        from tests.test_usb_zoom_drag import FrameHeaders, server
        live = usb_camera.UsbLive.__new__(usb_camera.UsbLive)
        live.cond, live.seq, live.frame, live.stamp = threading.Condition(), 4, b"\xff\xd8x\xff\xd9", (0, 0)
        saved = server.cam
        try:
            server.cam = type("C", (), {"mode_changed_at": 1795383000.25})()
            self.assertEqual(FrameHeaders.frame(None, live)["X-Mode-At"], "1795383000.25")
            server.cam = None  # Wi-Fi or not connected: empty
            self.assertEqual(FrameHeaders.frame(None, live)["X-Mode-At"], "")
        finally:
            server.cam = saved


if __name__ == "__main__":
    unittest.main()
