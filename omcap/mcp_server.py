"""Read-only MCP server (Model Context Protocol, stdio) for E-M1 Capture (REQ-F35).

Talks only to the running E-M1 Capture web app over local HTTP (GET only) and never accesses
the camera or card directly. All safety rules and mode checks stay in one place (omcap.server).

Usage:
  .venv/bin/python -B -m omcap.mcp_server
  .venv/bin/em1-capture-mcp --url http://127.0.0.1:8765
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

DEFAULT_URL = "http://127.0.0.1:8765"
PROTOCOL_VERSION = "2025-03-26"
SUPPORTED_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
MAX_IMAGE_BYTES = 12 << 20  # 12 MB cap for base64 image responses over stdio
MAX_LIST_LIMIT = 200

INSTRUCTIONS = (
    "Read-only interface to a running E-M1 Capture server (Olympus OM-D E-M1 Mark I over USB or Wi-Fi). "
    "Use these tools to inspect camera status, settings, lens, live view frame, card list and recent pictures. "
    "This server cannot change camera settings, focus or release the shutter."
)


class ApiError(Exception):
    """Error talking to the local E-M1 Capture HTTP API."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def validate_url(url):
    """Ensure the MCP server only talks to a local HTTP E-M1 Capture instance (loopback only)."""
    parsed = urllib.parse.urlparse((url or "").strip())
    if parsed.scheme != "http":
        raise ValueError("E-M1 Capture URL must use http:// (got %r)" % (url,))
    if parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError("E-M1 Capture URL must point to 127.0.0.1 or localhost (got %r)" % (parsed.hostname,))
    if parsed.username or parsed.password:
        raise ValueError("E-M1 Capture URL must not contain credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("E-M1 Capture URL must not include a path or query")
    port = parsed.port
    if port is None:
        raise ValueError("E-M1 Capture URL must include a port (e.g. %s)" % DEFAULT_URL)
    return "http://%s:%d" % (parsed.hostname, port)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Unexpected redirect", headers, fp)


class HttpClient:
    """Thin GET-only client for the local E-M1 Capture HTTP API."""

    def __init__(self, base_url=DEFAULT_URL, timeout=10.0):
        self.base_url = validate_url(base_url)
        self.timeout = timeout
        # Ignore system proxy env vars on loopback and refuse redirects off localhost
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _build_url(self, path, query=None):
        url = self.base_url + path
        if query:
            items = [(k, v) for k, v in query.items() if v is not None]
            if items:
                url += "?" + urllib.parse.urlencode(items, safe="/")
        return url

    def get_bytes(self, path, query=None, timeout=None, max_bytes=None):
        """HTTP GET returning (status, bytes, headers_lower). Never sends POST or non-GET."""
        url = self._build_url(path, query)
        req = urllib.request.Request(url, method="GET")
        try:
            with self._opener.open(req, timeout=timeout or self.timeout) as resp:
                headers = {k.lower(): v for k, v in resp.headers.items()}
                if max_bytes is not None:
                    cl = headers.get("content-length")
                    if cl and cl.isdigit() and int(cl) > max_bytes:
                        raise ApiError("Image exceeds %d MB limit" % (max_bytes >> 20), status=resp.status)
                    data = resp.read(max_bytes + 1)
                    if len(data) > max_bytes:
                        raise ApiError("Image exceeds %d MB limit" % (max_bytes >> 20), status=resp.status)
                else:
                    data = resp.read()
                return resp.status, data, headers
        except urllib.error.HTTPError as e:
            msg = self._extract_error(e)
            raise ApiError(msg, status=e.code)
        except (urllib.error.URLError, OSError) as e:
            raise ApiError(
                "E-M1 Capture is not running at %s (%s). Start it first (e.g. em1-capture)."
                % (self.base_url, getattr(e, "reason", e))
            )

    def get_json(self, path, query=None, timeout=None):
        """HTTP GET returning parsed JSON."""
        status, data, _ = self.get_bytes(path, query=query, timeout=timeout)
        if not data:
            raise ApiError("Empty JSON response from %s (HTTP %s)" % (path, status), status=status)
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise ApiError("Invalid JSON from %s: %s" % (path, e), status=status)

    @staticmethod
    def _extract_error(err):
        try:
            raw = err.read()
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, dict) and payload.get("error"):
                return str(payload["error"])
        except Exception:
            pass
        return "HTTP %d from E-M1 Capture" % err.code


