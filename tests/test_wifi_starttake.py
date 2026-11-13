"""Wi-Fi Take picture: starttake with the tapped point first, shutter-button route as fallback (REQ-F34)."""
import unittest

from omcap import camera
from omcap.camera import CameraError


class Cam(camera.Camera):
    def __init__(self, reply):
        self.reply, self.calls, self.pressed, self.af_point = reply, [], [], None

    def prop(self, name):
        return {"takemode": "P", "shutspeedvalue": "250", "drivemode": "normal"}.get(name, "")

    def write(self, cgi, **q):
        self.calls.append((cgi, q))
        if q.get("com") == "starttake":
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply
        return b""

    def press(self, stage):
        self.pressed.append(stage)


OK = b'<?xml version="1.0"?><response><take>ok</take><affocus>ok</affocus></response>'


class StartTake(unittest.TestCase):
    def setUp(self):
        self.sleep, camera.time.sleep = camera.time.sleep, lambda s: None

    def tearDown(self):
        camera.time.sleep = self.sleep

    def test_point_used_and_no_shutter_mode(self):
        cam = Cam(OK)
        cam.af_point = "0164x0387"
        cam.shoot()
        self.assertEqual(cam.calls[0], ("exec_takemotion", {"com": "starttake", "point": "0164x0387"}))
        self.assertEqual(cam.calls[1][1], {"com": "stoptake"})
        self.assertEqual(cam.pressed, [])

    def test_without_tap_camera_target(self):
        cam = Cam(OK)
        cam.shoot()
        self.assertNotIn("point", cam.calls[0][1])

    def test_refused_falls_back(self):
        cam = Cam(CameraError("HTTP Error 520", code=520))
        cam.shoot()
        self.assertEqual(cam.pressed, [1, 2, 0])



class Guards(unittest.TestCase):
    def setUp(self):
        self.sleep, camera.time.sleep = camera.time.sleep, lambda s: None

    def tearDown(self):
        camera.time.sleep = self.sleep

    def make(self, reply, props):
        cam = Cam(reply)
        cam.prop = lambda p: props.get(p, "")
        return cam

    def test_long_exposure_selftimer_movie_use_old_route(self):
        for props in ({"takemode": "M", "shutspeedvalue": "livebulb"}, {"takemode": "M", "shutspeedvalue": '2"'},
                      {"takemode": "M", "shutspeedvalue": "2"}, {"takemode": "P", "drivemode": "selftimer"},
                      {"takemode": "movie"}):
            cam = self.make(OK, props)
            cam.shoot()
            self.assertEqual(cam.pressed, [1, 2, 0], props)
            self.assertTrue(cam.mode_switched)

    def test_normal_shot_keeps_live_view(self):
        cam = self.make(OK, {"takemode": "P", "shutspeedvalue": "250", "drivemode": "normal"})
        cam.shoot()
        self.assertEqual(cam.pressed, [])
        self.assertFalse(cam.mode_switched)

    def test_timeout_raises_no_second_shot(self):
        cam = self.make(CameraError("timed out"), {"takemode": "P", "shutspeedvalue": "250"})
        with self.assertRaises(CameraError):
            cam.shoot()
        self.assertEqual(cam.pressed, [])
        self.assertEqual(cam.calls[-1][1], {"com": "stoptake"})

    def test_not_ok_falls_back(self):
        cam = self.make(b"<response><take>ng</take></response>", {"takemode": "P", "shutspeedvalue": "250"})
        cam.shoot()
        self.assertEqual(cam.pressed, [1, 2, 0])

    def test_size_change_clears_point(self):
        cam = camera.Camera.__new__(camera.Camera)
        cam.af_point, cam.lvqty, cam._touch = "0164x0387", "0800x0600", None
        cam.write = lambda *a, **k: b""
        cam.set_mode("rec", "1024x0768")
        self.assertIsNone(cam.af_point)


if __name__ == "__main__":
    unittest.main()
