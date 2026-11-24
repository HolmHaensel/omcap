"""AF result event 0xC003 of the E-M1 (mapped on the camera 2026-11-13)."""
import threading
import time
import unittest
from unittest import mock

from omcap import usb_camera


class AfResult(unittest.TestCase):
    def test_in_focus_with_position(self):
        r = usb_camera.parse_af_result("PTP Event c003, Param1 00000001, Param2 02e301d6, Param3 00630043")
        self.assertEqual(r, (True, {"x": 1028, "y": 648}))  # event space ~920x696 -> 1280x960

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
        cam._events(1.2, "quiet")  # longer than the 1 s early stop of S-AF
        self.assertGreaterEqual(time.monotonic() - t0, 1.2)
        self.assertFalse(cam.af_failed)


class HeldHalfPressPosition(unittest.TestCase):
    """USB test 2026-11-22: a held "Press halfway" kept the old d05d/d05e (0x1014 is not live in a session)."""

    def cam(self, events):
        c = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
        c.last_af, c._event_log = {"x": 832, "y": 592}, []
        c._events = lambda t, *a: c._event_log.extend(events) or True
        c._value = mock.Mock(return_value="0")
        return c

    def test_event_position_wins(self):
        c = self.cam(["PTP Event c003, Param1 00000001, Param2 01cc015c, Param3 0"])  # field 41: 460/348
        c._read_focus_position()
        self.assertEqual(c.last_af, {"x": 640, "y": 480})  # the centre of 1280x960
        c._value.assert_not_called()

    def test_no_focus_event(self):
        c = self.cam(["PTP Event c003, Param1 00000002, Param2 00000000, Param3 0"])
        c._read_focus_position()
        self.assertEqual(c.last_af, {"x": 0, "y": 0})
        self.assertIs(c.focus_ok, False)

    def test_event_without_position_reads_properties(self):
        c = self.cam(["PTP Event c003, Param1 00000001"])
        with mock.patch.object(usb_camera, "FOCUS_POSITION_WAIT", 0.05):
            c._read_focus_position()
        c._value.assert_called()


class MeasuredGrid(unittest.TestCase):
    def test_fields_1_41_81_land_on_their_grid_fields(self):
        # camera reading 2026-11-22: field 1 = 89/105, 41 = 460/348, 81 = 832/592 in the event space
        cam = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
        a = dict(cam.AF_AREA)
        for field, raw in ((1, (89, 105)), (41, (460, 348)), (81, (832, 592))):
            ok, pos = usb_camera.parse_af_result("PTP Event c003, Param1 00000001, Param2 %04x%04x" % raw)
            row, col = divmod(field - 1, 9)
            cx = a["x0"] + (col + .5) / 9 * (a["x1"] - a["x0"])
            cy = a["y0"] + (row + .5) / 9 * (a["y1"] - a["y0"])
            self.assertLess(abs(pos["x"] - cx), 8, field)
            self.assertLess(abs(pos["y"] - cy), 8, field)


class WifiOuterFields(unittest.TestCase):
    """Over Wi-Fi the camera also takes taps outside its touch frame (~47-60 %), so every field of the real grid (~91 x 79 %) is used as tapped."""

    def setUp(self):
        from omcap import server
        self.server = server
        saved = (server.cam, server.conn_type, dict(server.state))
        self.addCleanup(lambda: (setattr(server, "cam", saved[0]), setattr(server, "conn_type", saved[1]),
                                 server.state.update(saved[2])))
        server.conn_type = "wifi"
        server.cam = mock.Mock(touch_frame=mock.Mock(return_value={
            "x": 135, "y": 100, "w": 527, "h": 397, "base_w": 797, "base_h": 597}),
            af_focus=mock.Mock(return_value={"ok": True, "x": None, "y": None}))

    def test_outer_fields_focus_where_tapped(self):
        a = self.server.af_area()["area"]
        for field in (1, 9, 37, 73, 81):
            self.server.set_af_area(None, field)
            fx, fy = self.server.cam.af_focus.call_args[0]
            row, col = divmod(field - 1, 9)
            self.assertAlmostEqual(fx * a["w"], a["x0"] + (col + .5) / 9 * (a["x1"] - a["x0"]), places=6)
            self.assertAlmostEqual(fy * a["h"], a["y0"] + (row + .5) / 9 * (a["y1"] - a["y0"]), places=6)
            self.assertEqual(self.server.state["wifi_field"], field)

    def test_centre_field_stays(self):
        self.server.set_af_area(None, 41)
        self.assertEqual(self.server.state["wifi_field"], 41)


if __name__ == "__main__":
    unittest.main()
