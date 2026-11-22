"""REQ-F69: Focus Stacking state read live; a stacking shot with one frame ends early and says so."""
import time
import unittest
from unittest import mock

from omcap import usb_camera


def cam(live=None, desc=None):
    c = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
    c._live_int = mock.Mock(side_effect=lambda code: (live or {})[code])
    c._value = mock.Mock(side_effect=lambda code: (desc or {})[code])
    return c


class LiveState(unittest.TestCase):
    def test_live_value_wins_over_the_session_start(self):
        c = cam(live={"d0a6": 1, "d0cb": 2, "d0ce": 2}, desc={"d0a6": "1", "d0cb": "1", "d0ce": "1"})
        self.assertFalse(c._stacking_on())  # switched off in the camera menu after the connect

    def test_live_on(self):
        self.assertTrue(cam(live={"d0a6": 1, "d0cb": 1, "d0ce": 1})._stacking_on())

    def test_falls_back_to_the_descriptor(self):
        c = cam(desc={"d0a6": "1", "d0cb": "1", "d0ce": "1"})
        c._live_int = mock.Mock(side_effect=usb_camera.CameraError("libgphoto2"))
        self.assertTrue(c._stacking_on())


class BracketingMainSwitch(unittest.TestCase):
    def test_bracketing_off_means_no_stacking(self):
        # USB test 2026-11-22: Focus BKT and stacking on, Bracketing Off -> the camera took one picture
        self.assertFalse(cam(live={"d0a6": 2, "d0cb": 1, "d0ce": 1})._stacking_on())


class Switch(unittest.TestCase):
    """The app switch sets Bracketing d0a6 with Focus BKT and restores what was there before."""

    def cam(self):
        state = {"d0a6": "2", "d020": "1", "d0cb": "2", "d0ce": "2", "shutterspeed": "1/60"}
        c = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
        c._need_write = lambda: None
        c._value = lambda code: state[code]
        c._live_int = lambda code: int(state[code])
        c._set = lambda code, v: state.__setitem__(code, str(v))
        c.refresh = lambda: None
        return c, state

    def test_double_on_still_restores_bracketing_off(self):
        c, state = self.cam()
        c._set_focus_stacking(True)
        c._set_focus_stacking(True)  # a second On (retry, stale page) must not forget the old state
        self.assertEqual((state["d0a6"], state["d020"], state["d0ce"]), ("1", "3", "1"))
        c._set_focus_stacking(False)
        self.assertEqual((state["d0a6"], state["d020"], state["d0cb"], state["d0ce"]), ("2", "1", "2", "2"))

    def test_failed_switch_leaves_bracketing_as_it_was(self):
        c, state = self.cam()
        set_ = c._set
        c._set = lambda code, v: (_ for _ in ()).throw(usb_camera.CameraError("no")) if code == "d0cb" and v == 1 \
            else set_(code, v)
        with self.assertRaises(usb_camera.CameraError):
            c._set_focus_stacking(True)
        self.assertEqual((state["d0a6"], state["d020"]), ("2", "1"))


class MergingPause(unittest.TestCase):
    def test_no_answer_while_merging_is_waited_out(self):
        c = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
        calls = []

        def events(seconds):
            calls.append(seconds)
            if len(calls) < 3:
                raise usb_camera.CameraError("USB: PTP: no answer")
        c._events = events
        marks = []
        with mock.patch.object(usb_camera.time, "sleep"):
            c.gone = False
            c._stack_events(time.monotonic() + 0.2, marks, time.monotonic())
        self.assertGreaterEqual(len(calls), 3)
        self.assertEqual([m[0] for m in marks], ["camera busy merging"])


if __name__ == "__main__":
    unittest.main()
