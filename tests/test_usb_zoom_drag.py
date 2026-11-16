"""USB zoom drag, click focus and ratio handling (REQ-F54): offline, no camera."""
import os
import unittest

from omcap import ptp, server, usb_camera
from omcap.camera import CameraError, WriteBlocked
from tests.test_usb_loupe import make


class DragMoves(unittest.TestCase):
    def test_step_size_at_x5_is_87_px(self):
        step = ptp.LOUPE_STEP_NORMAL_PX * 5
        self.assertAlmostEqual(step, 87)
        self.assertEqual(ptp.loupe_drag_moves(step - 1, 0, 5)[0], [])
        self.assertEqual(ptp.loupe_drag_moves(step + 1, 0, 5)[0], ["left"])

    def test_grab_the_picture_directions(self):
        # dragging the picture right shows what is left: the frame moves left
        self.assertEqual(ptp.loupe_drag_moves(100, 0, 5)[0], ["left"])
        self.assertEqual(ptp.loupe_drag_moves(-100, 0, 5)[0], ["right"])
        self.assertEqual(ptp.loupe_drag_moves(0, 100, 5)[0], ["up"])
        self.assertEqual(ptp.loupe_drag_moves(0, -100, 5)[0], ["down"])

    def test_step_grows_with_ratio(self):
        self.assertEqual(len(ptp.loupe_drag_moves(500, 0, 3)[0]), 9)
        self.assertEqual(len(ptp.loupe_drag_moves(500, 0, 14)[0]), 2)

    def test_remainder_accumulates(self):
        rem, total = (0.0, 0.0), 0
        for _ in range(10):
            moves, rem = ptp.loupe_drag_moves(30, -10, 5, rem)
            total += len(moves)
        self.assertEqual(total, 3 + 1)  # 300 px = 3 steps, 100 px = 1 step
        self.assertLess(abs(rem[0]), 87)

    def test_capped_per_call(self):
        self.assertEqual(len(ptp.loupe_drag_moves(100000, 0, 3)[0]), ptp.LOUPE_MAX_STEPS)

    def test_both_axes(self):
        self.assertEqual(ptp.loupe_drag_moves(100, -100, 5)[0], ["left", "down"])


class Drag(unittest.TestCase):
    def test_sends_only_step_opcodes(self):
        cam = make()
        cam.loupe(True, 5)
        cam._c.writes.clear()
        self.assertEqual(cam.loupe_drag(180, 0), 2)
        self.assertEqual(cam._c.writes, [("opcode", "0x9488,0x3")] * 2)  # never 0x9483

    def test_remainder_kept_between_calls(self):
        cam = make()
        cam.loupe(True, 5)
        cam._c.writes.clear()
        self.assertEqual(cam.loupe_drag(60, 0), 0)
        self.assertEqual(cam.loupe_drag(60, 0), 1)

    def test_step_follows_chosen_ratio(self):
        cam = make()
        cam.loupe(True, 14)
        self.assertEqual(cam.loupe_drag(250, 0), 1)  # 243.6 px per step at x14

    def test_needs_zoom_on_and_write(self):
        cam = make()
        with self.assertRaises(CameraError):
            cam.loupe_drag(100, 0)
        with self.assertRaises(WriteBlocked):
            make(allow_write=False).loupe_drag(100, 0)
        self.assertEqual(cam._c.writes, [])


class FocusInZoom(unittest.TestCase):
    def setUp(self):
        self.cam = make()
        c = self.cam
        c.gone, c.stage, c.last_press, c._event_log = False, 0, 0.0, []
        c._hold_add = lambda n: None
        c._events = lambda *a, **k: False  # the camera sends no AF result in this test
        c.af_mode = usb_camera.AF_SINGLE

    def presses(self):
        return [v for n, v in self.cam._c.writes if n == "opcode"]

    def test_half_press_then_release_without_shot(self):
        self.cam.loupe_on = True
        self.cam.focus()
        self.assertEqual(self.presses(), ["0x9481,0x1", "0x9481,0x5"])

    def test_normal_view_still_releases_with_6(self):
        self.cam.focus()
        self.assertEqual(self.presses(), ["0x9481,0x1", "0x9481,0x6"])


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.saved = (server.cam, server.conn_type, server.ensure_idle, server.live)
        server.ensure_idle = lambda: None
        server.live = type("Live", (), {"running": True})()

    def tearDown(self):
        server.cam, server.conn_type, server.ensure_idle, server.live = self.saved

    def act(self, b):
        return server.Handler._action(server.Handler.__new__(server.Handler), "/api/loupe", b)

    def test_drag_over_usb(self):
        server.cam, server.conn_type = make(), "usb"
        self.act({"on": True, "ratio": 3})
        server.cam._c.writes.clear()
        self.assertEqual(self.act({"drag": {"dx": 0, "dy": 110}}), {"loupe": True})
        self.assertEqual(server.cam._c.writes, [("opcode", "0x9488,0x1")] * 2)

    def test_wifi_unchanged(self):
        server.cam, server.conn_type = object(), "wifi"
        with self.assertRaises(CameraError):
            self.act({"drag": {"dx": 10, "dy": 0}})
        self.assertNotIn("loupe", server.WIFI_FEATURES)

    def test_ratio_remembered(self):
        cam = make()
        cam.loupe(True, 10)
        self.assertEqual(cam.loupe_ratio, 10)


class Page(unittest.TestCase):
    """The page keeps the ratio steps and both zoom controls (Wi-Fi keeps 1x/2x/4x)."""

    def test_markup(self):
        path = os.path.join(os.path.dirname(__file__), "..", "omcap", "web", "index.html")
        html = open(path, encoding="utf-8").read()
        self.assertIn("LOUPE_STEPS=[1,3,5,7,10,14]", html)
        for z in (1, 2, 4):
            self.assertIn('data-z="%d"' % z, html)
        for z in (1, 3, 5, 7, 10, 14):
            self.assertIn('data-lz="%d"' % z, html)
        self.assertNotIn("loupeBtn", html)


if __name__ == "__main__":
    unittest.main()
