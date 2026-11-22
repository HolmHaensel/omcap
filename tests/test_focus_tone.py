"""Focus tone (REQ-F59) and silent half press over Wi-Fi: page markup and server logic, no camera."""
import os
import unittest

from omcap import camera, server, usb_camera

WEB = os.path.join(os.path.dirname(__file__), "..", "omcap", "web", "index.html")


class FakeCam:
    def __init__(self, full):
        self.stage, self.released_full, self._full, self.pressed = 1, False, full, []

    def press(self, stage):
        self.pressed.append(stage)
        self.released_full = self._full
        self.stage = 0


class Page(unittest.TestCase):
    def setUp(self):
        self.html = open(WEB, encoding="utf-8").read()

    def test_switch_gated_and_remembered(self):
        self.assertIn('data-feat="focus_tone"', self.html)
        self.assertIn('id="focusTone"', self.html)
        self.assertIn("'lvlSound','focusTone']", self.html)  # saved with the other switches
        self.assertIn('"lv.focusTone": "Focus tone"', self.html)
        self.assertIn('"lv.focusToneHint"', self.html)

    def test_tone_after_tap_focus_only(self):
        self.assertIn("if(f) focusTone(!!hit);", self.html)
        self.assertIn("features.has('focus_tone')", self.html)
        self.assertEqual(self.html.count("focusTone("), 2)  # definition and the one call in setAf

    def test_wifi_only(self):
        self.assertIn("focus_tone", server.WIFI_FEATURES)
        self.assertNotIn("focus_tone", usb_camera.FEATURES)


class HalfPress(unittest.TestCase):
    def setUp(self):
        self.saved = (server.cam, server.conn_type, dict(server.state), server.pull_new)
        self.pulled = []
        server.pull_new = lambda seen: self.pulled.append(seen)
        server.conn_type = "wifi"
        server.state["seen"] = {"a"}
        server.state["resume_live"] = False

    def tearDown(self):
        server.cam, server.conn_type, st, server.pull_new = self.saved
        server.state.clear()
        server.state.update(st)

    def test_half_press_without_shot_does_not_pull(self):
        server.cam = FakeCam(full=False)
        server.Handler._shutter(None, 0)
        self.assertEqual(self.pulled, [])
        self.assertIsNone(server.state["seen"])

    def test_real_shot_pulls(self):
        server.cam = FakeCam(full=True)
        server.Handler._shutter(None, 0)
        self.assertEqual(self.pulled, [{"a"}])

    def test_release_flag_in_camera(self):
        c = camera.Camera.__new__(camera.Camera)
        c.stage, c.released_full = 1, True
        c.shutter = lambda step: None
        c.set_mode = lambda m: None
        c._release()
        self.assertFalse(c.released_full)
        c.stage = 2
        camera.time.sleep, old = lambda s: None, camera.time.sleep
        try:
            c._release()
        finally:
            camera.time.sleep = old
        self.assertTrue(c.released_full)


if __name__ == "__main__":
    unittest.main()


class HalfHeld(unittest.TestCase):
    def test_tap_while_halfway_is_held_is_refused_over_wifi(self):
        # Wi-Fi test 2026-11-22: a tap while Press halfway was held answered HTTP 520 (camera in mode shutter)
        with open(os.path.join(os.path.dirname(__file__), "..", "omcap", "web", "index.html"), encoding="utf-8") as f:
            h = f.read()
        body = h[h.index("async function setAf(b){"):h.index("async function setAf(b){") + 400]
        self.assertIn("!isUsb&&st.stage>=1", body)
        self.assertIn('"msg.halfHeld"', h)


class HalfPaused(unittest.TestCase):
    def test_paused_text_instead_of_no_signal(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "omcap", "web", "index.html"), encoding="utf-8") as f:
            h = f.read()
        self.assertIn("paused=!isUsb&&st.live&&st.stage>=1", h)
        self.assertIn("stale=st.live&&st.lv_age>3&&!paused", h)
        self.assertIn('"lv.halfPaused"', h)
