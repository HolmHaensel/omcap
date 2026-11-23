"""MCP server (Model Context Protocol, stdio) for E-M1 Capture (REQ-F35).

Starts read-only by default (5 read-only tools + 3 Photo Coach prompts).
With `--allow-write` (and E-M1 Capture also running with `--allow-write`), adds the
`camera_configure` tool (dry-run by default; applies settings only with `apply=true`
after explicit user confirmation).

Talks only to the running E-M1 Capture web app over local HTTP (loopback 127.0.0.1 /
localhost only) and never accesses the camera, firmware or card directly. Never exposes
shutter release, card erase or power-off.

Usage:
  .venv/bin/python -B -m omcap.mcp_server                          # read-only (default)
  .venv/bin/python -B -m omcap.mcp_server --allow-write            # + camera_configure
  .venv/bin/em1-capture-mcp --url http://127.0.0.1:8765 --lenses "12-40mm f/2.8, 45mm f/1.8"
"""
import argparse
import base64
import io
import json
import os
import sys
import traceback
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
WRITE_ENDPOINTS = frozenset({"/api/set"})  # strict allowlist: settings only, never shoot/erase/poweroff

INSTRUCTIONS_RO = (
    "Read-only AI Photo Coach interface to a running E-M1 Capture server (Olympus OM-D E-M1 Mark I "
    "over USB or Wi-Fi). Use these tools to inspect camera status, settings, lens, live view frame "
    "(with exposure statistics), card list and recent pictures. This server is read-only and cannot "
    "change camera settings, focus or release the shutter."
)

INSTRUCTIONS_RW = (
    "AI Photo Coach interface to a running E-M1 Capture server (Olympus OM-D E-M1 Mark I over USB "
    "or Wi-Fi). Inspect status, settings, live view and shots freely. To configure the camera, ALWAYS "
    "call camera_configure with apply=false first to build a validated plan, present the exact changes "
    "(and any manual steps such as turning the mode dial over USB) to the user, and call "
    "camera_configure with apply=true ONLY after the user explicitly confirms. This server never "
    "releases the shutter, erases card files or touches firmware."
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
    """Thin client for the local E-M1 Capture HTTP API (GET always; allowlisted POST only with allow_write)."""

    def __init__(self, base_url=DEFAULT_URL, timeout=10.0, allow_write=False):
        self.base_url = validate_url(base_url)
        self.timeout = timeout
        self.allow_write = bool(allow_write)
        # Ignore system proxy env vars on loopback and refuse redirects off localhost
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _build_url(self, path, query=None):
        url = self.base_url + path
        if query:
            items = [(k, v) for k, v in query.items() if v is not None]
            if items:
                url += "?" + urllib.parse.urlencode(items, safe="/")
        return url

    def _open(self, req, timeout=None, max_bytes=None):
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
            raise ApiError(self._extract_error(e), status=e.code)
        except (urllib.error.URLError, OSError) as e:
            raise ApiError(
                "E-M1 Capture is not running at %s (%s). Start it first (e.g. em1-capture)."
                % (self.base_url, getattr(e, "reason", e))
            )

    def get_bytes(self, path, query=None, timeout=None, max_bytes=None):
        """HTTP GET returning (status, bytes, headers_lower)."""
        req = urllib.request.Request(self._build_url(path, query), method="GET")
        return self._open(req, timeout=timeout, max_bytes=max_bytes)

    def get_json(self, path, query=None, timeout=None):
        """HTTP GET returning parsed JSON."""
        status, data, _ = self.get_bytes(path, query=query, timeout=timeout)
        if not data:
            raise ApiError("Empty JSON response from %s (HTTP %s)" % (path, status), status=status)
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise ApiError("Invalid JSON from %s: %s" % (path, e), status=status)

    def post_json(self, path, payload, timeout=None):
        """HTTP POST strictly gated by allow_write and WRITE_ENDPOINTS allowlist."""
        if not self.allow_write:
            raise ApiError("MCP server is read-only. Restart with --allow-write to configure settings.", status=403)
        if path not in WRITE_ENDPOINTS:
            raise ApiError("Endpoint %s is not allowed from MCP" % path, status=403)
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._build_url(path),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        status, data, _ = self._open(req, timeout=timeout)
        if not data:
            return {"ok": True}
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


def image_stats(jpeg_bytes):
    """Compute objective exposure statistics from JPEG bytes when numpy + Pillow/imageio exist; else None."""
    if not jpeg_bytes:
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    arr = None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(jpeg_bytes)) as im:
            im.thumbnail((640, 640))
            arr = np.asarray(im.convert("L"), dtype=np.uint8)
    except ImportError:
        try:
            import imageio.v2 as imageio
            raw = np.asarray(imageio.imread(io.BytesIO(jpeg_bytes)))
            if raw.ndim == 3:
                arr = (0.299 * raw[..., 0] + 0.587 * raw[..., 1] + 0.114 * raw[..., 2]).astype(np.uint8)
            else:
                arr = raw.astype(np.uint8)
        except Exception:
            return None
    except Exception:
        return None
    if arr is None or arr.size == 0:
        return None
    n = float(arr.size)
    p5, p50, p95 = np.percentile(arr, [5, 50, 95])
    return {
        "median_luma": round(float(p50), 1),
        "mean_luma": round(float(arr.mean()), 1),
        "clipped_highlights_pct": round(float((arr >= 250).sum()) / n * 100.0, 2),
        "crushed_shadows_pct": round(float((arr <= 5).sum()) / n * 100.0, 2),
        "p5": round(float(p5), 1),
        "p95": round(float(p95), 1),
    }


