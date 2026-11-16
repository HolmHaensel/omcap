"""USB Zoom AF (REQ-F53): the camera's magnified live view via d0cf, 0x9483, d04b and 0x9488 (no camera)."""
import threading
import unittest

from omcap import ptp, server, usb_camera
from omcap.camera import CameraError, WriteBlocked


class FakeGp:
    class GPhoto2Error(Exception):
        pass


class Widget:
    def __init__(self):
        self.value = None

    def set_value(self, v):
        self.value = v


class Cam:
    """Records every write as (name, value) in order, like the gphoto2-style widgets of both backends."""

    def __init__(self, fail=False):
        self.writes, self.fail = [], fail

    def get_single_config(self, name):
        if self.fail:
            raise FakeGp.GPhoto2Error("gone")
        return Widget()

    def set_single_config(self, name, w):
        self.writes.append((name, w.value))


def make(allow_write=True, fail=False):
    cam = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)  # no USB session
    cam.gp, cam._lock, cam._c, cam.allow_write = FakeGp, threading.Lock(), Cam(fail), allow_write
    return cam


class Point(unittest.TestCase):
    def test_packed_as_in_the_trace(self):
        self.assertEqual(ptp.loupe_point(512, 384), 0x01800200)  # centre, OM Capture 2026-11-16
        self.assertEqual(ptp.loupe_point(510, 390), 0x018601FE)

    def test_clamped_to_the_grid(self):
        self.assertEqual(ptp.loupe_point(-5, 9999), (767 << 16) | 0)
        self.assertEqual(ptp.loupe_point(1024, 768), (767 << 16) | 1023)


class Loupe(unittest.TestCase):
    def test_on_order_as_om_capture(self):
        cam = make()
        cam.loupe(True, 5, 0.5, 0.5)
        self.assertEqual(cam._c.writes, [("d0cf", "2"), ("opcode", "0x9483,0x1800200"), ("d04b", "1")])
        self.assertTrue(cam.loupe_on)

    def test_new_ratio_keeps_the_frame(self):
        cam = make()
        cam.loupe(True, 14)
        self.assertEqual(cam._c.writes, [("d0cf", "5"), ("d04b", "1")])

    def test_off(self):
        cam = make()
        cam.loupe_on = True
        cam.loupe(False)
        self.assertEqual(cam._c.writes, [("d04b", "2")])
        self.assertFalse(cam.loupe_on)

    def test_move(self):
        cam = make()
        for d in ("up", "down", "left", "right"):
            cam.loupe_move(d)
        self.assertEqual([v for _, v in cam._c.writes], ["0x9488,0x1", "0x9488,0x2", "0x9488,0x3", "0x9488,0x4"])

    def test_bad_input_writes_nothing(self):
        cam = make()
        for call in (lambda: cam.loupe(True, 4), lambda: cam.loupe(True, 5, 1.5, 0.5),
                     lambda: cam.loupe_move("forward")):
            with self.assertRaises(CameraError):
                call()
        self.assertNotIn(("d04b", "1"), cam._c.writes)

    def test_needs_write_permission(self):
        cam = make(allow_write=False)
        with self.assertRaises(WriteBlocked):
            cam.loupe(True, 5, 0.5, 0.5)
        with self.assertRaises(WriteBlocked):
            cam.loupe_move("up")
        self.assertEqual(cam._c.writes, [])


class Cleanup(unittest.TestCase):
    """A magnified view outlives a session (seen 2026-11-16): end it at live view start and stop."""

    def test_live_view_start_and_stop_switch_off(self):
        cam = make()
        cam.loupe_on = True
        cam.start_liveview(0)
        cam.stop_liveview()
        self.assertEqual(cam._c.writes, [("d04b", "2"), ("d04b", "2")])
        self.assertFalse(cam.loupe_on)

    def test_read_only_never_writes(self):
        cam = make(allow_write=False)
        cam.stop_liveview()
        self.assertEqual(cam._c.writes, [])

    def test_errors_are_quiet(self):
        cam = make(fail=True)
        cam.loupe_on = True
        cam.stop_liveview()  # body without d04b or camera gone
        self.assertFalse(cam.loupe_on)

    def test_gone_camera_is_not_touched(self):
        cam = make()
        cam.gone, cam.loupe_on = True, True
        cam.stop_liveview()
        self.assertEqual(cam._c.writes, [])
        self.assertFalse(cam.loupe_on)


def act(path, b):
    return server.Handler._action(server.Handler.__new__(server.Handler), path, b)


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.saved = (server.cam, server.conn_type, server.ensure_idle, server.live)
        server.ensure_idle = lambda: None
        server.live = type("Live", (), {"running": True})()

    def tearDown(self):
        server.cam, server.conn_type, server.ensure_idle, server.live = self.saved

    def test_needs_live_view(self):
        server.cam, server.conn_type = make(), "usb"
        server.live.running = False
        with self.assertRaises(CameraError):
            act("/api/loupe", {"on": True})
        self.assertEqual(server.cam._c.writes, [])

    def test_usb_only(self):
        self.assertIn("loupe", usb_camera.FEATURES)
        self.assertNotIn("loupe", server.WIFI_FEATURES)
        server.cam, server.conn_type = object(), "wifi"
        with self.assertRaises(CameraError):
            act("/api/loupe", {"on": True})

    def test_usb_on_and_move(self):
        server.cam, server.conn_type = make(), "usb"
        self.assertEqual(act("/api/loupe", {"on": True, "ratio": 7, "x": 0.25, "y": 0.75}), {"loupe": True, "rev": 1})
        self.assertEqual(server.cam._c.writes[1], ("opcode", "0x9483,0x%x" % ((576 << 16) | 256)))
        self.assertEqual(act("/api/loupe", {"move": "left"}), {"loupe": True, "rev": 1})
        self.assertEqual(act("/api/loupe", {"on": False}), {"loupe": False, "rev": 2})


if __name__ == "__main__":
    unittest.main()
