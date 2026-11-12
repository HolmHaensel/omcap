"""USB live view size (REQ-F36): only offered when libgphoto2 has the widget "liveviewsize"."""
import threading
import unittest

from omcap import usb_camera
from omcap.camera import CameraError, WriteBlocked


class FakeGp:
    class GPhoto2Error(Exception):
        pass


class Widget:
    def __init__(self):
        self.value = "1024x768"

    def set_value(self, v):
        self.value = v


class Cam:
    def __init__(self):
        self.w = Widget()

    def get_single_config(self, name):
        return self.w

    def set_single_config(self, name, w):
        pass


def make(allow_write=True, lvsize=True):
    cam = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)  # no USB session
    cam.gp, cam._lock, cam._c, cam.allow_write = FakeGp, threading.Lock(), Cam(), allow_write
    cam.features = usb_camera.FEATURES + (["lvsize"] if lvsize else [])
    cam.lvqty = None
    return cam


class LvSize(unittest.TestCase):
    def test_set_size(self):
        cam = make()
        cam.set_mode("rec", "1280x0960")
        self.assertEqual(cam._c.w.value, "1280x960")
        self.assertEqual(cam.lvqty, "1280x0960")

    def test_old_library_ignores_size(self):
        cam = make(lvsize=False)
        cam.set_mode("rec", "1280x0960")
        self.assertEqual(cam._c.w.value, "1024x768")
        self.assertIsNone(cam.lvqty)

    def test_needs_write_and_valid_size(self):
        with self.assertRaises(WriteBlocked):
            make(allow_write=False).set_mode("rec", "1280x0960")
        with self.assertRaises(CameraError):
            make().set_mode("rec", "big")


if __name__ == "__main__":
    unittest.main()