def _resolve_setting_value(entry, wanted):
    """Match a user/AI setting value against a camera property's enum or human-readable names."""
    choices = [str(c) for c in (entry.get("enum") or ())]
    names = {str(k): str(v) for k, v in (entry.get("names") or {}).items()}
    raw = str(wanted).strip()
    if raw in choices:
        return raw
    low = raw.lower()
    # Direct case-insensitive enum match (e.g. "auto" -> "Auto", "livecomp" -> "livecomp")
    for c in choices:
        if c.lower() == low:
            return c
    # Strip common prefixes like "f/" or "iso "
    stripped = low[2:].strip() if low.startswith("f/") else (low[4:].strip() if low.startswith("iso ") else low)
    for c in choices:
        if c.lower() == stripped:
            return c
    # Numbers written differently ("8" for the camera's "8.0", "f/8")
    try:
        num = float(stripped)
    except ValueError:
        num = None
    if num is not None:
        for c in choices:
            try:
                if abs(float(c) - num) < 0.01:
                    return c
            except ValueError:
                continue
    # Match human-readable USB display names (e.g. "MF" -> "1", "S-AF+MF" -> "32769", "Natural" -> "33537")
    for code, label in names.items():
        if label.lower() == low and (not choices or code in choices):
            return code
    return None


# --- Tools ---------------------------------------------------------------------------------------

def tool_camera_status(client, args, ctx):
    fresh_device = bool(args.get("fresh_device", False))
    app = client.get_json("/api/app")
    try:
        status = client.get_json("/api/status")
    except ApiError as e:
        if e.status == 409:
            conns = _optional_json(client, "/api/connections")
            out = {"connected": False, "app": app, "connections": conns}
            if ctx.get("lenses"):
                out["my_lenses"] = list(ctx["lenses"])
            return _text(out)
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
        "mcp_allow_write": bool(ctx.get("allow_write")),
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
            "gone": gone,
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
    if ctx.get("lenses"):
        result["my_lenses"] = list(ctx["lenses"])
    return _text(result)


def tool_camera_settings(client, args, ctx):
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


def tool_live_view_frame(client, args, ctx):
    state = client.get_json("/api/state")
    if not state.get("live"):
        raise ApiError("Live view is not running. Start Live View in E-M1 Capture first.")
    status, data, headers = client.get_bytes("/live.jpg", {"seq": "0"}, timeout=5.0, max_bytes=MAX_IMAGE_BYTES)
    if status == 204 or not data:
        raise ApiError("No live view frame arrived within the timeout.")
    meta = {
        "seq": int(headers["x-seq"]) if headers.get("x-seq", "").isdigit() else None,
        "loupe": headers.get("x-loupe") == "1",
        "size": state.get("lvqty"),
        "live_values": state.get("lvinfo"),
        "bytes": len(data),
        "stats": image_stats(data),
    }
    return [_image(data), *_text(meta)]


def _dos_datetime(date, time_):
    """Card list date/time as the camera sends them (FAT/DOS packed integers) -> "YYYY-MM-DD HH:MM:SS"."""
    if not isinstance(date, int) or not isinstance(time_, int) or not date:
        return None
    return "%04d-%02d-%02d %02d:%02d:%02d" % (1980 + (date >> 9), (date >> 5) & 15, date & 31,
                                              time_ >> 11, (time_ >> 5) & 63, (time_ & 31) * 2)


