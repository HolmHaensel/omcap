"""POST /api/connect twice at once (start screen auto-connect and a click): one connection, the second waits for it.

Seen 2026-11-15: both requests connected, the second one disconnected the first and one of them failed."""
import json
import socket
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from omcap import server


class ConnectOnce(unittest.TestCase):
    def test_two_requests_one_connection(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        host = "127.0.0.1:%d" % port
        server.allowed_hosts.add(host)
        httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        calls = []

        def fake_connect(kind):
            calls.append(kind)
            time.sleep(0.3)  # connecting takes a while
            server.cam, server.conn_type = object(), kind

        def post():
            req = urllib.request.Request("http://%s/api/connect" % host, json.dumps({"type": "usb"}).encode(),
                                         {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                answers.append(json.loads(r.read()))

        answers = []
        old = server.cam, server.conn_type
        try:
            with mock.patch.object(server, "connect", side_effect=fake_connect):
                threads = [threading.Thread(target=post) for _ in range(2)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(5)
            self.assertEqual(calls, ["usb"])
            self.assertEqual([a.get("type") for a in answers], ["usb", "usb"])
        finally:
            server.cam, server.conn_type = old
            server.allowed_hosts.discard(host)
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
