"""Card list saved on the computer per connection type (instant start, REQ-F27)."""
import os
import tempfile
import unittest

from omcap import server


class CardCache(unittest.TestCase):
    def test_roundtrip_per_connection(self):
        old = server.PREVIEW_CACHE
        with tempfile.TemporaryDirectory() as d:
            server.PREVIEW_CACHE = os.path.join(d, "cache", "previews")
            try:
                self.assertIsNone(server.card_cache("wifi"))
                imgs = [{"path": "/DCIM/100OLYMP/P1.JPG", "size": 1, "date": 1, "time": 1}]
                server.card_cache("wifi", imgs)
                self.assertEqual(server.card_cache("wifi"), imgs)
                self.assertIsNone(server.card_cache("usb"))  # USB paths differ
            finally:
                server.PREVIEW_CACHE = old



class LiveStartRetry(unittest.TestCase):
    """Wi-Fi: startliveview right after switch_cammode may answer 520 for a moment."""

    def run_start(self, fails, age=None):
        from omcap.camera import CameraError

        class Cam:
            calls = 0

            def start_liveview(self, port):
                Cam.calls += 1
                if Cam.calls <= fails:
                    raise CameraError("HTTP Error 520", code=520)

        class Live:
            def start(self):
                pass
        Live.age = age
        saved = server.cam, server.live, server.conn_type, server.time.sleep
        server.cam, server.live, server.conn_type, server.time.sleep = Cam(), Live(), "wifi", lambda s: None
        try:
            server.start_live()
        finally:
            server.cam, server.live, server.conn_type, server.time.sleep = saved
        return Cam.calls

    def test_retries_then_ok(self):
        self.assertEqual(self.run_start(2), 3)

    def test_frames_already_arrive(self):
        self.assertEqual(self.run_start(9, age=0.1), 1)

    def test_gives_up(self):
        from omcap.camera import CameraError
        with self.assertRaises(CameraError):
            self.run_start(9)


if __name__ == "__main__":
    unittest.main()