def tool_list_card_images(client, args, ctx):
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

    items = []
    for e in imgs[:limit]:
        item = {k: e.get(k) for k in ("path", "name", "size") if e.get(k) is not None}
        taken = _dos_datetime(e.get("date"), e.get("time"))
        if taken:
            item["taken"] = taken
        items.append(item)
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


def tool_last_picture(client, args, ctx):
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

    meta = {
        "path": card_path,
        "local": local_name,
        "source": source,
        "bytes": len(img_bytes) if img_bytes else None,
        "stats": image_stats(img_bytes) if img_bytes else None,
        "exif": exif_data,
    }
    if exif_note:
        meta["exif_note"] = exif_note
    content = [_image(img_bytes)] if img_bytes else []
    content.extend(_text(meta))
    return content


PASM = ("P", "A", "S", "M")
# Where the E-M1 lets you select a setting: (still photo modes, movie exposure modes). Same rules as FEATURES.show
# in omcap/web/index.html (E-M1 manual p.18, 24, 38-41, 71, 82); keep both in step.
MODE_RULES = {
    "shutspeedvalue": (("S", "M"), ("S", "M")),
    "focalvalue": (("A", "M"), ("A", "M")),
    "expcomp": (("P", "A", "S", "ART"), ("P", "A", "S")),
    "isospeedvalue": (("P", "A", "S", "M", "ART"), ("M",)),
    "wbvalue": (("P", "A", "S", "M", "ART"), PASM),
    "drivemode": (("iAuto", "P", "A", "S", "M", "ART", "B"), ()),
    "colortone": (PASM, ()),
    "artfilter": (("ART",), ()),
    "exposemovie": ((), PASM),
    "focusmode": (PASM, ()), "metering": (PASM, ()), "flashmode": (PASM, ()), "recordmode": (PASM, ()),
    "aspect": (PASM, ()), "stabilizer": (PASM, ()), "facepriority": (PASM, ()), "focusstacking": (PASM, ()),
}
USB_ONLY = ("focusmode", "metering", "flashmode", "recordmode", "aspect", "stabilizer", "facepriority",
            "focusstacking")  # Super Control Panel items without a Wi-Fi command
NOT_WITH_STACKING = ("drivemode", "flashmode")  # hidden while Focus Stacking is On (as on the page)
LONG_SHUTTER = ("livebulb", "livetime", "livecomp")  # BULB, LIVE TIME, LIVECOMP: M only
# The manual's terms, for text the user reads
LABELS = {
    "takemode": "Shooting mode", "shutspeedvalue": "Shutter speed", "focalvalue": "Aperture",
    "expcomp": "Exposure compensation", "isospeedvalue": "ISO", "wbvalue": "WB", "drivemode": "Sequential/Self-timer",
    "colortone": "Picture Mode", "artfilter": "ART filter", "exposemovie": "Movie exposure mode", "focusmode": "AF mode",
    "metering": "Metering", "flashmode": "Flash mode", "recordmode": "Record mode (image quality)",
    "aspect": "Image aspect", "stabilizer": "Image stabilizer", "facepriority": "Face priority",
    "focusstacking": "Focus stacking",
}
MODE_NAMES = {"p": "P", "program": "P", "a": "A", "aperture": "A", "aperture priority": "A", "s": "S",
              "shutter": "S", "shutter priority": "S", "m": "M", "manual": "M", "iauto": "iAuto", "auto": "iAuto",
              "art": "ART", "movie": "movie", "b": "B", "bulb": "B"}


def _label(prop):
    return LABELS.get(prop, prop)


def _norm_mode(value):
    return MODE_NAMES.get(str(value).strip().lower())


def _mode_allows(prop, mode, movie_exp):
    photo, movie = MODE_RULES.get(prop, (None, None))
    if photo is None:
        return True  # no rule known: the camera's writable flag decides
    return movie_exp in movie if mode == "movie" else mode in photo


