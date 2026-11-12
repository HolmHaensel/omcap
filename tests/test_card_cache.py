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



class NewestFolderOnly(unittest.TestCase):
    """Wi-Fi after a shot: only the newest folder is read and merged into the saved list."""

    def test_merge(self):
        def e(folder, name, t):
            return {"dir": "/DCIM/" + folder, "name": name, "path": "/DCIM/%s/%s" % (folder, name),
                    "size": 1, "isdir": False, "date": 1, "time": t}
        read = []

        class Cam:
            def listdir(self, d):
                return [{"name": "108_PANA", "isdir": True}, {"name": "111OLYMP", "isdir": True}]

            def images(self, root):
                read.append(root)
                return [e("111OLYMP", "P2.JPG", 2), e("111OLYMP", "P3.JPG", 3)]
        old = server.PREVIEW_CACHE, server.cam
        with tempfile.TemporaryDirectory() as d:
            server.PREVIEW_CACHE, server.cam = os.path.join(d, "cache", "previews"), Cam()
            try:
                server.card_cache("wifi", [e("111OLYMP", "P2.JPG", 2), e("108_PANA", "P1.JPG", 1)])
                imgs = server.wifi_images_newest()
                self.assertEqual(read, ["/DCIM/111OLYMP"])
                self.assertEqual([x["name"] for x in imgs], ["P3.JPG", "P2.JPG", "P1.JPG"])
                self.assertEqual(server.card_cache("wifi"), imgs)
            finally:
                server.PREVIEW_CACHE, server.cam = old


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
