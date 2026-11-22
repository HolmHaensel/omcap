"""Offline unit tests for the read-only MCP server (REQ-F35). No camera, no sockets."""
import ast
import base64
import io
import json
import os
import unittest
from unittest import mock

from omcap import __version__, mcp_server

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\xff\xd9"


class FakeClient:
    """In-memory stand-in for mcp_server.HttpClient recording every GET and POST request."""

    def __init__(self, json_map=None, bytes_map=None, allow_write=False):
        self.json_map = dict(json_map or {})
        self.bytes_map = dict(bytes_map or {})
        self.allow_write = allow_write
        self.calls = []
        self.posts = []
        self.post_hook = None

    def _lookup(self, table, path, query):
        key = (path, tuple(sorted((query or {}).items())))
        self.calls.append(key)
        if key in table:
            val = table[key]
        elif (path, ()) in table and not query:
            val = table[(path, ())]
        elif path in table:
            val = table[path]
        else:
            raise mcp_server.ApiError("Not found: %s" % path, status=404)
        if isinstance(val, Exception):
            raise val
        return val

    def get_json(self, path, query=None, timeout=None):
        return self._lookup(self.json_map, path, query)

    def get_bytes(self, path, query=None, timeout=None, max_bytes=None):
        status, data, headers = self._lookup(self.bytes_map, path, query)
        if max_bytes is not None and len(data) > max_bytes:
            raise mcp_server.ApiError("Image exceeds limit", status=status)
        return status, data, headers

    def post_json(self, path, payload, timeout=None):
        if not self.allow_write:
            raise mcp_server.ApiError("Read-only", status=403)
        if path not in mcp_server.WRITE_ENDPOINTS:
            raise mcp_server.ApiError("Not allowed", status=403)
        self.posts.append((path, dict(payload)))
        if self.post_hook:
            return self.post_hook(path, payload)
        return {"ok": True}


