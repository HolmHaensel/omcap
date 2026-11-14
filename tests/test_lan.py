"""Phone in the home network (--lan, REQ-F47): key check and QR code, no camera."""
import unittest
from email.message import Message
from unittest import mock

from omcap import qr, server


def handler(client, cookie=None, host="192.168.178.39:8765"):
    h = server.Handler.__new__(server.Handler)
    h.client_address = (client, 50000)
    h.headers = Message()
    h.headers["Host"] = host
    if cookie is not None:
        h.headers["Cookie"] = cookie
    return h


class LanKey(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(server.lan, {"key": "secret-key", "url": "http://192.168.178.39:8765/?key=secret-key"})
        p.start()
        self.addCleanup(p.stop)
        h = mock.patch.object(server, "allowed_hosts", {"127.0.0.1:8765", "192.168.178.39:8765"})
        h.start()
        self.addCleanup(h.stop)

    def test_computer_needs_no_key(self):
        self.assertTrue(handler("127.0.0.1", host="127.0.0.1:8765")._trusted())

    def test_phone_needs_the_key(self):
        self.assertFalse(handler("192.168.178.50")._trusted())
        self.assertFalse(handler("192.168.178.50", cookie="omcap_key=wrong")._trusted())
        self.assertTrue(handler("192.168.178.50", cookie="omcap_key=secret-key")._trusted())

    def test_non_ascii_cookie_is_refused_not_crashing(self):
        self.assertFalse(handler("192.168.178.50", cookie="omcap_key=\u00e9t\u00e9")._trusted())

    def test_key_not_in_timing_log(self):
        h = handler("192.168.178.50")
        h.path = "/?key=secret-key"
        self.assertNotIn("secret", h._log_path())

    def test_foreign_host_refused_even_with_key(self):
        self.assertFalse(handler("192.168.178.50", cookie="omcap_key=secret-key", host="evil.example:8765")._trusted())

    def test_without_lan_no_other_device(self):
        with mock.patch.dict(server.lan, {"key": None}):
            self.assertFalse(handler("192.168.178.50", cookie="omcap_key=secret-key")._trusted())


class Connections(unittest.TestCase):
    def test_lan_flag_in_both_branches(self):
        with mock.patch.dict(server.lan, {"key": "k"}), mock.patch.object(server, "conn_type", "usb"):
            self.assertTrue(server.connections()["lan"])
        with mock.patch.dict(server.lan, {"key": None}), mock.patch.object(server, "conn_type", None), \
                mock.patch.object(server, "wifi_name", return_value=None), \
                mock.patch.object(server.usb_camera, "detect_name", return_value=None):
            self.assertFalse(server.connections()["lan"])


class LanAddress(unittest.TestCase):
    def test_camera_network_is_skipped(self):
        with mock.patch.object(server.socket, "socket") as sock, \
                mock.patch.object(server.socket, "getaddrinfo", return_value=[]):
            sock.return_value.getsockname.side_effect = [("192.168.0.21", 0), ("192.168.178.39", 0), ("10.0.0.2", 0)]
            self.assertEqual(server.lan_address(), "192.168.178.39")


class QrCode(unittest.TestCase):
    def test_size_and_finder_patterns(self):
        m = qr.encode("http://192.168.178.39:8765/?key=Ab3dEf6hIj9kLm0nOp1q")
        self.assertEqual(len(m), 33)  # version 4
        for r, c in ((0, 0), (0, 26), (26, 0)):  # finder corners: dark ring, light gap, dark core
            self.assertTrue(m[r][c] and m[r + 6][c + 6] and m[r + 3][c + 3])
            self.assertFalse(m[r + 1][c + 1])

    def test_too_long(self):
        with self.assertRaises(ValueError):
            qr.encode("x" * 107)

    def test_svg(self):
        self.assertTrue(qr.svg("hi").startswith("<svg"))


if __name__ == "__main__":
    unittest.main()