# --- Helpers -------------------------------------------------------------------------------------

def _text(obj):
    return [{"type": "text", "text": obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2)}]


def _image(data, mime="image/jpeg"):
    return {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": mime}


def _is_jpg(path):
    return bool(path) and path.lower().endswith((".jpg", ".jpeg"))


def _optional_json(client, path, query=None):
    try:
        return client.get_json(path, query=query)
    except ApiError:
        return None


def _newest_jpg(images):
    for entry in images or ():
        if _is_jpg(entry.get("path")):
            return entry["path"]
    return None


def _format_prop(entry, include_enum=False):
    val = entry.get("value")
    names = entry.get("names") or {}
    out = {"value": val, "writable": bool(entry.get("writable"))}
    if str(val) in names:
        out["label"] = names[str(val)]
    if include_enum:
        out["enum"] = entry.get("enum") or []
        if names:
            out["names"] = names
    return out


# --- Read-only tools -----------------------------------------------------------------------------

def tool_camera_status(client, args):
    fresh_device = bool(args.get("fresh_device", False))
    app = client.get_json("/api/app")
    try:
        status = client.get_json("/api/status")
    except ApiError as e:
        if e.status == 409:
            conns = _optional_json(client, "/api/connections")
            return _text({"connected": False, "app": app, "connections": conns})
        raise

    state = client.get_json("/api/state")
    gone = bool(state.get("gone"))
    dev = None if gone else _optional_json(client, "/api/device", {"fresh": "1"} if fresh_device else None)
    af = None if gone else _optional_json(client, "/api/afarea")

    lens = None
    if not gone:
        if status.get("type") == "usb":
            res = _optional_json(client, "/api/lens")
            lens = res.get("lens") if isinstance(res, dict) else None
        else:
            cached = _optional_json(client, "/api/images", {"cached": "1"})
            jpg = _newest_jpg(cached)
            if jpg:
                res = _optional_json(client, "/api/lens", {"path": jpg})
                lens = res.get("lens") if isinstance(res, dict) else None

    level = None
    if not gone and status.get("type") == "usb" and state.get("live") and "level" in (status.get("features") or ()):
        level = _optional_json(client, "/api/level")

    result = {
        "connected": True,
        "app": app,
        "connection": {
            "type": status.get("type"),
            "model": status.get("model"),
            "allow_write": bool(status.get("allow_write")),
            "usb_backend": status.get("usb_backend"),
            "features": status.get("features") or [],
        },
        "live_view": {
            "running": bool(state.get("live")),
            "size": state.get("lvqty"),
            "age_s": round(state["lv_age"], 2) if isinstance(state.get("lv_age"), (int, float)) else None,
            "perf": state.get("lvperf"),
            "loupe": bool(state.get("loupe")),
            "loupe_ratio": state.get("loupe_ratio") if state.get("loupe") else None,
            "live_values": state.get("lvinfo"),
        },
        "camera_state": {
            "busy": bool(state.get("busy")),
            "gone": bool(state.get("gone")),
            "shutter_stage": state.get("stage"),
            "play_mode": bool(state.get("play")),
            "card_present": state.get("card"),
            "movie_s": round(state["movie"], 1) if isinstance(state.get("movie"), (int, float)) else None,
            "long_exposure_s": round(state["take"], 1) if isinstance(state.get("take"), (int, float)) else None,
            "transfer": state.get("transfer"),
            "latest_saved": state.get("latest"),
            "fast_shot_ready": bool(state.get("fast_n")),
        },
        "lens": lens,
        "device": dev,
        "af_area": af,
    }
    if level is not None:
        result["level"] = level
    return _text(result)


def tool_camera_settings(client, args):
    props = client.get_json("/api/props")
    prop = args.get("prop")
    if prop is not None:
        if not isinstance(prop, str) or not prop.strip():
            raise ValueError("'prop' must be a non-empty string")
        prop = prop.strip()
        if prop not in props:
            raise ApiError("Unknown setting %r. Available: %s" % (prop, ", ".join(sorted(props))))
        return _text({prop: _format_prop(props[prop], include_enum=True)})
    return _text({k: _format_prop(v, include_enum=False) for k, v in props.items()})


def tool_live_view_frame(client, args):
    state = client.get_json("/api/state")
    if not state.get("live"):
        raise ApiError("Live view is not running. Start Live View in E-M1 Capture first (this MCP server is read-only).")
    status, data, headers = client.get_bytes("/live.jpg", {"seq": "0"}, timeout=5.0, max_bytes=MAX_IMAGE_BYTES)
    if status == 204 or not data:
        raise ApiError("No live view frame arrived within the timeout.")
    meta = {
        "seq": int(headers["x-seq"]) if headers.get("x-seq", "").isdigit() else None,
        "loupe": headers.get("x-loupe") == "1",
        "size": state.get("lvqty"),
        "live_values": state.get("lvinfo"),
        "bytes": len(data),
    }
    return [_image(data), *_text(meta)]


def tool_list_card_images(client, args):
    raw_limit = args.get("limit", 20)
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
        raise ValueError("'limit' must be an integer")
    limit = max(1, min(raw_limit, MAX_LIST_LIMIT))
    fresh = bool(args.get("fresh", False))
    folder = args.get("dir", "/DCIM")
    if not isinstance(folder, str) or not folder.startswith("/"):
        raise ValueError("'dir' must be a card path starting with '/'")

    used_cache = False
    if not fresh and folder == "/DCIM":
        imgs = client.get_json("/api/images", {"cached": "1"})
        if imgs:
            used_cache = True
        else:
            imgs = client.get_json("/api/images", {"dir": folder}, timeout=30.0)
    else:
        imgs = client.get_json("/api/images", {"dir": folder}, timeout=30.0)

    items = [
        {k: e.get(k) for k in ("path", "name", "size", "date", "time") if e.get(k) is not None}
        for e in imgs[:limit]
    ]
    return _text({"total": len(imgs), "shown": len(items), "cached": used_cache, "images": items})


def _resolve_picture(client, path_arg):
    """Resolve explicit path or the most recent shot across USB (fast/card/direct) and Wi-Fi."""
    if path_arg is not None:
        if not isinstance(path_arg, str) or not path_arg.startswith("/"):
            raise ValueError("'path' must be a camera card path starting with '/'")
        return {"path": path_arg, "fast": False, "local": None}

    last = client.get_json("/api/lastshot") or {}
    if last.get("path") or last.get("fast"):
        return {"path": last.get("path"), "fast": bool(last.get("fast")), "local": None}

    state = _optional_json(client, "/api/state") or {}
    if state.get("card") is False and state.get("latest"):
        return {"path": None, "fast": False, "local": state["latest"]}

    imgs = _optional_json(client, "/api/images", {"cached": "1"}) or []
    if not imgs:
        imgs = _optional_json(client, "/api/images") or []
    jpg = _newest_jpg(imgs)
    if jpg:
        return {"path": jpg, "fast": False, "local": None}
    if imgs and imgs[0].get("path"):
        return {"path": imgs[0]["path"], "fast": False, "local": None}
    if state.get("latest"):
        return {"path": None, "fast": False, "local": state["latest"]}
    raise ApiError("No picture found on the card or in the current session.")


def tool_last_picture(client, args):
    preview = args.get("preview", "auto")
    if preview not in ("auto", "thumb", "full", "none"):
        raise ValueError("'preview' must be one of: auto, thumb, full, none")
    target = _resolve_picture(client, args.get("path"))
    card_path, has_fast, local_name = target["path"], target["fast"], target["local"]

    exif_data, exif_note = None, None
    if card_path:
        if _is_jpg(card_path):
            res = _optional_json(client, "/api/exif", {"path": card_path})
            exif_data = res.get("exif") if isinstance(res, dict) else None
        else:
            exif_note = "EXIF shooting data is only read from JPG files."

    img_bytes, source = None, None
    if preview != "none":
        if preview == "auto":
            if has_fast:
                try:
                    _, img_bytes, _ = client.get_bytes("/api/lastfast", max_bytes=MAX_IMAGE_BYTES)
                    source = "lastfast"
                except ApiError:
                    img_bytes = None
            if img_bytes is None and card_path:
                _, img_bytes, _ = client.get_bytes("/api/thumb", {"path": card_path}, max_bytes=MAX_IMAGE_BYTES)
                source = "thumb"
            elif img_bytes is None and local_name:
                quoted = urllib.parse.quote(local_name, safe="")
                _, img_bytes, _ = client.get_bytes("/captures/" + quoted, max_bytes=MAX_IMAGE_BYTES)
                source = "captures"
        elif preview == "thumb":
            if not card_path:
                raise ApiError("Thumbnail requires a picture path on the camera card.")
            _, img_bytes, _ = client.get_bytes("/api/thumb", {"path": card_path}, max_bytes=MAX_IMAGE_BYTES)
            source = "thumb"
        elif preview == "full":
            if card_path:
                if not _is_jpg(card_path):
                    raise ApiError("Full preview is only supported for JPG files (not ORF).")
                _, img_bytes, _ = client.get_bytes("/api/full", {"path": card_path}, timeout=30.0,
                                                   max_bytes=MAX_IMAGE_BYTES)
                source = "full"
            elif local_name:
                quoted = urllib.parse.quote(local_name, safe="")
                _, img_bytes, _ = client.get_bytes("/captures/" + quoted, max_bytes=MAX_IMAGE_BYTES)
                source = "captures"
            else:
                raise ApiError("Full preview requires a JPG on the card or in captures/.")

    if preview != "none" and img_bytes is None and exif_data is None:
        raise ApiError("Picture preview is no longer available.")

    meta = {"path": card_path, "local": local_name, "source": source,
            "bytes": len(img_bytes) if img_bytes else None, "exif": exif_data}
    if exif_note:
        meta["exif_note"] = exif_note
    content = [_image(img_bytes)] if img_bytes else []
    content.extend(_text(meta))
    return content


# --- Tool registry & JSON-RPC dispatch -----------------------------------------------------------

def _schema(properties=None, required=None):
    s = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        s["required"] = list(required)
    return s


READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

TOOLS = {
    "camera_status": (
        "Read the E-M1 Capture connection status, camera model, live view state, active lens, "
        "AF area, free card space, rough body battery (USB) and level gauge (USB live view). "
        "If no camera is connected yet, returns available USB/Wi-Fi connections.",
        _schema({"fresh_device": {"type": "boolean", "description": "Refresh cached card space and battery."}}),
        tool_camera_status,
    ),
    "camera_settings": (
        "Read the camera's LV super control panel settings (mode, shutter speed, aperture, ISO, WB, "
        "drive, Picture Mode, AF mode, etc.). Omit 'prop' for a compact overview of all settings; pass "
        "'prop' to also receive its allowed values (enum).",
        _schema({"prop": {"type": "string", "description": "Optional setting name, e.g. shutspeedvalue, isospeedvalue."}}),
        tool_camera_settings,
    ),
    "live_view_frame": (
        "Fetch the current JPEG frame from the running live view together with frame metadata "
        "(size, zoom state, and Wi-Fi live exposure/focal values). Does not start live view.",
        _schema(),
        tool_live_view_frame,
    ),
    "list_card_images": (
        "List pictures on the camera card (newest first). Uses the saved card list by default for "
        "instant answers; set fresh=true to query the camera card.",
        _schema({
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIST_LIMIT,
                      "description": "Maximum number of entries to return (default 20)."},
            "fresh": {"type": "boolean", "description": "Read the live list from the camera instead of the cache."},
            "dir": {"type": "string", "description": "Card directory to list (default /DCIM)."},
        }),
        tool_list_card_images,
    ),
    "last_picture": (
        "Inspect the most recent shot (or a specific card path) with EXIF shooting data and an "
        "optional JPEG preview ('auto' uses the fast shot preview or thumbnail; 'full' loads the full JPG "
        "for checking sharpness; 'none' returns EXIF metadata only).",
        _schema({
            "path": {"type": "string", "description": "Optional camera card path, e.g. /DCIM/100OLYMP/PB220001.JPG."},
            "preview": {"type": "string", "enum": ["auto", "thumb", "full", "none"],
                        "description": "Preview size to return (default 'auto')."},
        }),
        tool_last_picture,
    ),
}


