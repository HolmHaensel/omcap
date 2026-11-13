"""AF result event 0xC003 of the E-M1 (mapped on the camera 2026-11-13)."""
import threading
import time
import unittest

from omcap import usb_camera


class AfResult(unittest.TestCase):
    def test_in_focus_with_position(self):
        r = usb_camera.parse_af_result("PTP Event c003, Param1 00000001, Param2 02e301d6, Param3 00630043")
        self.assertEqual(r, (True, {"x": 739, "y": 470}))

    def test_no_focus(self):
        r = usb_camera.parse_af_result("PTP Event c003, Param1 00000002, Param2 00000000, Param3 00000000")
        self.assertEqual(r, (False, None))

    def test_libgphoto2_param1_only(self):
        self.assertEqual(usb_camera.parse_af_result("PTP Event c003, Param1 00000001"), (True, None))

    def test_dial_and_after_shot_are_no_af_result(self):
        self.assertIsNone(usb_camera.parse_af_result("PTP Event c003, Param1 00000003"))
        self.assertIsNone(usb_camera.parse_af_result("PTP Event c001, Param1 00000001"))



class EarlyStop(unittest.TestCase):
    """shoot() waits for files; a "no focus" event ends the wait after ~1 s in S-AF only."""
    NO_FOCUS = (1, "PTP Event c003, Param1 00000002, Param2 00000000, Param3 00000000")

    def make(self, saf):
        class Gp:
            GP_EVENT_TIMEOUT, GP_EVENT_FILE_ADDED, GP_EVENT_UNKNOWN = 0, 2, 1
        cam = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
        cam.gp, cam._lock, cam._new_files, cam._pending, cam._event_log = Gp, threading.Lock(), [], [], []
        cam.saf_shot, cam.af_failed = saf, False
        queue = [self.NO_FOCUS]
        cam._call = lambda fn, *a: queue.pop(0) if queue else (Gp.GP_EVENT_TIMEOUT, None)
        cam._c = type("C", (), {"wait_for_event": None})()
        return cam

    def test_saf_stops_after_about_a_second(self):
        cam = self.make(saf=True)
        t0 = time.monotonic()
        cam._events(5.0, "quiet")
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertTrue(cam.af_failed)

    def test_caf_keeps_waiting(self):
        cam = self.make(saf=False)
        t0 = time.monotonic()
        cam._events(1.5, "quiet")
        self.assertGreaterEqual(time.monotonic() - t0, 1.5)
        self.assertFalse(cam.af_failed)


if __name__ == "__main__":
    unittest.main()
