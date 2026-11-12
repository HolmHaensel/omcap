"""POST /api/quit: disconnects, answers, then stops the server (no camera)."""
import json
import socket
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from omcap import server


class QuitTest(unittest.TestCase):
    def _quit(self, disconnect_error=None):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        host = "127.0.0.1:%d" % port
        server.allowed_hosts.add(host)
        httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        old = server.http_server
        server.http_server = httpd
        try:
            with mock.patch.object(server, "disconnect", side_effect=disconnect_error) as disc:
                req = urllib.request.Request("http://%s/api/quit" % host, b"{}",
                                             {"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    self.assertTrue(json.loads(r.read())["ok"])
                t.join(5)
                self.assertFalse(t.is_alive())
                disc.assert_called_once_with()
        finally:
            server.http_server = old
            server.allowed_hosts.discard(host)
            httpd.server_close()

    def test_quit_disconnects_and_shuts_down(self):
        self._quit()

    def test_quit_stops_even_if_disconnect_fails(self):
        self._quit(server.CameraError("USB: gone"))

    def test_foreign_origin_is_refused(self):
        h = server.Handler.__new__(server.Handler)
        h.headers = {"Host": "127.0.0.1:1", "Origin": "http://evil.example"}
        self.assertFalse(h._trusted())


if __name__ == "__main__":
    unittest.main()