def _plan_settings(status, props, wanted):
    """Validate requested settings against the camera's props and the E-M1 mode rules.

    Returns changes, unchanged, manual steps, invalid and pending (settings that only become selectable
    after a mode change: checked again once the mode has changed)."""
    conn = status.get("type")
    changes, unchanged, manual_steps, invalid, pending = [], [], [], [], []
    cur_mode = str((props.get("takemode") or {}).get("value"))
    mode = cur_mode
    if "takemode" in wanted:
        val = wanted["takemode"]
        want = _norm_mode(val)
        entry = props.get("takemode") or {}
        if want is None:
            invalid.append({"prop": "takemode", "label": _label("takemode"), "wanted": val,
                            "reason": "Unknown shooting mode (P, A, S, M, iAuto, ART, movie)"})
        elif conn == "usb":
            if want == cur_mode:
                unchanged.append({"prop": "takemode", "value": cur_mode})
            else:
                note = (" Over USB the app reads iAUTO, ART, SCN and PHOTO STORY as P, so it cannot check this turn."
                        if want in ("iAuto", "ART") else "")
                manual_steps.append("Turn the mode dial to %s (the computer cannot change the shooting mode over "
                                    "USB, E-M1 manual p.18).%s" % (want, note))
                mode = want
        else:
            resolved = _resolve_setting_value(entry, want)
            if resolved is None or not entry.get("writable"):
                invalid.append({"prop": "takemode", "label": _label("takemode"), "wanted": val,
                                "reason": "Shooting mode cannot be set to this now"})
            elif resolved == cur_mode:
                unchanged.append({"prop": "takemode", "value": cur_mode})
            else:
                changes.append({"prop": "takemode", "label": _label("takemode"), "current": cur_mode,
                                "target": resolved})
                mode = resolved
    movie_exp = str(wanted.get("exposemovie") or (props.get("exposemovie") or {}).get("value"))
    stacking = str(wanted.get("focusstacking", (props.get("focusstacking") or {}).get("value"))) in ("1", "On", "on")
    for prop in sorted(k for k in wanted if k != "takemode"):
        val = wanted[prop]
        if prop not in props:
            if conn == "wifi" and prop in USB_ONLY:
                manual_steps.append("Set %s to %s on the camera (not available over Wi-Fi)." % (_label(prop), val))
            else:
                invalid.append({"prop": prop, "wanted": val, "reason": "Unknown setting on this connection"})
            continue
        if not _mode_allows(prop, mode, movie_exp):
            invalid.append({"prop": prop, "label": _label(prop), "wanted": val,
                            "reason": "Not selectable in shooting mode %s (E-M1 manual p.18)" % mode})
            continue
        if stacking and prop in NOT_WITH_STACKING:
            invalid.append({"prop": prop, "label": _label(prop), "wanted": val,
                            "reason": "Not selectable while Focus stacking is On"})
            continue
        if mode != cur_mode and not _mode_allows(prop, cur_mode, movie_exp):
            # only selectable after the mode change: the current writable flag and choices say nothing yet
            pending.append({"prop": prop, "label": _label(prop), "wanted": val,
                            "reason": "Checked again after the shooting mode is %s" % mode})
            continue
        entry = props[prop]
        cur = str(entry.get("value"))
        names = {str(k): str(v) for k, v in (entry.get("names") or {}).items()}
        if not entry.get("writable"):
            manual_steps.append("Set %s to %s on the camera (read-only in this mode or connection)."
                                % (_label(prop), val))
            continue
        resolved = _resolve_setting_value(entry, val)
        if resolved is None or (prop == "shutspeedvalue" and resolved in LONG_SHUTTER and mode != "M"):
            sample = [names.get(str(c), str(c)) for c in (entry.get("enum") or ())[:15]]
            invalid.append({"prop": prop, "label": _label(prop), "wanted": val, "reason": "Not in allowed values",
                            "allowed_sample": sample})
            continue
        if resolved == cur:
            unchanged.append({"prop": prop, "value": cur, "label": names.get(cur)})
        else:
            changes.append({
                "prop": prop,
                "label": _label(prop),
                "current": cur,
                "current_label": names.get(cur),
                "target": resolved,
                "target_label": names.get(resolved),
            })
    return changes, unchanged, manual_steps, invalid, pending


