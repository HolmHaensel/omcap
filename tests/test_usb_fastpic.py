"""Fast picture after a shot over USB (REQ-F56): PTP 0x9485 OMD_GetImage, shown before the card lists the file."""
import unittest

from omcap import ptp, ptp_gphoto as pg, server, usb_camera
from test_ptp_gphoto import FakePtp, camera

JPEG = b"\xff\xd8\xff\xe0fakejpeg\xff\xd9"
D = "/store_00010001/DCIM/100OLYMP/"


class Scripted(ptp.PtpCamera):
    """PtpCamera whose transact() plays a list of answers (bytes, or an exception to raise)."""

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
    def test_jpeg_returned(self):
        c = Scripted([JPEG])
        self.assertEqual(c.get_image(), JPEG)
        self.assertEqual(c.sent, [(0x9485, (1,))])

    def test_busy_then_jpeg(self):
        c = Scripted([ptp.PtpError("busy", code=ptp.RC_BUSY), b"", JPEG])
        self.assertEqual(c.get_image(), JPEG)
        self.assertEqual(len(c.sent), 3)

    def test_empty_gives_up_after_wait(self):
        c = Scripted([b""] * 50)
        self.assertEqual(c.get_image(wait=0.25), b"")
        self.assertLess(len(c.sent), 10)

    def test_refusal_is_not_retried(self):
        c = Scripted([ptp.PtpError("no", code=0x2005)])
        self.assertEqual(c.get_image(), b"")
        self.assertEqual(len(c.sent), 1)

    def test_not_a_jpeg_ignored(self):
        self.assertEqual(Scripted([b"junk"] * 20).get_image(wait=0.2), b"")


class FastPtp(FakePtp):
    def __init__(self, answer=JPEG):
        super().__init__()
        self.answer = answer

    def get_image(self):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def cam_with(fake):
    import threading
    cam = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
    cam.gp, cam._c, cam._lock, cam.allow_write = pg, camera(fake), threading.Lock(), True
    cam.gone = False
    got = []
    cam.on_fast_jpeg = got.append
    return cam, got


class Camera(unittest.TestCase):
    def test_delivers_once(self):
        cam, got = cam_with(FastPtp())
        cam._fast_picture()
        self.assertEqual(got, [JPEG])

    def test_empty_and_error_fall_back_silently(self):
        for answer in (b"", ptp.PtpError("x", code=0x2005)):
            cam, got = cam_with(FastPtp(answer))
            cam._fast_picture()
            self.assertEqual(got, [])

    def test_libgphoto2_layer_skipped(self):
        cam, got = cam_with(FastPtp())

        class Plain:  # no omd_get_image, like a libgphoto2 camera object
            pass
        cam._c = Plain()
        cam._fast_picture()
        self.assertEqual(got, [])

    def test_no_callback_no_request(self):
        fake = FastPtp()
        cam, got = cam_with(fake)
        cam.on_fast_jpeg = None
        fake.get_image = lambda: self.fail("must not ask")
        cam._fast_picture()


class Server(unittest.TestCase):
    def setUp(self):
        self.old = dict(server.state)
        server.state.update(last_shot=None, last_shot_jpeg=None, fast_n=0)

    def tearDown(self):
        server.state.clear()
        server.state.update(self.old)

    def test_fast_then_card_path_takes_over(self):
        server.remember_fast_shot(JPEG)
        self.assertEqual((server.state["last_shot_jpeg"], server.state["last_shot"], server.state["fast_n"]),
                         (JPEG, None, 1))
        server.remember_shot([D + "P1010002.ORF"])  # RAW only: nothing to take over
        self.assertEqual(server.state["last_shot_jpeg"], JPEG)
        server.remember_shot([D + "P1010002.JPG", D + "P1010002.ORF"])
        self.assertIsNone(server.state["last_shot_jpeg"])
        self.assertEqual(server.state["last_shot"], D + "P1010002.JPG")

    def test_next_shot_replaces_and_old_path_dropped(self):
        server.remember_shot([D + "P1010001.JPG"])
        server.remember_fast_shot(JPEG)
        self.assertIsNone(server.state["last_shot"])
        server.remember_fast_shot(JPEG + b"2")
        self.assertEqual((server.state["last_shot_jpeg"], server.state["fast_n"]), (JPEG + b"2", 2))

    def test_never_saved(self):
        saved = []
        old, server.save_capture = server.save_capture, lambda *a, **k: saved.append(a)
        try:
            server.remember_fast_shot(JPEG)
        finally:
            server.save_capture = old
        self.assertEqual(saved, [])

    def test_wifi_state_unaffected(self):
        old = server.conn_type
        server.conn_type = "wifi"
        try:
            server.state["last_shot_jpeg"] = JPEG
            server.state["fast_n"] = 3
            self.assertNotIn("usb", server.conn_type)
            # public_state reports a fast picture only over USB
            self.assertEqual(server.state["fast_n"] if server.conn_type == "usb" else 0, 0)
        finally:
            server.conn_type = old


if __name__ == "__main__":
    unittest.main()
