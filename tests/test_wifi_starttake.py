"""Wi-Fi Take picture: starttake with the tapped point first, shutter-button route as fallback (REQ-F34)."""
import unittest

from omcap import camera
from omcap.camera import CameraError


class Cam(camera.Camera):
    def __init__(self, reply):
        self.reply, self.calls, self.pressed, self.af_point = reply, [], [], None

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


if __name__ == "__main__":
    unittest.main()