class UrlAndSafety(unittest.TestCase):
    def test_accepts_loopback_http_urls(self):
        self.assertEqual(mcp_server.validate_url("http://127.0.0.1:8765"), "http://127.0.0.1:8765")
        self.assertEqual(mcp_server.validate_url("http://127.0.0.1:8765/"), "http://127.0.0.1:8765")
        self.assertEqual(mcp_server.validate_url("http://localhost:8770"), "http://localhost:8770")

    def test_rejects_non_loopback_or_bad_urls(self):
        for bad in (
            "",
            "https://127.0.0.1:8765",
            "http://192.168.0.10:80",
            "http://example.com:8765",
            "http://127.0.0.1",
            "http://user:pass@127.0.0.1:8765",
            "http://127.0.0.1:8765/api/status",
            "http://127.0.0.1:8765?x=1",
            "file:///etc/passwd",
        ):
            with self.subTest(url=bad):
                with self.assertRaises(ValueError):
                    mcp_server.validate_url(bad)

    def test_module_never_imports_camera_or_usb_directly(self):
        # REQ-F35 hard architectural gate: HTTP API only, never direct camera/PTP access
        src = os.path.abspath(mcp_server.__file__)
        with open(src, encoding="utf-8") as f:
            tree = ast.parse(f.read(), src)
        forbidden = {"camera", "usb_camera", "ptp", "ptp_gphoto", "liveview", "gphoto2"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(any(b in alias.name.split(".") for b in forbidden), alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")
                names = [a.name for a in node.names]
                self.assertFalse(any(b in mod or b in names for b in forbidden), (node.module, names))

    def test_http_client_uses_get_only_and_bypasses_proxies(self):
        client = mcp_server.HttpClient("http://127.0.0.1:8765")
        resp = mock.MagicMock()
        resp.status = 200
        resp.headers = {"Content-Type": "application/json"}
        resp.read.return_value = b'{"ok": true}'
        resp.__enter__.return_value = resp
        with mock.patch.object(client._opener, "open", return_value=resp) as m:
            self.assertEqual(client.get_json("/api/app"), {"ok": True})
            req = m.call_args[0][0]
            self.assertEqual(req.get_method(), "GET")
            self.assertEqual(req.full_url, "http://127.0.0.1:8765/api/app")

    def test_http_client_enforces_max_bytes_from_content_length_and_body(self):
        client = mcp_server.HttpClient("http://127.0.0.1:8765")
        resp = mock.MagicMock()
        resp.status = 200
        resp.headers = {"Content-Length": str(20 << 20)}
        resp.__enter__.return_value = resp
        with mock.patch.object(client._opener, "open", return_value=resp):
            with self.assertRaises(mcp_server.ApiError):
                client.get_bytes("/api/full", max_bytes=1024)

        resp.headers = {}
        resp.read.return_value = b"x" * 1025
        with mock.patch.object(client._opener, "open", return_value=resp):
            with self.assertRaises(mcp_server.ApiError):
                client.get_bytes("/api/full", max_bytes=1024)


class Protocol(unittest.TestCase):
    def setUp(self):
        self.srv = mcp_server.McpServer(FakeClient())

    def test_initialize_and_ping_and_notification(self):
        r = self.srv.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                     "params": {"protocolVersion": "2024-11-05"}})
        self.assertEqual(r["id"], 1)
        self.assertEqual(r["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(r["result"]["serverInfo"], {"name": "em1-capture", "version": __version__})
        self.assertIn("read-only", r["result"]["instructions"].lower())

        # Unsupported protocol version falls back to server default
        r2 = self.srv.handle_message({"jsonrpc": "2.0", "id": 2, "method": "initialize",
                                      "params": {"protocolVersion": "1999-01-01"}})
        self.assertEqual(r2["result"]["protocolVersion"], mcp_server.PROTOCOL_VERSION)

        self.assertEqual(self.srv.handle_message({"jsonrpc": "2.0", "id": 3, "method": "ping"})["result"], {})
        # Notifications (no id) get no reply
        self.assertIsNone(self.srv.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_tools_list_all_read_only(self):
        r = self.srv.handle_message({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
        tools = r["result"]["tools"]
        names = [t["name"] for t in tools]
        self.assertEqual(names, ["camera_status", "camera_settings", "live_view_frame",
                                 "list_card_images", "last_picture"])
        for t in tools:
            self.assertTrue(t["annotations"]["readOnlyHint"])
            self.assertFalse(t["annotations"]["destructiveHint"])
            self.assertFalse(t["inputSchema"]["additionalProperties"])

    def test_rpc_error_codes(self):
        self.assertEqual(self.srv.handle_message("bad")["error"]["code"], -32600)
        self.assertEqual(self.srv.handle_message({"jsonrpc": "2.0", "id": 1})["error"]["code"], -32600)
        self.assertEqual(self.srv.handle_message({"jsonrpc": "2.0", "id": 1, "method": "nope"})["error"]["code"], -32601)
        self.assertEqual(
            self.srv.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": "shoot", "arguments": {}}})["error"]["code"],
            -32602,
        )
        # Unknown arguments rejected per additionalProperties: False
        self.assertEqual(
            self.srv.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": "live_view_frame", "arguments": {"write": True}}})["error"]["code"],
            -32602,
        )

    def test_stdio_serve_loop_handles_parse_error_and_valid_lines(self):
        inp = io.StringIO(
            "\n"
            "{not json\n"
            '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
            '{"jsonrpc":"2.0","id":7,"method":"ping"}\n'
        )
        out = io.StringIO()
        mcp_server.serve(self.srv, stdin=inp, stdout=out)
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["error"]["code"], -32700)
        self.assertEqual(lines[1], {"jsonrpc": "2.0", "id": 7, "result": {}})


def _call(client, name, arguments=None, allow_write=False, lenses=None):
    srv = mcp_server.McpServer(client, allow_write=allow_write, lenses=lenses)
    resp = srv.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    })
    return resp["result"]


def _json_payload(res):
    texts = [c["text"] for c in res["content"] if c["type"] == "text"]
    return json.loads(texts[-1])


class CameraStatusTool(unittest.TestCase):
    def test_not_connected_returns_available_connections(self):
        client = FakeClient(json_map={
            "/api/app": {"app": "em1-capture", "version": __version__, "allow_write": False},
            "/api/status": mcp_server.ApiError("Not connected", status=409),
            "/api/connections": {"connected": None, "usb": True, "wifi": False, "names": {"usb": "E-M1", "wifi": None}},
        })
        res = _call(client, "camera_status")
        self.assertFalse(res["isError"])
        data = _json_payload(res)
        self.assertFalse(data["connected"])
        self.assertTrue(data["connections"]["usb"])

    def test_usb_connected_includes_lens_and_level(self):
        client = FakeClient(json_map={
            "/api/app": {"app": "em1-capture", "version": __version__, "allow_write": True},
            "/api/status": {"type": "usb", "model": "E-M1", "allow_write": True,
                            "usb_backend": "ptp", "features": ["liveview", "level"]},
            "/api/state": {"live": True, "lvqty": "1024x0768", "lv_age": 0.04, "stage": 0, "busy": False,
                           "gone": False, "play": False, "card": True, "loupe": True, "loupe_ratio": 5, "fast_n": 1},
            "/api/device": {"card": 4000000000, "battery": 100},
            "/api/afarea": {"mode": 33025, "field": 41, "modes": True},
            "/api/lens": {"lens": {"name": "M.12-40mm F2.8", "focal": 25}},
            "/api/level": {"a": -0.2, "b": 0.4},
        })
        res = _call(client, "camera_status")
        self.assertFalse(res["isError"])
        data = _json_payload(res)
        self.assertTrue(data["connected"])
        self.assertEqual(data["connection"]["type"], "usb")
        self.assertEqual(data["lens"]["name"], "M.12-40mm F2.8")
        self.assertEqual(data["level"], {"a": -0.2, "b": 0.4})
        self.assertTrue(data["live_view"]["loupe"])
        self.assertEqual(data["live_view"]["loupe_ratio"], 5)

    def test_wifi_connected_reads_lens_from_cached_jpg_and_skips_level(self):
        client = FakeClient(json_map={
            "/api/app": {"app": "em1-capture", "version": __version__, "allow_write": False},
            "/api/status": {"type": "wifi", "model": "E-M1", "allow_write": False,
                            "usb_backend": None, "features": ["liveview"]},
            "/api/state": {"live": True, "lvqty": "0800x0600", "lv_age": 0.08, "stage": 0, "busy": False,
                           "gone": False, "play": False, "card": None, "lvinfo": {"iso": 400, "focal": [12, 40, 25]}},
            "/api/device": {"card": 123456, "battery": None},
            "/api/afarea": {"mode": 33025, "field": 41, "modes": False},
            ("/api/images", (("cached", "1"),)): [
                {"path": "/DCIM/100OLYMP/PB220002.ORF"},
                {"path": "/DCIM/100OLYMP/PB220001.JPG"},
            ],
            ("/api/lens", (("path", "/DCIM/100OLYMP/PB220001.JPG"),)): {"lens": {"name": "M.12-40mm F2.8"}},
        })
        res = _call(client, "camera_status")
        data = _json_payload(res)
        self.assertEqual(data["lens"]["name"], "M.12-40mm F2.8")
        self.assertNotIn("level", data)
        self.assertFalse(any(p == "/api/level" for p, _ in client.calls))

    def test_usb_gone_skips_optional_camera_queries(self):
        client = FakeClient(json_map={
            "/api/app": {"app": "em1-capture", "version": __version__, "allow_write": True},
            "/api/status": {"type": "usb", "model": "E-M1", "allow_write": True, "features": ["liveview", "level"]},
            "/api/state": {"live": False, "gone": True, "stage": 0, "busy": False},
        })
        res = _call(client, "camera_status")
        data = _json_payload(res)
        self.assertTrue(data["camera_state"]["gone"])
        self.assertEqual([p for p, _ in client.calls], ["/api/app", "/api/status", "/api/state"])

    def test_server_offline_returns_tool_error(self):
        client = FakeClient(json_map={"/api/app": mcp_server.ApiError("E-M1 Capture is not running")})
        res = _call(client, "camera_status")
        self.assertTrue(res["isError"])
        self.assertIn("not running", res["content"][0]["text"])


class CameraSettingsTool(unittest.TestCase):
    PROPS = {
        "takemode": {"value": "A", "writable": False, "enum": []},
        "focusmode": {"value": "32769", "writable": True, "enum": ["2", "32769"],
                      "names": {"2": "MF", "32769": "S-AF+MF"}},
        "shutspeedvalue": {"value": "1/250", "writable": True, "enum": ["1/4000", "1/250", "1"]},
    }

    def test_overview_omits_enums_and_adds_usb_labels(self):
        res = _call(FakeClient(json_map={"/api/props": self.PROPS}), "camera_settings")
        self.assertFalse(res["isError"])
        data = _json_payload(res)
        self.assertEqual(data["focusmode"], {"value": "32769", "writable": True, "label": "S-AF+MF"})
        self.assertNotIn("enum", data["shutspeedvalue"])

    def test_single_prop_includes_enum_and_names(self):
        res = _call(FakeClient(json_map={"/api/props": self.PROPS}), "camera_settings", {"prop": "focusmode"})
        self.assertFalse(res["isError"])
        data = _json_payload(res)
        self.assertEqual(data["focusmode"]["enum"], ["2", "32769"])
        self.assertEqual(data["focusmode"]["names"]["32769"], "S-AF+MF")

    def test_unknown_prop_returns_error_with_available_names(self):
        res = _call(FakeClient(json_map={"/api/props": self.PROPS}), "camera_settings", {"prop": "bogus"})
        self.assertTrue(res["isError"])
        self.assertIn("focusmode", res["content"][0]["text"])


class LiveViewFrameTool(unittest.TestCase):
    def test_returns_jpeg_and_metadata_when_running(self):
        client = FakeClient(
            json_map={"/api/state": {"live": True, "lvqty": "1024x0768", "lvinfo": {"iso": 200}}},
            bytes_map={("/live.jpg", (("seq", "0"),)): (200, JPEG, {"x-seq": "42", "x-loupe": "1"})},
        )
        res = _call(client, "live_view_frame")
        self.assertFalse(res["isError"])
        self.assertEqual(res["content"][0]["type"], "image")
        self.assertEqual(base64.b64decode(res["content"][0]["data"]), JPEG)
        meta = _json_payload(res)
        self.assertEqual(meta["seq"], 42)
        self.assertTrue(meta["loupe"])
        self.assertEqual(meta["bytes"], len(JPEG))

    def test_live_view_off_fails_without_starting_live_view(self):
        client = FakeClient(json_map={"/api/state": {"live": False}})
        res = _call(client, "live_view_frame")
        self.assertTrue(res["isError"])
        self.assertIn("not running", res["content"][0]["text"])
        self.assertEqual(client.calls, [("/api/state", ())])

    def test_204_timeout_returns_error(self):
        client = FakeClient(
            json_map={"/api/state": {"live": True}},
            bytes_map={("/live.jpg", (("seq", "0"),)): (204, b"", {})},
        )
        res = _call(client, "live_view_frame")
        self.assertTrue(res["isError"])


class ListCardImagesTool(unittest.TestCase):
    def test_uses_cache_by_default_and_respects_limit(self):
        imgs = [{"path": "/DCIM/100OLYMP/P%02d.JPG" % i, "name": "P%02d.JPG" % i, "size": 1000} for i in range(5)]
        client = FakeClient(json_map={("/api/images", (("cached", "1"),)): imgs})
        res = _call(client, "list_card_images", {"limit": 2})
        data = _json_payload(res)
        self.assertTrue(data["cached"])
        self.assertEqual(data["total"], 5)
        self.assertEqual(data["shown"], 2)

    def test_falls_back_to_live_list_when_cache_empty(self):
        imgs = [{"path": "/DCIM/100OLYMP/P01.JPG", "name": "P01.JPG", "size": 1000}]
        client = FakeClient(json_map={
            ("/api/images", (("cached", "1"),)): [],
            ("/api/images", (("dir", "/DCIM"),)): imgs,
        })
        res = _call(client, "list_card_images")
        data = _json_payload(res)
        self.assertFalse(data["cached"])
        self.assertEqual(data["total"], 1)

    def test_rejects_bad_limit_and_dir(self):
        client = FakeClient()
        self.assertTrue(_call(client, "list_card_images", {"limit": True})["isError"])
        self.assertTrue(_call(client, "list_card_images", {"dir": "DCIM"})["isError"])


class LastPictureTool(unittest.TestCase):
    def test_usb_fast_shot_with_card_exif(self):
        client = FakeClient(
            json_map={
                "/api/lastshot": {"path": "/DCIM/100OLYMP/PB220001.JPG", "fast": 3},
                ("/api/exif", (("path", "/DCIM/100OLYMP/PB220001.JPG"),)): {"exif": {"iso": 200, "fnumber": 2.8}},
            },
            bytes_map={"/api/lastfast": (200, JPEG, {})},
        )
        res = _call(client, "last_picture")
        self.assertFalse(res["isError"])
        self.assertEqual(res["content"][0]["type"], "image")
        meta = _json_payload(res)
        self.assertEqual(meta["source"], "lastfast")
        self.assertEqual(meta["exif"], {"iso": 200, "fnumber": 2.8})

    def test_usb_no_card_direct_store_uses_captures_fallback(self):
        client = FakeClient(
            json_map={
                "/api/lastshot": {"path": None, "fast": None},
                "/api/state": {"card": False, "latest": "E-M1_20261122-220000.JPG"},
            },
            bytes_map={"/captures/E-M1_20261122-220000.JPG": (200, JPEG, {})},
        )
        res = _call(client, "last_picture")
        self.assertFalse(res["isError"])
        meta = _json_payload(res)
        self.assertEqual(meta["source"], "captures")
        self.assertEqual(meta["local"], "E-M1_20261122-220000.JPG")

    def test_wifi_falls_back_to_newest_jpg_thumb_and_exif(self):
        client = FakeClient(
            json_map={
                "/api/lastshot": {"path": None, "fast": None},
                "/api/state": {"card": None, "latest": None},
                ("/api/images", (("cached", "1"),)): [
                    {"path": "/DCIM/100OLYMP/PB220002.ORF"},
                    {"path": "/DCIM/100OLYMP/PB220002.JPG"},
                ],
                ("/api/exif", (("path", "/DCIM/100OLYMP/PB220002.JPG"),)): {"exif": {"shutter": "1/125"}},
            },
            bytes_map={("/api/thumb", (("path", "/DCIM/100OLYMP/PB220002.JPG"),)): (200, JPEG, {})},
        )
        res = _call(client, "last_picture")
        self.assertFalse(res["isError"])
        meta = _json_payload(res)
        self.assertEqual(meta["path"], "/DCIM/100OLYMP/PB220002.JPG")
        self.assertEqual(meta["source"], "thumb")
        self.assertEqual(meta["exif"]["shutter"], "1/125")

    def test_explicit_orf_notes_no_exif_and_blocks_full(self):
        client = FakeClient(
            bytes_map={("/api/thumb", (("path", "/DCIM/100OLYMP/PB220002.ORF"),)): (200, JPEG, {})},
        )
        res = _call(client, "last_picture", {"path": "/DCIM/100OLYMP/PB220002.ORF", "preview": "thumb"})
        self.assertFalse(res["isError"])
        meta = _json_payload(res)
        self.assertIsNone(meta["exif"])
        self.assertIn("JPG", meta["exif_note"])

        res_full = _call(client, "last_picture", {"path": "/DCIM/100OLYMP/PB220002.ORF", "preview": "full"})
        self.assertTrue(res_full["isError"])

    def test_preview_none_returns_metadata_only(self):
        client = FakeClient(json_map={
            ("/api/exif", (("path", "/DCIM/100OLYMP/PB220001.JPG"),)): {"exif": {"iso": 400}},
        })
        res = _call(client, "last_picture", {"path": "/DCIM/100OLYMP/PB220001.JPG", "preview": "none"})
        self.assertFalse(res["isError"])
        self.assertEqual(len(res["content"]), 1)
        self.assertEqual(res["content"][0]["type"], "text")
        self.assertIsNone(_json_payload(res)["source"])

    def test_empty_card_returns_error(self):
        client = FakeClient(json_map={
            "/api/lastshot": {"path": None, "fast": None},
            "/api/state": {"card": True, "latest": None},
            ("/api/images", (("cached", "1"),)): [],
            "/api/images": [],
        })
        res = _call(client, "last_picture")
        self.assertTrue(res["isError"])

    def test_not_connected_is_reported_not_masked_as_empty(self):
        client = FakeClient(json_map={"/api/lastshot": mcp_server.ApiError("Not connected", status=409)})
        res = _call(client, "last_picture")
        self.assertTrue(res["isError"])
        self.assertIn("Not connected", res["content"][0]["text"])


class WriteSafetyAndConfigure(unittest.TestCase):
    USB_PROPS = {
        "takemode": {"value": "A", "writable": False, "enum": []},
        "focalvalue": {"value": "4.0", "writable": True, "enum": ["2.8", "4.0", "5.6"]},
        "isospeedvalue": {"value": "Auto", "writable": True, "enum": ["Auto", "200", "800", "1600"]},
        "focusmode": {"value": "2", "writable": True, "enum": ["1", "2", "32769"],
                      "names": {"1": "MF", "2": "S-AF", "32769": "S-AF+MF"}},
        "stabilizer": {"value": "4", "writable": True, "enum": ["0", "1", "4"],
                       "names": {"0": "Off", "1": "S-IS 1", "4": "S-IS Auto"}},
    }

    def test_http_client_blocks_post_without_allow_write_and_blocks_dangerous_endpoints(self):
        ro = mcp_server.HttpClient("http://127.0.0.1:8765", allow_write=False)
        with self.assertRaises(mcp_server.ApiError):
            ro.post_json("/api/set", {"prop": "isospeedvalue", "value": "800"})

        rw = mcp_server.HttpClient("http://127.0.0.1:8765", allow_write=True)
        for forbidden in ("/api/shoot", "/api/shutter", "/api/erase", "/api/poweroff", "/api/open", "/api/quit"):
            with self.subTest(endpoint=forbidden):
                with self.assertRaises(mcp_server.ApiError):
                    rw.post_json(forbidden, {})

    def test_read_only_server_hides_and_rejects_camera_configure(self):
        srv = mcp_server.McpServer(FakeClient(), allow_write=False)
        names = [t["name"] for t in srv.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]
        self.assertNotIn("camera_configure", names)
        resp = srv.handle_message({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "camera_configure", "arguments": {"settings": {"isospeedvalue": "800"}}},
        })
        self.assertEqual(resp["error"]["code"], -32602)

    def test_dry_run_resolves_usb_labels_and_reports_manual_mode_dial(self):
        client = FakeClient(json_map={
            "/api/status": {"type": "usb", "allow_write": True},
            "/api/props": self.USB_PROPS,
        }, allow_write=True)
        res = _call(client, "camera_configure", {
            "settings": {"takemode": "M", "focalvalue": "f/2.8", "isospeedvalue": "ISO 1600",
                         "focusmode": "MF", "stabilizer": "Off"},
        }, allow_write=True)
        self.assertFalse(res["isError"])
        data = _json_payload(res)
        self.assertTrue(data["dry_run"])
        self.assertFalse(data["applied"])
        self.assertEqual(client.posts, [])
        changed = {c["prop"]: c["target"] for c in data["changes"]}
        self.assertEqual(changed, {"focalvalue": "2.8", "isospeedvalue": "1600", "focusmode": "1", "stabilizer": "0"})
        self.assertTrue(any("mode dial" in s for s in data["manual_steps"]))

    def test_apply_sends_posts_and_refuses_when_server_read_only_or_invalid(self):
        client = FakeClient(json_map={
            "/api/status": {"type": "usb", "allow_write": True},
            "/api/props": self.USB_PROPS,
        }, allow_write=True)
        res = _call(client, "camera_configure", {
            "settings": {"focusmode": "MF", "stabilizer": "Off"},
            "apply": True,
        }, allow_write=True)
        self.assertFalse(res["isError"])
        data = _json_payload(res)
        self.assertTrue(data["applied"])
        self.assertEqual(client.posts, [
            ("/api/set", {"prop": "focusmode", "value": "1"}),
            ("/api/set", {"prop": "stabilizer", "value": "0"}),
        ])

        # Server read-only refuses apply
        ro_srv = FakeClient(json_map={
            "/api/status": {"type": "usb", "allow_write": False},
            "/api/props": self.USB_PROPS,
        }, allow_write=True)
        res2 = _call(ro_srv, "camera_configure", {"settings": {"focusmode": "MF"}, "apply": True}, allow_write=True)
        self.assertTrue(res2["isError"])
        self.assertEqual(ro_srv.posts, [])

        # Invalid value refuses entire apply
        bad = FakeClient(json_map={
            "/api/status": {"type": "usb", "allow_write": True},
            "/api/props": self.USB_PROPS,
        }, allow_write=True)
        res3 = _call(bad, "camera_configure", {"settings": {"focusmode": "MF", "focalvalue": "0.95"}, "apply": True},
                     allow_write=True)
        self.assertTrue(res3["isError"])
        self.assertEqual(bad.posts, [])

    def test_wifi_apply_switches_takemode_first_then_rereads_props(self):
        props_a = {
            "takemode": {"value": "A", "writable": True, "enum": ["P", "A", "S", "M"]},
            "shutspeedvalue": {"value": "1/250", "writable": False, "enum": []},
        }
        props_m = {
            "takemode": {"value": "M", "writable": True, "enum": ["P", "A", "S", "M"]},
            "shutspeedvalue": {"value": "1/250", "writable": True, "enum": ["1/250", "15", "livecomp"]},
        }
        client = FakeClient(json_map={
            "/api/status": {"type": "wifi", "allow_write": True},
            "/api/props": props_a,
        }, allow_write=True)
        def on_post(path, payload):
            if payload.get("prop") == "takemode" and payload.get("value") == "M":
                client.json_map["/api/props"] = props_m
            return {"ok": True}
        client.post_hook = on_post

        res = _call(client, "camera_configure", {"settings": {"takemode": "M", "shutspeedvalue": "15"}, "apply": True},
                    allow_write=True)
        self.assertFalse(res["isError"])
        self.assertEqual(client.posts, [
            ("/api/set", {"prop": "takemode", "value": "M"}),
            ("/api/set", {"prop": "shutspeedvalue", "value": "15"}),
        ])


class PromptsStatsAndLenses(unittest.TestCase):
    def test_prompts_list_and_get_reflect_write_mode(self):
        ro = mcp_server.McpServer(FakeClient(), allow_write=False)
        init = ro.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertIn("prompts", init["result"]["capabilities"])
        plist = ro.handle_message({"jsonrpc": "2.0", "id": 2, "method": "prompts/list"})["result"]["prompts"]
        self.assertEqual([p["name"] for p in plist], ["setup_for_scene", "check_composition", "critique_last_shot"])

        p_ro = ro.handle_message({"jsonrpc": "2.0", "id": 3, "method": "prompts/get",
                                  "params": {"name": "setup_for_scene", "arguments": {"scene": "stars"}}})["result"]
        self.assertIn("read-only", p_ro["messages"][0]["content"]["text"].lower())

        rw = mcp_server.McpServer(FakeClient(), allow_write=True)
        p_rw = rw.handle_message({"jsonrpc": "2.0", "id": 4, "method": "prompts/get",
                                  "params": {"name": "setup_for_scene", "arguments": {"scene": "sunset"}}})["result"]
        self.assertIn("camera_configure", p_rw["messages"][0]["content"]["text"])

        missing = ro.handle_message({"jsonrpc": "2.0", "id": 5, "method": "prompts/get",
                                     "params": {"name": "setup_for_scene", "arguments": {}}})
        self.assertEqual(missing["error"]["code"], -32602)

    def test_image_stats_measures_clipping_and_median(self):
        import numpy as np
        from PIL import Image
        arr = np.full((64, 64), 100, dtype=np.uint8)
        arr[:8, :] = 255   # 12.5% bright highlights
        arr[-8:, :] = 0    # 12.5% crushed shadows
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="JPEG", quality=95)
        st = mcp_server.image_stats(buf.getvalue())
        self.assertIsNotNone(st)
        self.assertGreater(st["clipped_highlights_pct"], 8.0)
        self.assertGreater(st["crushed_shadows_pct"], 8.0)
        self.assertAlmostEqual(st["median_luma"], 100.0, delta=5.0)

    def test_my_lenses_included_in_camera_status(self):
        client = FakeClient(json_map={
            "/api/app": {"app": "em1-capture", "version": __version__, "allow_write": False},
            "/api/status": mcp_server.ApiError("Not connected", status=409),
            "/api/connections": {"connected": None, "usb": False, "wifi": False},
        })
        res = _call(client, "camera_status", lenses=["M.12-40mm F2.8", "M.45mm F1.8"])
        data = _json_payload(res)
        self.assertEqual(data["my_lenses"], ["M.12-40mm F2.8", "M.45mm F1.8"])


if __name__ == "__main__":
    unittest.main()
