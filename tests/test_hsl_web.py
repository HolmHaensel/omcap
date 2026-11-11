"""Server-side HSL (omcap.server hsl_apply and the HTTP routes) with synthetic images only."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np

import omcap.server as server


class HslWebTests(unittest.TestCase):
    def setUp(self):
        import imageio.v2 as imageio
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (server.CAPTURES, server.HSL_OUT, dict(server.hsl_auto), set(server.allowed_hosts))
        server.CAPTURES = os.path.join(self.tmp.name, "captures")
        server.HSL_OUT = os.path.join(self.tmp.name, "out", "hsl")
        os.makedirs(server.CAPTURES)
        rng = np.random.RandomState(3)
        img = (rng.rand(24, 32, 3) * 255).astype(np.uint8)
        imageio.imwrite(os.path.join(server.CAPTURES, "a.jpg"), img)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.host = "127.0.0.1:%d" % self.srv.server_address[1]
        server.allowed_hosts.add(self.host)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        server.CAPTURES, server.HSL_OUT = self.old[0], self.old[1]
        server.hsl_auto.clear()
        server.hsl_auto.update(self.old[2])
        server.allowed_hosts.clear()
        server.allowed_hosts.update(self.old[3])
        self.tmp.cleanup()

    def call(self, path, body=None):
        req = urllib.request.Request("http://" + self.host + path,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_presets_and_apply(self):
        code, b = self.call("/api/hsl/presets")
        self.assertEqual(code, 200)
        names = json.loads(b)["presets"]
        self.assertIn("Neutral", names)
        code, b = self.call("/api/hsl", {"name": "a.jpg", "profile": names[1]})
        self.assertEqual(code, 200)
        out = json.loads(b)["name"]
        self.assertEqual(out, "a_JPG_hsl.jpg")
        self.assertTrue(os.path.isfile(os.path.join(server.HSL_OUT, out)))
        self.assertEqual(os.listdir(server.CAPTURES), ["a.jpg"])   # nothing next to the source
        code, b = self.call("/out-hsl/" + out)
        self.assertEqual((code, b[:2]), (200, b"\xff\xd8"))

    def test_path_safety_and_errors(self):
        code, _ = self.call("/out-hsl/..%2F..%2Fetc%2Fpasswd")
        self.assertNotEqual(code, 200)
        code, _ = self.call("/api/hsl", {"name": "nothere.jpg", "profile": "Neutral"})
        self.assertEqual(code, 502)
        code, _ = self.call("/api/hsl", {"name": "a.jpg", "profile": "No such preset"})
        self.assertEqual(code, 502)

    def test_auto_on_save(self):
        code, _ = self.call("/api/hslauto", {"enabled": True, "preset": "Neutral"})
        self.assertEqual(code, 200)
        server.hsl_auto_run(os.path.join(server.CAPTURES, "a.jpg"))
        target = os.path.join(server.HSL_OUT, "a_JPG_hsl.jpg")
        for _ in range(100):
            if os.path.isfile(target):
                break
            threading.Event().wait(0.05)
        self.assertTrue(os.path.isfile(target))


if __name__ == "__main__":
    unittest.main()
