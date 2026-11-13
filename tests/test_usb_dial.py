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
        cam.gp, cam._lock, cam._hold, cam._hold_lock, cam.stage = FakeGp, threading.Lock(), 0, threading.Lock(), 0
        cam._new_files, cam._pending, cam._event_log, cam.last_jpg, cam.last_press = [], [], [], None, 0.0
        queue = list(events)

        class C:
            def wait_for_event(self, ms):
                return queue.pop(0) if queue else (FakeGp.GP_EVENT_TIMEOUT, None)
        cam._c = C()
        return cam

    def take(self, start):
        from unittest import mock
        cam = self.make([])
        cam.allow_write = True
        cam._is_bulb = lambda: False
        cam._events = lambda *a: False
        with mock.patch.object(cam, "_shutter"):
            if start:
                cam.take_start()
                cam._take_t0 -= 5  # a 5 s exposure
            cam.take_stop()
        return cam

    def test_quiet_after_exposure(self):
        cam = self.take(start=True)
        self.assertGreater(cam.last_press, time.monotonic() + 3)  # noise reduction ~ exposure time
        self.assertFalse(cam.shooting)
        self.assertIsNone(cam._take_t0)

    def test_stop_without_exposure_keeps_dial_check(self):
        cam = self.take(start=False)  # e.g. a second Stop click
        self.assertLessEqual(cam.last_press, time.monotonic())

    def test_dial_event(self):
        self.assertTrue(self.make([(1, "PTP Event c003, Param1 00000003")]).dial_turned())

    def test_other_events(self):
        self.assertFalse(self.make([(1, "PTP Event c003, Param1 00000001"), (1, "PTP Event c001")]).dial_turned())

    def test_quiet_after_shutter(self):
        cam = self.make([(1, "PTP Event c003, Param1 00000003")])
        cam.last_press = time.monotonic()
        self.assertFalse(cam.dial_turned())

    def test_reason_names_time_since_last_command(self):
        cam = self.make([(1, "PTP Event c003, Param1 00000003")])
        cam.last_press = time.monotonic() - 10
        self.assertTrue(cam.dial_turned())
        self.assertRegex(cam.dial_reason, r"^1\d\.\d s after the last command$")

    def test_camera_body_shot_goes_to_card_list_only(self):
        class F:
            folder, name = "/store_00010001/DCIM/111OLYMP", "P1.JPG"
        cam = self.make([(FakeGp.GP_EVENT_FILE_ADDED, F())])
        self.assertFalse(cam.dial_turned())
        self.assertEqual(cam._new_files, [])
        self.assertEqual(cam._pending, ["/store_00010001/DCIM/111OLYMP/P1.JPG"])

    def test_not_while_shooting(self):
        cam = self.make([(1, "PTP Event c003, Param1 00000003")])
        cam._hold_add(1)
        self.assertFalse(cam.dial_turned())


if __name__ == "__main__":
    unittest.main()