def tool_camera_configure(client, args, ctx):
    """Validate (apply=false, default) or apply (apply=true) a set of camera settings via POST /api/set."""
    settings = args.get("settings")
    if not isinstance(settings, dict) or not settings:
        raise ValueError("'settings' must be a non-empty object mapping setting names to target values")
    apply_now = args.get("apply") is True  # only a real JSON true applies ("false" as a string must not)

    status = client.get_json("/api/status")
    props = client.get_json("/api/props")
    changes, unchanged, manual_steps, invalid, pending = _plan_settings(status, props, settings)

    if not apply_now:
        return _text({
            "applied": False,
            "dry_run": True,
            "connection": status.get("type"),
            "server_allow_write": bool(status.get("allow_write")),
            "changes": changes,
            "unchanged": unchanged,
            "manual_steps": manual_steps,
            "pending": pending,
            "invalid": invalid,
            "next_step": "Show this plan to the user and call camera_configure again with apply=true only after explicit confirmation.",
        })

    if not status.get("allow_write"):
        raise ApiError("E-M1 Capture is running read-only. Restart E-M1 Capture with --allow-write first.", status=403)
    if invalid:
        raise ApiError("Refused to apply because some settings are invalid: %s" % json.dumps(invalid))

    applied, failed = [], []
    mode_change = next((c for c in changes if c["prop"] == "takemode"), None)
    if mode_change:  # Wi-Fi: the mode first, then plan the rest again on the new mode's props
        client.post_json("/api/set", {"prop": "takemode", "value": mode_change["target"]})
        applied.append(mode_change)
        rest = {k: v for k, v in settings.items() if k != "takemode"}
        changes, unchanged, manual_steps, invalid, pending = (
            _plan_settings(status, client.get_json("/api/props"), rest) if rest else ([], [], [], [], []))
        if invalid:  # the new mode refuses something: stop after the mode change
            changes = []
    for ch in changes:
        try:
            client.post_json("/api/set", {"prop": ch["prop"], "value": ch["target"]})
            applied.append(ch)
        except ApiError as e:
            failed.append({**ch, "error": str(e)})

    return _text({
        "applied": not failed and not invalid,
        "dry_run": False,
        "connection": status.get("type"),
        "applied_changes": applied,
        "unchanged": unchanged,
        "manual_steps": manual_steps,
        "pending": pending,
        "invalid": invalid,
        "failed": failed,
    })


# --- Photo Coach MCP Prompts ---------------------------------------------------------------------

PROMPTS = {
    "setup_for_scene": {
        "description": "AI Photo Coach: inspect the camera and recommend (or configure after confirmation) E-M1 Mark I settings for a scene such as stars, sunset, portrait or macro.",
        "arguments": [
            {"name": "scene", "description": "What you want to photograph (e.g. stars, sunset, portrait, macro).", "required": True},
            {"name": "notes", "description": "Optional context (tripod vs handheld, available lenses, mood).", "required": False},
        ],
    },
    "check_composition": {
        "description": "AI Photo Coach: inspect the live view frame, exposure clipping stats and USB level gauge to advise on framing, horizon and light.",
        "arguments": [
            {"name": "goal", "description": "Optional creative goal for the frame.", "required": False},
        ],
    },
    "critique_last_shot": {
        "description": "AI Photo Coach: inspect the last picture (full JPG + EXIF + exposure stats) and give concrete advice on sharpness, exposure and next shot.",
        "arguments": [
            {"name": "goal", "description": "Optional intent of the shot.", "required": False},
        ],
    },
}


