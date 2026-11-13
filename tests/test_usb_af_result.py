"""AF result event 0xC003 of the E-M1 (mapped on the camera 2026-11-13)."""
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


if __name__ == "__main__":
    unittest.main()
