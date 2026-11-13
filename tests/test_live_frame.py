"""GET /live.jpg: next live frame after a sequence number, 204 if none (no camera)."""
import socket
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from omcap import server


class FakeLive:
    def __init__(self, seq, frame):
        self.seq, self.frame = seq, frame

    def wait_frame(self, last_seq, timeout=3.0):
        return self.seq, self.frame


class LiveFrame(unittest.TestCase):
    def setUp(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.host = "127.0.0.1:%d" % port
        server.allowed_hosts.add(self.host)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.allowed_hosts.discard(self.host)

    def get(self, seq):
        with urllib.request.urlopen("http://%s/live.jpg?seq=%d" % (self.host, seq), timeout=5) as r:
            return r.status, r.headers.get("X-Seq"), r.read()

    def test_new_frame(self):
        with mock.patch.object(server, "live", FakeLive(7, b"\xff\xd8jpg\xff\xd9")), \
                mock.patch.object(server, "cam", object()):
            self.assertEqual(self.get(6), (200, "7", b"\xff\xd8jpg\xff\xd9"))

    def test_no_new_frame(self):
        with mock.patch.object(server, "live", FakeLive(7, b"\xff\xd8jpg\xff\xd9")), \
                mock.patch.object(server, "cam", object()):
            self.assertEqual(self.get(7)[0], 204)


if __name__ == "__main__":
    unittest.main()