def render_prompt(name, args, allow_write):
    if name == "setup_for_scene":
        scene = str(args.get("scene") or "").strip()
        if not scene:
            raise _RpcError(-32602, "Prompt 'setup_for_scene' requires argument 'scene'")
        notes = str(args.get("notes") or "").strip()
        cfg_step = (
            "Then call camera_configure with apply=false to prepare a validated change plan, show the exact "
            "changes and any manual camera steps (like turning the mode dial over USB) to the user, and apply "
            "with apply=true ONLY after the user explicitly says yes."
            if allow_write else
            "Give clear step-by-step settings instructions the user can dial in (this MCP session is read-only)."
        )
        text = (
            "You are an expert Olympus OM-D E-M1 Mark I (Micro Four Thirds, 2x crop) photography coach. "
            "The user wants to photograph: %s.%s\n\n"
            "Steps:\n"
            "1. Call camera_status and camera_settings (and live_view_frame if live view is running).\n"
            "2. Check the attached lens (and my_lenses if listed) and advise if another lens would suit the scene better.\n"
            "3. Spot any current camera pitfalls (e.g. S-IS on while on a tripod, JPG-only instead of RAW+JPG, "
            "exposure compensation left non-zero, shutter too slow/too long for stars per MFT NPF rule, "
            "overexposed highlights in sunset/twilight, Live Composite for star trails/light painting).\n"
            "4. Give concise, practical recommendations for mode, aperture, shutter, ISO, WB, AF mode, IS and framing. "
            "Respect the E-M1 mode rules (manual p.18): shutter speed only in S and M, aperture only in A and M, "
            "BULB / LIVE TIME / LIVECOMP only in M; over USB the user turns the mode dial by hand.\n"
            "5. %s"
        ) % (scene, (" Extra context: " + notes) if notes else "", cfg_step)
        return {"description": PROMPTS[name]["description"],
                "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
    if name == "check_composition":
        goal = str(args.get("goal") or "").strip()
        text = (
            "Call camera_status and live_view_frame.%s Review the framing, horizon tilt (from USB level gauge if "
            "present), focal length, foreground/background balance, and the exposure stats (median_luma, "
            "clipped_highlights_pct, crushed_shadows_pct). Give 3-5 specific, actionable improvements."
        ) % ((" Creative goal: " + goal + ".") if goal else "")
        return {"description": PROMPTS[name]["description"],
                "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
    if name == "critique_last_shot":
        goal = str(args.get("goal") or "").strip()
        text = (
            "Call last_picture with preview='full' (falling back to 'auto' if needed).%s Inspect sharpness/focus, "
            "EXIF settings (shutter speed vs focal length, ISO, aperture, EV), clipped highlights / crushed shadows "
            "from stats, and composition. Give honest, constructive feedback and exact changes for the next shot."
        ) % ((" Intent: " + goal + ".") if goal else "")
        return {"description": PROMPTS[name]["description"],
                "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
    raise _RpcError(-32602, "Unknown prompt: %r" % (name,))


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

CONFIGURE_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

READ_TOOLS = {
    "camera_status": (
        "Read the E-M1 Capture connection status, camera model, live view state, active lens, "
        "user's lens bag (if configured), AF area, free card space, rough body battery (USB) and "
        "level gauge (USB live view). If no camera is connected yet, returns available connections.",
        _schema({"fresh_device": {"type": "boolean", "description": "Refresh cached card space and battery."}}),
        READ_ONLY_ANNOTATIONS,
        tool_camera_status,
    ),
    "camera_settings": (
        "Read the camera's LV super control panel settings (mode, shutter speed, aperture, ISO, WB, "
        "drive, Picture Mode, AF mode, IS, etc.). Omit 'prop' for a compact overview of all settings; "
        "pass 'prop' to also receive its allowed values (enum).",
        _schema({"prop": {"type": "string", "description": "Optional setting name, e.g. shutspeedvalue, isospeedvalue."}}),
        READ_ONLY_ANNOTATIONS,
        tool_camera_settings,
    ),
    "live_view_frame": (
        "Fetch the current JPEG frame from the running live view together with objective exposure "
        "statistics (median luma, clipped highlights %, crushed shadows %) and frame metadata. "
        "Does not start live view.",
        _schema(),
        READ_ONLY_ANNOTATIONS,
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
        READ_ONLY_ANNOTATIONS,
        tool_list_card_images,
    ),
    "last_picture": (
        "Inspect the most recent shot (or a specific card path) with EXIF shooting data, exposure "
        "statistics (clipped highlights %, crushed shadows %) and an optional JPEG preview ('auto', "
        "'thumb', 'full' for checking sharpness, or 'none' for metadata only).",
        _schema({
            "path": {"type": "string", "description": "Optional camera card path, e.g. /DCIM/100OLYMP/PB220001.JPG."},
            "preview": {"type": "string", "enum": ["auto", "thumb", "full", "none"],
                        "description": "Preview size to return (default 'auto')."},
        }),
        READ_ONLY_ANNOTATIONS,
        tool_last_picture,
    ),
}

WRITE_TOOLS = {
    "camera_configure": (
        "Validate or apply camera settings for a scene (e.g. stars, sunset, portrait). "
        "Defaults to apply=false (safe dry-run plan showing exact changes, human-readable labels, "
        "and any manual steps such as turning the mode dial over USB). Set apply=true ONLY after "
        "the user has explicitly confirmed the plan. Never releases the shutter or erases files.",
        _schema({
            "settings": {
                "type": "object",
                "description": "Map of setting names to target values or labels, e.g. {'isospeedvalue': '1600', 'focusmode': 'MF', 'stabilizer': 'Off'}.",
            },
            "apply": {
                "type": "boolean",
                "description": "False (default) returns a dry-run plan only; true applies validated changes to the camera.",
            },
        }, required=["settings"]),
        CONFIGURE_ANNOTATIONS,
        tool_camera_configure,
    ),
}


class McpServer:
    """Stateless JSON-RPC 2.0 handler for E-M1 Capture MCP tools and Photo Coach prompts."""

    def __init__(self, client, allow_write=False, lenses=None):
        self.client = client
        self.allow_write = bool(allow_write)
        self.lenses = [s.strip() for s in (lenses or ()) if str(s).strip()]

    def _tools(self):
        if self.allow_write:
            return {**READ_TOOLS, **WRITE_TOOLS}
        return READ_TOOLS

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
        except Exception as e:  # noqa: BLE001 - one bad request must not end the stdio session
            traceback.print_exc(file=sys.stderr)
            return self._error(mid, -32603, "Internal error: %s" % e)

    def _dispatch(self, method, params):
        if method == "initialize":
            req_ver = params.get("protocolVersion")
            ver = req_ver if req_ver in SUPPORTED_PROTOCOLS else PROTOCOL_VERSION
            return {
                "protocolVersion": ver,
                "capabilities": {"tools": {}, "prompts": {}},
                "serverInfo": {"name": "em1-capture", "version": __version__},
                "instructions": INSTRUCTIONS_RW if self.allow_write else INSTRUCTIONS_RO,
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
                        "annotations": dict(ann),
                    }
                    for name, (desc, schema, ann, _) in self._tools().items()
                ]
            }
        if method == "tools/call":
            tools = self._tools()
            name = params.get("name")
            args = params.get("arguments")
            if args is None:
                args = {}
            if not isinstance(name, str) or name not in tools:
                raise _RpcError(-32602, "Unknown tool: %r" % (name,))
            if not isinstance(args, dict):
                raise _RpcError(-32602, "Tool arguments must be an object")
            allowed = set(tools[name][1]["properties"])
            extra = sorted(set(args) - allowed)
            if extra:
                raise _RpcError(-32602, "Unexpected argument(s) for %s: %s" % (name, ", ".join(extra)))
            ctx = {"allow_write": self.allow_write, "lenses": self.lenses}
            try:
                content = tools[name][3](self.client, args, ctx)
                return {"content": content, "isError": False}
            except (ApiError, ValueError) as e:
                return {"content": _text("Error: %s" % e), "isError": True}
            except Exception as e:  # noqa: BLE001 - reported to the AI as a tool error, logged to stderr
                traceback.print_exc(file=sys.stderr)
                return {"content": _text("Error: %s" % e), "isError": True}
        if method == "prompts/list":
            return {
                "prompts": [
                    {"name": name, "description": spec["description"], "arguments": spec["arguments"]}
                    for name, spec in PROMPTS.items()
                ]
            }
        if method == "prompts/get":
            name = params.get("name")
            args = params.get("arguments") or {}
            if not isinstance(name, str) or name not in PROMPTS:
                raise _RpcError(-32602, "Unknown prompt: %r" % (name,))
            if not isinstance(args, dict):
                raise _RpcError(-32602, "Prompt arguments must be an object")
            return render_prompt(name, args, self.allow_write)
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
        description="MCP server (stdio) talking to a running local E-M1 Capture web app (read-only by default).",
    )
    ap.add_argument(
        "--url",
        default=os.environ.get("OMCAP_URL", DEFAULT_URL),
        help="Local E-M1 Capture URL (default: %s, or OMCAP_URL)" % DEFAULT_URL,
    )
    ap.add_argument(
        "--allow-write",
        action="store_true",
        help="Enable camera_configure to change camera settings (E-M1 Capture must also run with --allow-write).",
    )
    ap.add_argument(
        "--lenses",
        default=os.environ.get("OMCAP_LENSES", ""),
        help="Comma-separated list of lenses you own, for Photo Coach recommendations (or OMCAP_LENSES).",
    )
    args = ap.parse_args(argv)
    try:
        client = HttpClient(args.url, allow_write=args.allow_write)
    except ValueError as e:
        ap.error(str(e))
    lenses = [s.strip() for s in args.lenses.split(",") if s.strip()]
    serve(McpServer(client, allow_write=args.allow_write, lenses=lenses))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