class McpServer:
    """Stateless JSON-RPC 2.0 handler for the read-only MCP tools."""

    def __init__(self, client):
        self.client = client

    def handle_message(self, msg):
        """Process one decoded JSON-RPC message. Returns a response dict, or None for notifications."""
        if not isinstance(msg, dict):
            return self._error(None, -32600, "Invalid Request: expected a JSON object")
        mid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params")
        if params is None:
            params = {}
        if not isinstance(method, str) or not isinstance(params, dict):
            return None if mid is None else self._error(mid, -32600, "Invalid Request")
        # JSON-RPC notifications have no "id" and must not receive a response
        if mid is None:
            return None
        try:
            result = self._dispatch(method, params)
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except _RpcError as e:
            return self._error(mid, e.code, str(e))

    def _dispatch(self, method, params):
        if method == "initialize":
            req_ver = params.get("protocolVersion")
            ver = req_ver if req_ver in SUPPORTED_PROTOCOLS else PROTOCOL_VERSION
            return {
                "protocolVersion": ver,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "em1-capture", "version": __version__},
                "instructions": INSTRUCTIONS,
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": name,
                        "description": desc,
                        "inputSchema": schema,
                        "annotations": dict(READ_ONLY_ANNOTATIONS),
                    }
                    for name, (desc, schema, _) in TOOLS.items()
                ]
            }
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments")
            if args is None:
                args = {}
            if not isinstance(name, str) or name not in TOOLS:
                raise _RpcError(-32602, "Unknown tool: %r" % (name,))
            if not isinstance(args, dict):
                raise _RpcError(-32602, "Tool arguments must be an object")
            allowed = set(TOOLS[name][1]["properties"])
            extra = sorted(set(args) - allowed)
            if extra:
                raise _RpcError(-32602, "Unexpected argument(s) for %s: %s" % (name, ", ".join(extra)))
            try:
                content = TOOLS[name][2](self.client, args)
                return {"content": content, "isError": False}
            except (ApiError, ValueError) as e:
                return {"content": _text("Error: %s" % e), "isError": True}
        raise _RpcError(-32601, "Method not found: %s" % method)

    @staticmethod
    def _error(mid, code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


class _RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def serve(server, stdin=None, stdout=None):
    """Run the newline-delimited JSON-RPC stdio loop."""
    inp = stdin if stdin is not None else sys.stdin
    out = stdout if stdout is not None else sys.stdout
    for raw in inp:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError as e:
            reply = McpServer._error(None, -32700, "Parse error: %s" % e)
        else:
            reply = server.handle_message(msg)
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False) + "\n")
            out.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="em1-capture-mcp",
        description="Read-only MCP server (stdio) talking to a running local E-M1 Capture web app.",
    )
    ap.add_argument(
        "--url",
        default=os.environ.get("OMCAP_URL", DEFAULT_URL),
        help="Local E-M1 Capture URL (default: %s, or OMCAP_URL)" % DEFAULT_URL,
    )
    args = ap.parse_args(argv)
    try:
        client = HttpClient(args.url)
    except ValueError as e:
        ap.error(str(e))
    serve(McpServer(client))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
