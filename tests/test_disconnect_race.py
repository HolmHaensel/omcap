"""A disconnect in parallel to a request gives 409 (not 500); ext_info while the UDP loop counts (no camera)."""
import socket
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from omcap import liveview, server


class Vanishing:
    """Camera whose connection is dropped by a parallel disconnect during the first call."""
    features = []
    allow_write = False

    def props(self):
        server.cam = None
        return server.cam.props()  # what a handler reading the global again would hit


class Race(unittest.TestCase):
    def setUp(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.host = "127.0.0.1:%d" % port
        server.allowed_hosts.add(self.host)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.allowed_hosts.discard(self.host)

    def test_get_409(self):
        with mock.patch.object(server, "cam", Vanishing()):
            with self.assertRaises(urllib.error.HTTPError) as c:
                urllib.request.urlopen("http://%s/api/props" % self.host, timeout=5)
        self.assertEqual(c.exception.code, 409)

    def test_post_409(self):
        class Gone:
            def __getattr__(self, name):
                server.cam = None
                raise AttributeError(name)
        req = urllib.request.Request("http://%s/api/poweroff" % self.host, data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        with mock.patch.object(server, "cam", Gone()), mock.patch.object(server, "conn_type", "wifi"):
            with self.assertRaises(urllib.error.HTTPError) as c:
                urllib.request.urlopen(req, timeout=5)
        self.assertEqual(c.exception.code, 409)

    def test_ext_info_while_counting(self):
        lv = liveview.LiveView(0)
        stop = threading.Event()

        def count():
            n = 0
            while not stop.is_set():
                n += 1
                with lv.cond:
                    for fid in range(n % 50, n % 50 + 20):
                        lv.ext_seen[fid] = lv.ext_seen.get(fid, 0) + 1
        t = threading.Thread(target=count)
        t.start()
        try:
            for _ in range(300):
                lv.ext_info()  # raised "dictionary changed size during iteration" without the copy under the lock
        finally:
            stop.set()
            t.join()


if __name__ == "__main__":
    unittest.main()
