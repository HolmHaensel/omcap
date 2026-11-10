"""Start behaviour: already-running detection and the /api/app probe (no camera, no browser)."""
import socket
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

from omcap import server


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class StartTest(unittest.TestCase):
    def test_no_app_on_free_port(self):
        self.assertIsNone(server.running_app(free_port(), timeout=0.5))

    def test_detects_running_app_and_does_not_start_twice(self):
        port = free_port()
        server.allowed_hosts.add("127.0.0.1:%d" % port)
        httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            info = server.running_app(port)
            self.assertEqual(info["app"], server.APP_ID)
            with mock.patch("webbrowser.open") as wb:
                self.assertEqual(server.main(["--port", str(port), "--no-browser"]), 0)
                wb.assert_not_called()
            with mock.patch("webbrowser.open") as wb:
                self.assertEqual(server.main(["--port", str(port)]), 0)
                wb.assert_called_once_with("http://127.0.0.1:%d/" % port)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_foreign_program_on_port(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            port = s.getsockname()[1]
            with mock.patch.object(server, "running_app", return_value=None):
                self.assertEqual(server.main(["--port", str(port), "--no-browser"]), 1)


if __name__ == "__main__":
    unittest.main()
