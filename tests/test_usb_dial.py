"""USB: a mode dial turn (event 0xC003, param 3) is told apart from AF right after a shutter command."""
import time
import unittest

from omcap import usb_camera


class FakeGp:
    GP_EVENT_TIMEOUT, GP_EVENT_FILE_ADDED, GP_EVENT_UNKNOWN = 0, 2, 1

    class GPhoto2Error(Exception):
        pass


class Dial(unittest.TestCase):
    def make(self, events):
        cam = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)  # no USB session
        import threading
        cam.gp, cam._lock, cam.hold, cam.stage = FakeGp, threading.Lock(), 0, 0
        cam._new_files, cam._pending, cam.last_press = [], [], 0.0
        queue = list(events)

        class C:
            def wait_for_event(self, ms):
                return queue.pop(0) if queue else (FakeGp.GP_EVENT_TIMEOUT, None)
        cam._c = C()
        return cam

    def test_dial_event(self):
        self.assertTrue(self.make([(1, "PTP Event c003, Param1 00000003")]).dial_turned())

    def test_other_events(self):
        self.assertFalse(self.make([(1, "PTP Event c003, Param1 00000001"), (1, "PTP Event c001")]).dial_turned())

    def test_quiet_after_shutter(self):
        cam = self.make([(1, "PTP Event c003, Param1 00000003")])
        cam.last_press = time.monotonic()
        self.assertFalse(cam.dial_turned())

    def test_not_while_shooting(self):
        cam = self.make([(1, "PTP Event c003, Param1 00000003")])
        cam.hold = 1
        self.assertFalse(cam.dial_turned())


if __name__ == "__main__":
    unittest.main()
