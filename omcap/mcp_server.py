"""MCP server (Model Context Protocol, stdio) for E-M1 Capture (REQ-F35).

Starts read-only by default (5 read-only tools + 3 Photo Coach prompts).
Safety tiers (cumulative, opt-in via CLI flags; E-M1 Capture must also run with `--allow-write`):
  --allow-write   : camera_configure, camera_focus (AF/MF/Star AF/Zoom AF), live_view, playback
                    (Playback, download, HSL, OM Workspace), app_control (connect/disconnect/
                    poweroff/refresh/transfer/save_config). No shutter, no erase.
  --allow-shutter : + camera_shoot (single shot, half-press, BULB/LIVE TIME/LIVECOMP, interval,
                    bracketing, movie, stop_job; dry-run by default, confirm=true to trigger).
  --allow-erase   : + card_erase (USB card erase, Wi-Fi Share Order clear; dry-run by default,
                    confirm=true to execute).

Talks only to the running E-M1 Capture web app over local HTTP (loopback 127.0.0.1 /
localhost only) and never accesses the camera, firmware or card directly. Never exposes
app quit (`/api/quit`) or firmware operations.

Usage:
  .venv/bin/python -B -m omcap.mcp_server                                  # read-only (default)
  .venv/bin/python -B -m omcap.mcp_server --allow-write                    # + configure/focus/live/playback/app
  .venv/bin/python -B -m omcap.mcp_server --allow-write --allow-shutter    # + camera_shoot
  .venv/bin/python -B -m omcap.mcp_server --allow-write --allow-erase      # + card_erase
  .venv/bin/em1-capture-mcp --url http://127.0.0.1:8765 --lenses "12-40mm f/2.8, 45mm f/1.8"
"""
import argparse
import base64
import io
import json
import math
import os
import sys
import time
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
WRITE_ENDPOINTS = frozenset({
    "/api/set",
    "/api/afarea", "/api/mfdrive", "/api/staraf", "/api/loupe",
    "/api/liveview",
    "/api/playback", "/api/download", "/api/hsl", "/api/hslauto", "/api/open",
    "/api/connect", "/api/disconnect", "/api/poweroff",
    "/api/refresh", "/api/transfer", "/api/savecfg",
})  # settings, focus, live view, playback/HSL, app/connection (never /api/quit or firmware)
SHUTTER_ENDPOINTS = frozenset({
    "/api/shoot", "/api/shutter", "/api/take",
    "/api/interval", "/api/bracket", "/api/movie", "/api/job/stop",
})  # only with --allow-shutter (requires --allow-write)
ERASE_ENDPOINTS = frozenset({
    "/api/erase", "/api/shareorder/clear",
})  # only with --allow-erase (requires --allow-write)

# Any wish in words (scene, subject, mood, look, film, a problem like "too dark") -> camera settings.
# A general method; the scenes and looks are examples, not a fixed list. Active without picking a prompt (voice).
TRANSLATE = (
    "Turn any wish in words into camera settings: a scene ('set it up right for now', aurora, kids playing), "
    "a look or mood (a film, a director, 'warm and dreamy'), or a problem ('too dark', 'blurry'). Method: "
    "1) Look: camera_status, camera_settings with choices=true (what is selectable now, with readable labels), "
    "live_view_frame (exposure stats) or last_picture at night, and the lens. "
    "2) Advise first, as a coach: judge honestly whether the wish works with the attached lens (camera_status "
    "lens: focal range, widest aperture; MFT = 2x full-frame equivalent) and the body (E-M1: ISO 200-25600, "
    "clean to about 1600-3200, IS about 4 stops (CIPA), 1/8000-60 s, BULB/LIVE TIME/LIVECOMP), the light and "
    "tripod or handheld. Give a short verdict: works / works with a compromise (name it, e.g. ISO 6400 noise, "
    "less background blur, slower shutter needs a tripod) / better another lens. Then recommend the best lens "
    "from my_lenses if listed, otherwise a lens type (e.g. fast wide prime f/1.8 around 12-17 mm for aurora, "
    "f/1.8 portrait prime 45 mm, 100 mm+ for birds); also say what to change in the setup (tripod, position, "
    "time of day). If the user stays with the current lens, still set up the best possible result. "
    "3) Decide like a professional, in M unless the wish needs otherwise: shutter for the subject (handheld with "
    "IS at least 1/(2 x focal length), people moving 1/250-1/500, sport/birds 1/1000+, tripod as long as needed); "
    "aperture for depth of field (f/1.8-2.8 soft background, f/4-f/8 sharpest; MFT: not past f/11); ISO fixed, "
    "the lowest that works (200 base, 1600 clean, 3200+ only if needed); WB fixed to the light or the look "
    "(warmer = higher kelvin); Picture Mode, Art filter, drive, AF mode, IS and aspect as the wish asks. "
    "4) Map only to values in choices; anything the camera cannot take remotely goes into one short body step "
    "(see body_only), never invented as a setting. "
    "5) camera_configure with apply=false, one short reason per value, apply after the user's yes; over USB the "
    "user turns the mode dial by hand. "
    "6) Check the result after about 2 s (the E-M1 live view settles slowly): live_view_frame (in M it shows the exposure while Live View Boost is Off; median_luma "
    "about 100-140, brighter for high-key looks, lower when large dark areas fill the frame: judge the subject in the image; clipped_highlights_pct under 1 percent) or the last shot; "
    "propose one step (1/3-1 stop) and apply only after a short yes. Keep spoken answers short. "
    "Examples of the method: aurora = tripod, M, widest aperture, ISO 1600-3200, 2-8 s (faster aurora shorter), "
    "WB 3500-4000K, IS off, focus with Star AF; 'Desert Pastel' (Wes Anderson style) = A f/8, +0.3 to +0.7, ISO 200, "
    "WB 6000K, Vivid, body step Contrast -1 / Saturation +1, centred symmetric framing."
)
# Set on the camera body only (no USB or Wi-Fi command known to E-M1 Capture); told to the user as body steps
BODY_ONLY = [
    "Picture Mode details: Contrast, Sharpness, Saturation, Gradation, B&W filter, Pict. Tone",
    "Art filter effects and variations", "Highlight&Shadow Control curve", "Noise Filter, Noise Reduct.",
    "Color Creator hue and saturation", "WB fine-tuning (A/G) and custom kelvin values", "Flash intensity",
]

# Focus, live view, playback and app control come with --allow-write; after settings changes the live view may be
# soft, so focus again before judging sharpness.
CONTROL = (
    "Control: live_view starts/stops live view (with optional size); camera_focus handles AF (point x/y or current "
    "point), USB AF Area mode, USB Focus ring (MF) steps, USB Auto Star AF, and USB Zoom AF (loupe). After settings "
    "changes or when live_view_frame looks soft, focus again with camera_focus before judging sharpness. "
    "playback enters/exits Playback, downloads card files, applies software HSL or opens captures in OM Workspace. "
    "app_control connects/disconnects, refreshes USB state, sets transfer target and save folder/naming, or turns "
    "off the camera over Wi-Fi. Every change to the camera or its mode (live_view start, camera_focus changes, Playback "
    "enter/exit, connect, disconnect, refresh, Turn off camera) is a dry-run first: tell the user, then repeat with "
    "confirm=true after their yes."
)
SHUTTER_RULES = (
    "Shutter: camera_shoot covers single shot (optional self-timer), Press halfway, long exposure (BULB/LIVE TIME/"
    "LIVECOMP in M), Time lapse shooting (interval), AE BKT (exposure bracketing in P/A/S), movie recording, and "
    "stop_job. For any capture start, ALWAYS call without confirm first to get the dry-run plan (including exact "
    "frame count, interval, or EV sequence), tell the user, and call with confirm=true ONLY after their explicit "
    "yes for that specific action (one yes = one named action). Stop actions (stop_job, long_exposure stop, movie "
    "stop, Press halfway release) run immediately."
)
ERASE_RULES = (
    "Erase: card_erase deletes files from the camera card (USB) or runs Reset Share Order (Wi-Fi). ALWAYS call "
    "without confirm first to list the exact files, warn that the action cannot be undone, and call with "
    "confirm=true ONLY after the user's explicit yes."
)

INSTRUCTIONS_RO = (
    "Read-only AI Photo Coach interface to a running E-M1 Capture server (Olympus OM-D E-M1 Mark I "
    "over USB or Wi-Fi). Use these tools to inspect camera status, settings, lens, live view frame "
    "(with exposure statistics), card/local/Share Order lists and recent pictures. This server is read-only "
    "and cannot change camera settings, focus, release the shutter or erase files."
)

INSTRUCTIONS_RW = (
    "AI Photo Coach interface to a running E-M1 Capture server (Olympus OM-D E-M1 Mark I over USB "
    "or Wi-Fi). Inspect status, settings, live view and shots freely. To configure the camera, ALWAYS "
    "call camera_configure with apply=false first to build a validated plan, present the exact changes "
    "(and any manual steps such as turning the mode dial over USB) to the user, and call "
    "camera_configure with apply=true ONLY after the user explicitly confirms. Shutter actions require "
    "--allow-shutter, card erase requires --allow-erase, and app quit or firmware operations are never exposed.\n\n"
    + TRANSLATE + "\n\n" + CONTROL
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
    """Thin client for the local E-M1 Capture HTTP API (GET always; allowlisted POST gated by safety tier)."""

    def __init__(self, base_url=DEFAULT_URL, timeout=10.0, allow_write=False, allow_shutter=False, allow_erase=False):
        self.base_url = validate_url(base_url)
        self.timeout = timeout
        self.allow_write = bool(allow_write)
        self.allow_shutter = bool(allow_shutter) and self.allow_write
        self.allow_erase = bool(allow_erase) and self.allow_write
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
        """HTTP POST strictly gated by allow_write / allow_shutter / allow_erase endpoint allowlists."""
        if not self.allow_write:
            raise ApiError("MCP server is read-only. Restart with --allow-write to control the camera.", status=403)
        allowed = (
            path in WRITE_ENDPOINTS
            or (self.allow_shutter and path in SHUTTER_ENDPOINTS)
            or (self.allow_erase and path in ERASE_ENDPOINTS)
        )
        if not allowed:
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


# Readable names where the connection sends only codes (Wi-Fi WB); same table as FEATURES.wbvalue in index.html
DEFAULT_NAMES = {
    "wbvalue": {"0": "AUTO", "18": "5300K", "16": "7500K", "17": "6000K", "20": "3000K", "35": "4000K",
                "64": "Underwater", "23": "5500K Flash", "256": "One-touch 1", "257": "One-touch 2",
                "258": "One-touch 3", "259": "One-touch 4", "512": "CWB"},
}


def _with_names(prop, entry):
    if entry.get("names") or prop not in DEFAULT_NAMES:
        return entry
    return dict(entry, names=DEFAULT_NAMES[prop])


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
    star_af = None if gone else _optional_json(client, "/api/staraf")
    save_cfg = None if gone else _optional_json(client, "/api/savecfg")
    hsl_info = None if gone else _optional_json(client, "/api/hsl/presets")

    result = {
        "connected": True,
        "app": app,
        "mcp_allow_write": bool(ctx.get("allow_write")),
        "mcp_allow_shutter": bool(ctx.get("allow_shutter")),
        "mcp_allow_erase": bool(ctx.get("allow_erase")),
        "connection": {
            "type": status.get("type"),
            "model": status.get("model"),
            "allow_write": bool(status.get("allow_write")),
            "om_workspace": bool(status.get("om_workspace")),
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
            "job": state.get("job") if (state.get("job") or {}).get("running") else None,
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
    if isinstance(star_af, dict) and (star_af.get("running") or star_af.get("phase") not in (None, "idle")):
        result["star_af"] = star_af
    if isinstance(save_cfg, dict):
        result["save_config"] = save_cfg
    if isinstance(hsl_info, dict):
        result["hsl"] = hsl_info
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
        return _text({prop: _format_prop(_with_names(prop, props[prop]), include_enum=True)})
    if args.get("choices") is True:  # the map an assistant needs to turn a wish into settings
        mode = str((props.get("takemode") or {}).get("value"))
        movie_exp = str((props.get("exposemovie") or {}).get("value"))
        out = {}
        for k, v in props.items():
            if v.get("writable") and _mode_allows(k, mode, movie_exp):
                out[k] = dict(_format_prop(_with_names(k, v), include_enum=True), setting=_label(k))
        return _text({"shooting_mode": mode, "selectable": out, "body_only": BODY_ONLY})
    return _text({k: _format_prop(_with_names(k, v), include_enum=False) for k, v in props.items()})


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
    source = args.get("source", "card")
    if source not in ("card", "local", "share_order"):
        raise ValueError("'source' must be one of: card, local, share_order")
    raw_limit = args.get("limit", 20)
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
        raise ValueError("'limit' must be an integer")
    limit = max(1, min(raw_limit, MAX_LIST_LIMIT))

    if source == "local":
        files = client.get_json("/api/local") or []
        return _text({"source": "local", "total": len(files), "shown": min(len(files), limit), "images": files[:limit]})
    if source == "share_order":
        state = _optional_json(client, "/api/state") or {}
        if state.get("play") is False:
            raise ApiError("Share Order over Wi-Fi requires Playback mode. Call playback(action='enter') first.")
        paths = client.get_json("/api/shareorder") or []
        return _text({"source": "share_order", "total": len(paths), "shown": min(len(paths), limit),
                      "images": paths[:limit]})

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

    exif_data, exif_note, movie_seconds = None, None, None
    if card_path:
        if _is_jpg(card_path):
            res = _optional_json(client, "/api/exif", {"path": card_path})
            exif_data = res.get("exif") if isinstance(res, dict) else None
        elif card_path.lower().endswith(".mov"):
            res = _optional_json(client, "/api/movlength", {"path": card_path})
            movie_seconds = res.get("seconds") if isinstance(res, dict) else None
            exif_note = "EXIF shooting data is only read from JPG files."
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
    if movie_seconds is not None:
        meta["movie_seconds"] = movie_seconds
    content = [_image(img_bytes)] if img_bytes else []
    content.extend(_text(meta))
    return content


PASM = ("P", "A", "S", "M")
# Where the E-M1 lets you select a setting: (still photo modes, movie exposure modes). Same rules as FEATURES.show
# in omcap/web/index.html (E-M1 manual p.18, 24, 38-41, 71, 82); keep both in step.
ANY = "any"  # every movie exposure mode, also when the connection does not report it (USB)
MODE_RULES = {
    "shutspeedvalue": (("S", "M"), ("S", "M")),
    "focalvalue": (("A", "M"), ("A", "M")),
    "expcomp": (("P", "A", "S", "ART"), ("P", "A", "S")),
    "isospeedvalue": (("P", "A", "S", "M", "ART"), ("M",)),
    "wbvalue": (("P", "A", "S", "M", "ART"), ANY),
    "drivemode": (("iAuto", "P", "A", "S", "M", "ART", "B"), ()),
    "colortone": (PASM, ()),
    "artfilter": (("ART",), ()),
    "exposemovie": ((), ANY),
    "focusmode": (PASM, ()), "metering": (PASM, ()), "flashmode": (PASM, ()), "recordmode": (PASM, ()),
    "aspect": (PASM, ()), "stabilizer": (PASM, ()), "facepriority": (PASM, ()), "focusstacking": (PASM, ()),
}
USB_ONLY = ("focusmode", "metering", "flashmode", "recordmode", "aspect", "stabilizer", "facepriority",
            "focusstacking")  # Super Control Panel items without a Wi-Fi command
NOT_WITH_STACKING = ("drivemode", "flashmode")  # hidden while Focus Stacking is On (as on the page)
MODE_SETTLE = 0.8  # s after a Wi-Fi mode change before the props are read again (the page waits as long)
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
    if mode == "movie":
        return movie == ANY or movie_exp in movie
    return mode in photo


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
    movie_exp = str(_norm_mode(wanted["exposemovie"]) if wanted.get("exposemovie")
                    else (props.get("exposemovie") or {}).get("value"))
    stacking = str(wanted.get("focusstacking", (props.get("focusstacking") or {}).get("value"))).strip().lower() in ("1", "on")
    # Focus stacking first: turning it Off must reach the camera before drive or flash mode
    for prop in sorted((k for k in wanted if k != "takemode"), key=lambda k: (k != "focusstacking", k)):
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
        entry = _with_names(prop, props[prop])
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
        time.sleep(MODE_SETTLE)
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

CONTROL_ANNOTATIONS = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
SHUTTER_ANNOTATIONS = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
ERASE_ANNOTATIONS = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}
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
        "pass 'prop' to also receive its allowed values (enum); pass choices=true for every setting selectable in "
        "the current mode with its values and readable labels, plus what only the camera body can set (body_only).",
        _schema({"prop": {"type": "string", "description": "Optional setting name, e.g. shutspeedvalue, isospeedvalue."},
                 "choices": {"type": "boolean", "description": "All settings selectable now, with values and labels."}}),
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
        "List pictures on the camera card (newest first), saved computer captures (source='local'), "
        "or Wi-Fi Share Order marks (source='share_order'). Uses the saved card list by default for "
        "instant answers; set fresh=true to query the camera card.",
        _schema({
            "source": {"type": "string", "enum": ["card", "local", "share_order"],
                       "description": "List source: 'card' (default), 'local' (captures/), or 'share_order' (Wi-Fi)."},
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

AF_ALL_TARGETS = 33024  # USB AF Area "All Targets": the camera picks the field itself
AF_AREA_MODES = {"all": 33024, "single": 33025, "group": 33026, "small": 33027}
AF_AREA_LABELS = {33024: "All Targets", 33025: "Single Target", 33026: "Group Target", 33027: "Small Target"}
LOUPE_RATIOS = (3, 5, 7, 10, 14)
LOUPE_DIRECTIONS = ("up", "down", "left", "right")
LV_SIZES = ("0320x0240", "0640x0480", "0800x0600", "1024x0768", "1280x0960")
MIN_INTERVAL = 5  # same minimum as omcap/server.py (one shot takes ~4 s)
MAX_SELF_TIMER = 30


def _af_field(info, x, y):
    """Field 1-81 of the camera's 9x9 AF grid at (x, y) given as 0-1 of the live view frame."""
    a = info.get("area") or {}
    w, h = a.get("w") or 1, a.get("h") or 1
    col = int((x * w - a.get("x0", 0)) * 9 / max(1, a.get("x1", w) - a.get("x0", 0)))
    row = int((y * h - a.get("y0", 0)) * 9 / max(1, a.get("y1", h) - a.get("y0", 0)))
    return 9 * min(max(row, 0), 8) + min(max(col, 0), 8) + 1


def _check_xy(x, y):
    if (x is None) != (y is None):
        raise ValueError("Give both 'x' and 'y' (0-1 of the live view frame) or neither")
    if x is not None:
        for v in (x, y):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1:
                raise ValueError("'x' and 'y' must be numbers from 0 to 1")
    return x, y


def _check_capture_name(name):
    if not isinstance(name, str) or not name.strip() or "/" in name or "\\" in name or ".." in name:
        raise ValueError("'name' must be a plain file name from captures/ (no path separators)")
    return name.strip()


def _is_camera_busy(state):
    return bool(state.get("busy") or state.get("indexing") or state.get("stage")
                or (state.get("job") or {}).get("running")
                or (state.get("star_af") or {}).get("running")
                or state.get("movie") or state.get("take") or state.get("play"))


def _require_server_write(status):
    if isinstance(status, dict) and status.get("allow_write") is False:
        raise ApiError("E-M1 Capture is running read-only. Restart E-M1 Capture with --allow-write first.", status=403)


def _in_focus(conn, res):
    """USB reports authoritative focus_ok (never trust stale last_af); Wi-Fi reports last_af only on affocus=ok."""
    if conn == "usb":
        return res.get("focus_ok") is True
    return bool(res.get("last_af"))


def _is_usb_sequential_drive(drive_val):
    if drive_val is None:
        return False
    try:
        return (int(str(drive_val)) & 15) in (2, 3)
    except ValueError:
        return False


def _focus_dry_run(change, call_args):
    """Dry-run answer of camera_focus: what would change, and the call that applies it after the user's yes."""
    shown = ", ".join("%s=%s" % (k, json.dumps(v)) for k, v in sorted(call_args.items()))
    return _text({"dry_run": True, "will_change": change,
                  "next_step": "Tell the user what changes, then call camera_focus(%s%sconfirm=true)."
                               % (shown, ", " if shown else "")})


def tool_camera_focus(client, args, ctx):
    confirm = args.get("confirm") is True
    call_args = {k: v for k, v in args.items() if k != "confirm"}
    mf = args.get("mf")
    star_af = args.get("star_af")
    loupe = args.get("loupe")
    af_area = args.get("af_area")
    if sum(v is not None for v in (mf, star_af, loupe, af_area)) > 1:
        raise ValueError("Use only one of 'mf', 'star_af', 'loupe', or 'af_area' per call")

    if star_af == "status":
        return _text({"star_af": client.get_json("/api/staraf")})

    status = client.get_json("/api/status")
    _require_server_write(status)
    conn = status.get("type")

    if star_af is not None:
        if star_af not in ("start", "stop"):
            raise ValueError("'star_af' must be 'start', 'stop', or 'status'")
        if star_af == "stop":
            res = client.post_json("/api/staraf", {"action": "stop"}) or {}
            return _text(res)
        if conn != "usb":
            raise ApiError("Auto Star AF works only over USB (no Wi-Fi focus drive command).")
        state = client.get_json("/api/state")
        if not state.get("live"):
            raise ApiError("Start Live View first before running Star AF.")
        if _is_camera_busy(state):
            raise ApiError("The camera is busy: wait, then try again.")
        props = client.get_json("/api/props")
        if str((props.get("takemode") or {}).get("value")) == "movie":
            raise ApiError("Star AF is only available in photo shooting modes (not Movie mode).")
        x, y = _check_xy(args.get("x"), args.get("y"))
        zoom = args.get("zoom", True)
        boost = args.get("boost", True)
        if not isinstance(zoom, bool) or not isinstance(boost, bool):
            raise ValueError("'zoom' and 'boost' must be booleans")
        priority = args.get("priority", "speed")
        if priority not in ("speed", "accuracy"):
            raise ValueError("'priority' must be 'speed' or 'accuracy'")
        payload = {"action": "start", "zoom": zoom, "boost": boost, "priority": priority}
        if x is not None:
            payload["x"], payload["y"] = float(x), float(y)
        if not confirm:
            return _focus_dry_run("Auto Star AF: drives the focus, may switch S-AF+MF to MF on success"
                                  + (", temporary Live View Boost" if boost else "")
                                  + (", Zoom AF x10 while it runs" if zoom else ""), call_args)
        res = client.post_json("/api/staraf", payload) or {}
        res["note"] = "Star AF runs asynchronously; poll camera_focus(star_af='status') or camera_status."
        return _text(res)

    if loupe is not None:
        if loupe not in ("on", "off", "move"):
            raise ValueError("'loupe' must be 'on', 'off', or 'move'")
        if conn != "usb":
            raise ApiError("Zoom AF (loupe) works only over USB (no Wi-Fi command).")
        if loupe == "off":
            res = client.post_json("/api/loupe", {"on": False}) or {}
            return _text({"loupe": bool(res.get("loupe", False)), "rev": res.get("rev")})
        state = client.get_json("/api/state")
        if not state.get("live"):
            raise ApiError("Start Live View first before using Zoom AF (loupe).")
        if _is_camera_busy(state):
            raise ApiError("The camera is busy: wait, then try again.")
        if str(((_optional_json(client, "/api/props") or {}).get("takemode") or {}).get("value")) == "movie":
            raise ApiError("Zoom AF (loupe) is not available in Movie mode via the MCP (not camera-tested there).")
        if loupe == "move":
            if not state.get("loupe"):
                raise ApiError("Zoom AF (loupe) is not active. Turn it on first.")
            direction = args.get("direction")
            if direction not in LOUPE_DIRECTIONS:
                raise ValueError("'direction' must be one of: %s" % ", ".join(LOUPE_DIRECTIONS))
            if not confirm:
                return _focus_dry_run("Zoom AF (loupe): moves the zoomed area %s" % direction, call_args)
            res = client.post_json("/api/loupe", {"move": direction}) or {}
            return _text({"loupe": bool(res.get("loupe", True)), "moved": direction, "rev": res.get("rev")})
        payload = {"on": True}
        ratio = args.get("ratio")
        if ratio is not None:
            if isinstance(ratio, bool) or ratio not in LOUPE_RATIOS:
                raise ValueError("'ratio' must be one of: %s" % ", ".join(str(r) for r in LOUPE_RATIOS))
            payload["ratio"] = ratio
        x, y = _check_xy(args.get("x"), args.get("y"))
        if x is not None:
            payload["x"], payload["y"] = float(x), float(y)
        if not confirm:
            return _focus_dry_run("Zoom AF (loupe) on" + (" at x%s" % ratio if ratio else ""), call_args)
        res = client.post_json("/api/loupe", payload) or {}
        return _text({"loupe": bool(res.get("loupe", True)), "ratio": ratio, "rev": res.get("rev")})

    if mf is not None:
        if mf not in ("near", "far"):
            raise ValueError("'mf' must be 'near' or 'far'")
        step = args.get("step", 1)
        if isinstance(step, bool) or step not in (1, 2, 3):
            raise ValueError("'step' must be 1, 2, or 3")
        if conn != "usb":
            raise ApiError("Focus ring (MF) steps work only over USB (no Wi-Fi command).")
        props = _optional_json(client, "/api/props") or {}
        if str((props.get("takemode") or {}).get("value")) == "movie":
            raise ApiError("Focus ring (MF) steps are not offered in Movie mode (as in the app).")
        fm = (props.get("focusmode") or {}).get("value")
        if fm is not None and str(fm) not in ("1", "32769"):
            raise ApiError("Focus ring (MF) steps require AF mode MF or S-AF+MF (E-M1 manual, p.75).")
        if not confirm:
            return _focus_dry_run("Focus ring (MF): drives the lens %s, step %d" % (mf, step), call_args)
        client.post_json("/api/mfdrive", {"direction": mf, "step": step})
        return _text({"mf": mf, "step": step, "note": "Check sharpness with live_view_frame."})

    state = _optional_json(client, "/api/state") or {}
    if _is_camera_busy(state):
        raise ApiError("The camera is busy (shot, series, movie, Playback, or Press halfway): wait, then try again.")
    if conn == "usb":
        props = _optional_json(client, "/api/props") or {}
        if str((props.get("focusmode") or {}).get("value")) == "1":
            raise ApiError("AF target and AF Area are not available in MF mode.")

    x, y = _check_xy(args.get("x"), args.get("y"))
    if af_area is not None:
        if af_area not in AF_AREA_MODES:
            raise ValueError("'af_area' must be one of: %s" % ", ".join(AF_AREA_MODES))
        if conn != "usb":
            raise ApiError("AF Area mode can only be changed over USB (Wi-Fi always uses a single point).")
        mode_code = AF_AREA_MODES[af_area]
        if x is not None and mode_code == AF_ALL_TARGETS:
            raise ApiError("AF Area 'all' (All Targets) lets the camera pick the point; omit x/y or choose single/group/small.")
        payload = {"mode": mode_code}
        if x is not None:
            info = client.get_json("/api/afarea")
            payload["field"] = _af_field(info, x, y)
        if not confirm:
            return _focus_dry_run("AF Area: %s" % AF_AREA_LABELS.get(mode_code, af_area)
                                  + (", AF target field %d, then AF" % payload["field"] if "field" in payload else ""),
                                  call_args)
        res = client.post_json("/api/afarea", payload, timeout=15.0) or {}
        out = {
            "connection": conn,
            "af_area": AF_AREA_LABELS.get(res.get("mode", mode_code), af_area),
            "field": res.get("field", payload.get("field")),
        }
        if x is not None:
            out["in_focus"] = _in_focus(conn, res)
        return _text(out)

    info = client.get_json("/api/afarea")
    if x is not None:
        if conn == "usb" and info.get("mode") == AF_ALL_TARGETS:
            raise ApiError("AF Area is All Targets: the camera picks the point. Set af_area='single' "
                           "to focus on a point, or call camera_focus without x/y.")
        payload = {"field": _af_field(info, x, y)}
        if not confirm:
            return _focus_dry_run("AF target: field %d (of 81), then AF" % payload["field"], call_args)
    elif conn == "usb":
        payload = {"focus": True}
    else:
        payload = {"field": info.get("field") or 41}  # Wi-Fi focuses on a point: the last one, else the centre
    if not confirm:
        return _focus_dry_run("AF (Press halfway) with %s" % ("the current AF target" if "focus" in payload
                              else "AF target field %d" % payload["field"]), call_args)
    res = client.post_json("/api/afarea", payload, timeout=15.0) or {}
    in_focus = _in_focus(conn, res)
    out = {"connection": conn, "field": res.get("field", payload.get("field")), "in_focus": in_focus}
    if res.get("mode") in AF_AREA_LABELS:
        out["af_area"] = AF_AREA_LABELS[res["mode"]]
    if not in_focus:
        out["note"] = "No focus confirmed: more contrast, more light, or a closer point; then check live_view_frame."
    return _text(out)


def tool_live_view(client, args, ctx):
    action = args.get("action")
    if action not in ("start", "stop"):
        raise ValueError("'action' must be 'start' or 'stop'")
    status = _optional_json(client, "/api/status")
    _require_server_write(status)
    payload = {"action": action}
    size = args.get("size")
    if size is not None:
        if size not in LV_SIZES:
            raise ValueError("'size' must be one of: %s" % ", ".join(LV_SIZES))
    if action == "start":
        state = _optional_json(client, "/api/state") or {}
        if state.get("play"):
            raise ApiError("Exit Playback first before starting Live View.")
        if _is_camera_busy(state):
            raise ApiError("The camera is busy: wait before starting Live View.")
        if size is not None:
            if isinstance(status, dict) and status.get("features") is not None and "lvsize" not in status["features"]:
                raise ApiError("Live view size cannot be changed on this USB backend (fixed 1024x768).")
            payload["lvqty"] = size
        if args.get("confirm") is not True:
            return _text({"dry_run": True, "will_start_live_view": {"size": size} if size else True,
                          "next_step": "Tell the user, then call live_view(action='start'%s, confirm=true)."
                                       % (", size=%r" % size if size else "")})
    client.post_json("/api/liveview", payload, timeout=20.0)
    out = {"live_view": action == "start"}
    if action == "start" and size is not None:
        out["size"] = size
    return _text(out)


def tool_playback(client, args, ctx):
    action = args.get("action")
    if action not in ("enter", "exit", "download", "hsl", "hsl_auto", "open_workspace"):
        raise ValueError("'action' must be one of: enter, exit, download, hsl, hsl_auto, open_workspace")
    if action in ("enter", "exit"):
        _require_server_write(_optional_json(client, "/api/status"))
        if _is_camera_busy(_optional_json(client, "/api/state") or {}):
            raise ApiError("The camera is busy (shot, series, movie or Press halfway): wait, then try again.")
        if args.get("confirm") is not True:
            return _text({"dry_run": True, "will_switch_camera_to": "Playback" if action == "enter" else "shooting",
                          "next_step": "Tell the user, then call playback(action=%r, confirm=true)." % action})
        res = client.post_json("/api/playback", {"action": "enter" if action == "enter" else "leave"}, timeout=20.0) or {}
        return _text({"play_mode": bool(res.get("play", action == "enter"))})
    if action == "download":
        path = args.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("'path' must be a camera card path starting with '/'")
        res = client.post_json("/api/download", {"path": path}, timeout=60.0) or {}
        return _text({"downloaded": True, "path": path, "saved": res.get("saved"), "name": res.get("name")})
    if action == "hsl":
        name = _check_capture_name(args.get("name"))
        profile = args.get("profile")
        if not (isinstance(profile, (str, dict)) and profile):
            raise ValueError("'profile' must be a preset name or profile object")
        tiff = args.get("tiff", False)
        if not isinstance(tiff, bool):
            raise ValueError("'tiff' must be a boolean")
        res = client.post_json("/api/hsl", {"name": name, "profile": profile, "tiff": tiff}, timeout=60.0) or {}
        return _text({"hsl_applied": True, "name": name, "result": res})
    if action == "hsl_auto":
        enabled = args.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("'enabled' must be a boolean")
        payload = {"enabled": enabled}
        if args.get("preset") is not None:
            if not isinstance(args["preset"], str) or not args["preset"].strip():
                raise ValueError("'preset' must be a non-empty string")
            payload["preset"] = args["preset"].strip()
        res = client.post_json("/api/hslauto", payload) or {}
        return _text(res)
    name = _check_capture_name(args.get("name"))
    client.post_json("/api/open", {"name": name})
    return _text({"opened_in_om_workspace": name})


def tool_app_control(client, args, ctx):
    action = args.get("action")
    if action not in ("connect", "disconnect", "poweroff", "refresh", "transfer", "save_config"):
        raise ValueError("'action' must be one of: connect, disconnect, poweroff, refresh, transfer, save_config")
    confirm = args.get("confirm") is True
    if action == "connect":
        conn = args.get("connection")
        if conn not in ("usb", "wifi"):
            raise ValueError("'connection' must be 'usb' or 'wifi'")
        if not confirm:
            return _text({"dry_run": True, "will_connect": conn,
                          "next_step": "Tell the user, then call app_control(action='connect', connection=%r, confirm=true)." % conn})
        res = client.post_json("/api/connect", {"type": conn}, timeout=30.0) or {}
        return _text({"connected": True, "type": res.get("type", conn)})
    if action == "disconnect":
        if not confirm:
            return _text({"dry_run": True, "will_disconnect": True,
                          "next_step": "Confirm with the user and call app_control(action='disconnect', confirm=true)."})
        client.post_json("/api/disconnect", {})
        return _text({"disconnected": True})
    if action == "poweroff":
        status = client.get_json("/api/status")
        if status.get("type") != "wifi":
            raise ApiError("Turn off camera is only available over Wi-Fi.")
        if not confirm:
            return _text({"dry_run": True, "will_poweroff_camera": True, "model": status.get("model"),
                          "next_step": "Confirm with the user and call app_control(action='poweroff', confirm=true)."})
        _require_server_write(status)
        client.post_json("/api/poweroff", {}, timeout=15.0)
        return _text({"powered_off": True})
    if action == "refresh":
        status = client.get_json("/api/status")
        if status.get("type") != "usb":
            raise ApiError("Refresh is only needed over USB.")
        if not confirm:
            return _text({"dry_run": True, "will_refresh_usb_session": True,
                          "next_step": "Tell the user, then call app_control(action='refresh', confirm=true)."})
        client.post_json("/api/refresh", {}, timeout=30.0)
        return _text({"refreshed": True})
    if action == "transfer":
        target = args.get("target")
        if target not in ("sd", "both"):
            raise ValueError("'target' must be 'sd' or 'both'")
        client.post_json("/api/transfer", {"target": target})
        return _text({"transfer": target})
    cur = _optional_json(client, "/api/savecfg") or {}
    scheme = cur.get("scheme", "original") if args.get("scheme") is None else args["scheme"]
    if scheme not in ("original", "prefix", "datetime"):
        raise ValueError("'scheme' must be one of: original, prefix, datetime")
    save_dir = cur.get("dir", "") if args.get("dir") is None else args["dir"]
    prefix = cur.get("prefix", "") if args.get("prefix") is None else args["prefix"]
    if not isinstance(save_dir, str) or not isinstance(prefix, str):
        raise ValueError("'dir' and 'prefix' must be strings")
    payload = {"dir": save_dir, "scheme": scheme, "prefix": prefix}
    res = client.post_json("/api/savecfg", payload) or {}
    return _text({"save_config": res.get("cfg", payload)})


def _wifi_card_paths(client):
    """Newest Wi-Fi card paths, or None if the query failed (never conflated with an empty card)."""
    try:
        imgs = client.get_json("/api/images", {"newest": "1"}, timeout=20.0)
    except ApiError:
        return None
    return [e.get("path") for e in imgs or () if e.get("path")]


def _bracket_sequence(props, frames, step):
    """Compute the exact exposure compensation sequence (mirrors omcap/server.bracket_plan)."""
    if isinstance(frames, bool) or frames not in (3, 5, 7) or isinstance(step, bool) or step not in (1, 2, 3):
        raise ValueError("Bracketing requires frames in (3, 5, 7) and step in (1, 2, 3) thirds of a stop")
    p = props.get("expcomp") or {}
    enum = list(p.get("enum") or ())
    cur = p.get("value")
    if not p.get("writable") or not enum or cur not in enum:
        raise ApiError("Exposure compensation is not selectable in the current mode.")
    idx = enum.index(cur)
    wanted = [idx + k * step for k in range(-(frames // 2), frames // 2 + 1)]
    if wanted[0] < 0 or wanted[-1] >= len(enum):
        raise ApiError("Bracketing (%d frames, step %d/3 EV) exceeds the camera's compensation range." % (frames, step))
    return [enum[j] for j in wanted]


def tool_camera_shoot(client, args, ctx):
    action = args.get("action", "shot")
    if action not in ("shot", "half_press", "long_exposure", "interval", "bracket", "movie", "stop_job"):
        raise ValueError("'action' must be one of: shot, half_press, long_exposure, interval, bracket, movie, stop_job")
    confirm = args.get("confirm") is True

    # Stop/release actions run immediately so a running series, exposure or recording can always be stopped.
    if action == "stop_job":
        client.post_json("/api/job/stop", {})
        return _text({"stopped": "job"})
    if action == "half_press" and args.get("step") == "release":
        res = client.post_json("/api/shutter", {"stage": 0}) or {}
        return _text({"half_press": False, "saved_to_computer": res.get("saved") or []})
    if action == "long_exposure" and args.get("step") == "stop":
        res = client.post_json("/api/take", {"action": "stop"}, timeout=120.0) or {}
        return _text({"long_exposure": "stopped", "saved_to_computer": res.get("saved") or []})
    if action == "movie" and args.get("step") == "stop":
        state = _optional_json(client, "/api/state") or {}
        if "movie" in state and not state.get("movie"):
            raise ApiError("No movie recording is running.")
        client.post_json("/api/movie", {"action": "stop"}, timeout=20.0)
        return _text({"movie": "stopped"})

    status = client.get_json("/api/status")
    conn = status.get("type")
    props = client.get_json("/api/props")
    state = client.get_json("/api/state")
    val = lambda k: (props.get(k) or {}).get("value")  # noqa: E731
    mode = str(val("takemode"))
    shutter = str(val("shutspeedvalue"))
    base_plan = {"connection": conn, "shooting_mode": mode, "shutter": shutter, "aperture": val("focalvalue"),
                 "iso": val("isospeedvalue"), "drive": val("drivemode")}

    if action in ("shot", "half_press") and mode == "movie":
        raise ApiError("Take picture and Press halfway are not available in Movie mode via the MCP (not camera-tested "
                       "there): use action='movie', or set a photo Shooting mode first.")
    if action == "half_press":
        step = args.get("step", "press")
        if step != "press":
            raise ValueError("'step' for half_press must be 'press' or 'release'")
        if _is_camera_busy(state):
            raise ApiError("The camera is busy: wait, then try again.")
        if not confirm:
            return _text({"dry_run": True, "will_half_press": base_plan,
                          "next_step": "Confirm with the user and call camera_shoot(action='half_press', step='press', confirm=true)."})
        _require_server_write(status)
        res = client.post_json("/api/shutter", {"stage": 1}, timeout=15.0) or {}
        return _text({"half_press": True, "last_af": res.get("last_af")})

    if action == "long_exposure":
        step = args.get("step")
        if step not in ("prepare", "start"):
            raise ValueError("'step' for long_exposure must be 'prepare', 'start', or 'stop'")
        if mode != "M" or shutter not in LONG_SHUTTER:
            raise ApiError("Long exposure requires Shooting mode M and Shutter speed BULB, LIVE TIME, or LIVECOMP.")
        if conn == "usb" and str(val("focusstacking")) == "1":
            raise ApiError("BULB, LIVE TIME and LIVECOMP are not available while Focus Stacking is On.")
        if step == "prepare":
            if conn != "usb":
                raise ApiError("Prepare for LIVECOMP is only used over USB; call step='start' directly over Wi-Fi.")
            if shutter != "livecomp":
                raise ApiError("Prepare is only used for LIVECOMP.")
        if _is_camera_busy(state):
            raise ApiError("The camera is busy: wait, then try again.")
        plan = dict(base_plan, step=step)
        payload = {"action": step}
        if step == "start":
            for opt in ("exposuremin", "upperlimit"):
                v = args.get(opt)
                if v is not None:
                    if conn == "usb":
                        raise ApiError("'%s' is only supported over Wi-Fi (USB uses the camera's own setting)." % opt)
                    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
                        raise ValueError("'%s' must be a positive number" % opt)
                    payload[opt] = v
                    plan[opt] = v
        if not confirm:
            return _text({"dry_run": True, "will_long_exposure": plan,
                          "next_step": "Confirm with the user and call camera_shoot(action='long_exposure', step=%r, confirm=true)." % step})
        _require_server_write(status)
        client.post_json("/api/take", payload, timeout=30.0)
        return _text({"long_exposure": step, "settings": plan,
                      "next_step": "Call camera_shoot(action='long_exposure', step='stop') to finish." if step == "start"
                      else "Call camera_shoot(action='long_exposure', step='start', confirm=true) to begin."})

    if action == "movie":
        step = args.get("step")
        if step != "start":
            raise ValueError("'step' for movie must be 'start' or 'stop'")
        if conn == "usb" and state.get("card") is False:
            raise ApiError("Movie recording requires a card in the camera.")
        if shutter in LONG_SHUTTER:
            raise ApiError("Movie recording is not available during BULB, LIVE TIME, or LIVECOMP (E-M1 manual, p.26).")
        if conn == "usb" and (str(val("focusstacking")) == "1" or _is_usb_sequential_drive(val("drivemode"))):
            raise ApiError("Movie recording is not available during sequential shooting or Focus Stacking (E-M1 manual, p.26).")
        if _is_camera_busy(state):
            raise ApiError("The camera is busy: wait, then try again.")
        if conn == "wifi" and mode != "movie":
            raise ApiError("Over Wi-Fi the MCP does not switch the Shooting mode by itself (the app does): set Movie "
                           "with camera_configure (after the user's yes) or turn the mode dial to Movie.")
        plan = dict(base_plan, action="start")
        if not confirm:
            return _text({"dry_run": True, "will_start_movie": plan,
                          "next_step": "Confirm with the user and call camera_shoot(action='movie', step='start', confirm=true)."})
        _require_server_write(status)
        client.post_json("/api/movie", {"action": "start"}, timeout=20.0)
        return _text({"movie": "recording", "settings": plan,
                      "next_step": "Call camera_shoot(action='movie', step='stop') to stop recording."})

    if action == "interval":
        count, seconds = args.get("count"), args.get("seconds")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 999:
            raise ValueError("'count' must be an integer from 1 to 999")
        if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not math.isfinite(seconds) or seconds < MIN_INTERVAL):
            raise ValueError("'seconds' must be a number of at least %d s" % MIN_INTERVAL)
        if mode not in ("P", "A", "S", "M") or shutter in LONG_SHUTTER:
            raise ApiError("Time lapse shooting is only available in P, A, S, or M mode (not BULB/LIVE TIME/LIVECOMP).")
        if _is_camera_busy(state):
            raise ApiError("The camera is busy: wait, then try again.")
        plan = dict(base_plan, count=count, seconds=float(seconds),
                    estimated_total_s=round(max(0, count - 1) * float(seconds), 1))
        if not confirm:
            return _text({"dry_run": True, "will_run_interval": plan,
                          "next_step": "State the frame count and interval to the user, then call camera_shoot(action='interval', count=%d, seconds=%s, confirm=true)." % (count, seconds)})
        _require_server_write(status)
        client.post_json("/api/interval", {"count": count, "seconds": float(seconds)})
        return _text({"started": "interval", "plan": plan,
                      "next_step": "Check progress in camera_status or stop with camera_shoot(action='stop_job')."})

    if action == "bracket":
        frames, step = args.get("frames"), args.get("ev_step")
        if mode not in ("P", "A", "S"):
            raise ApiError("AE BKT is only available in P, A, or S mode (not %s)." % mode)
        if conn == "usb" and str(val("focusstacking")) == "1":
            raise ApiError("AE BKT is not available while Focus Stacking is On.")
        ev_seq = _bracket_sequence(props, frames, step)
        if _is_camera_busy(state):
            raise ApiError("The camera is busy: wait, then try again.")
        plan = dict(base_plan, frames=frames, ev_step_thirds=step, ev_sequence=ev_seq)
        if not confirm:
            return _text({"dry_run": True, "will_run_bracket": plan,
                          "next_step": "State the frame count and EV sequence to the user, then call camera_shoot(action='bracket', frames=%d, ev_step=%d, confirm=true)." % (frames, step)})
        _require_server_write(status)
        client.post_json("/api/bracket", {"frames": frames, "step": step})
        return _text({"started": "bracket", "plan": plan,
                      "next_step": "Check progress in camera_status or stop with camera_shoot(action='stop_job')."})

    # Default: action == "shot"
    self_timer = args.get("self_timer", 0)
    if isinstance(self_timer, bool) or not isinstance(self_timer, int) or not 0 <= self_timer <= MAX_SELF_TIMER:
        raise ValueError("'self_timer' must be an integer from 0 to %d seconds" % MAX_SELF_TIMER)
    if shutter in LONG_SHUTTER:
        raise ApiError("BULB, LIVE TIME and LIVECOMP need start and stop: use camera_shoot(action='long_exposure').")
    if _is_camera_busy(state):
        raise ApiError("The camera is busy (shot, series, movie, Playback, or Press halfway): wait, then try again.")
    plan = dict(base_plan)
    if self_timer:
        plan["self_timer_s"] = self_timer
    if not confirm:
        return _text({"dry_run": True, "will_take_one_picture": plan,
                      "next_step": "Tell the user and call camera_shoot with confirm=true only after their yes."})
    _require_server_write(status)
    if self_timer:
        time.sleep(self_timer)
    if conn == "usb":
        before_last = (_optional_json(client, "/api/lastshot") or {}).get("path")
        res = client.post_json("/api/shoot", {}, timeout=120.0) or {}
        after_last = (_optional_json(client, "/api/lastshot") or {}).get("path")
        new = [after_last] if after_last and after_last != before_last else []
        new_note = None
    else:
        before = _wifi_card_paths(client)
        res = client.post_json("/api/shoot", {}, timeout=120.0) or {}
        if before is None:
            new, new_note = [], "Could not list card files before the shot; check last_picture."
        else:
            before_set = set(before)
            new = []
            for attempt in range(3):
                after = _wifi_card_paths(client) or []
                new = [p for p in after if p not in before_set]
                if new or attempt == 2:
                    break
                time.sleep(1.5)
            new_note = None
    out = {"taken": True, "settings": plan, "new_files": new, "saved_to_computer": res.get("saved") or []}
    if res.get("note"):
        out["note"] = "Focus Stacking was On, the camera took one picture."
    elif new_note:
        out["note"] = new_note
    out["next_step"] = "Check it with last_picture (preview='full' for sharpness)."
    return _text(out)


def tool_card_erase(client, args, ctx):
    action = args.get("action", "erase")
    if action not in ("erase", "clear_share_order"):
        raise ValueError("'action' must be 'erase' or 'clear_share_order'")
    confirm = args.get("confirm") is True
    status = client.get_json("/api/status")
    conn = status.get("type")

    if action == "clear_share_order":
        if conn != "wifi":
            raise ApiError("Reset Share Order is only available over Wi-Fi.")
        state = _optional_json(client, "/api/state") or {}
        if state.get("play") is False:
            raise ApiError("Reset Share Order over Wi-Fi requires Playback mode. Call playback(action='enter') first.")
        marked = client.get_json("/api/shareorder") or []
        if not confirm:
            return _text({"dry_run": True, "action": "clear_share_order",
                          "marked_count": len(marked), "marked_files": marked,
                          "warning": "Deselects all images selected for sharing on the camera's card. This cannot be undone.",
                          "next_step": "Confirm with the user and call card_erase(action='clear_share_order', confirm=true)."})
        _require_server_write(status)
        client.post_json("/api/shareorder/clear", {})
        return _text({"cleared_share_order": True, "previous_count": len(marked)})

    if conn != "usb":
        raise ApiError("Card erase is only available over USB (Wi-Fi has no erase command).")
    paths = args.get("paths")
    if not isinstance(paths, list) or not paths or len(paths) > MAX_LIST_LIMIT:
        raise ValueError("'paths' must be a non-empty list of card paths (max %d)" % MAX_LIST_LIMIT)
    clean = []
    for p in paths:
        if not isinstance(p, str) or not p.startswith("/"):
            raise ValueError("Every path must be a camera card path starting with '/'")
        clean.append(p)
    if not confirm:
        return _text({"dry_run": True, "action": "erase", "will_erase_count": len(clean), "paths": clean,
                      "warning": "Card deletion cannot be undone.",
                      "next_step": "List the exact files to the user and call card_erase(action='erase', paths=..., confirm=true) only after their explicit yes."})
    _require_server_write(status)
    res = client.post_json("/api/erase", {"paths": clean}, timeout=60.0) or {}
    return _text({"erased": res.get("erased") or [], "failed": res.get("failed") or []})


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
    "camera_focus": (
        "Focus the camera: AF on a point (x, y as 0-1 of the live view frame), AF with the current AF point "
        "(no arguments), USB AF Area mode ('all'/'single'/'group'/'small'), USB Focus ring (MF) steps "
        "(mf='near'/'far', step 1-3), USB Auto Star AF (star_af='start'/'stop'/'status'), or USB Zoom AF "
        "(loupe='on'/'off'/'move'). Does not release the shutter. Anything that focuses, changes a setting or drives "
        "the lens (AF, x/y, af_area, mf, star_af='start', loupe='on'/'move') is a dry-run first: show the change, then "
        "repeat with confirm=true after the user's yes. star_af='status'/'stop' and loupe='off' run at once.",
        _schema({
            "x": {"type": "number", "minimum": 0, "maximum": 1, "description": "Horizontal point, 0 left to 1 right."},
            "y": {"type": "number", "minimum": 0, "maximum": 1, "description": "Vertical point, 0 top to 1 bottom."},
            "af_area": {"type": "string", "enum": ["all", "single", "group", "small"],
                        "description": "USB: AF Area target mode."},
            "mf": {"type": "string", "enum": ["near", "far"], "description": "USB: Focus ring (MF) direction (Near/Far)."},
            "step": {"type": "integer", "enum": [1, 2, 3], "description": "Focus ring (MF) step size 1-3 (default 1)."},
            "star_af": {"type": "string", "enum": ["start", "stop", "status"],
                        "description": "USB photo modes: Auto Star AF control or status."},
            "zoom": {"type": "boolean", "description": "Star AF: use Zoom AF x10 (default true)."},
            "boost": {"type": "boolean", "description": "Star AF: temporary Live View Boost (default true)."},
            "priority": {"type": "string", "enum": ["speed", "accuracy"],
                         "description": "Star AF priority (default 'speed')."},
            "loupe": {"type": "string", "enum": ["on", "off", "move"], "description": "USB: Zoom AF (loupe) control."},
            "ratio": {"type": "integer", "enum": [3, 5, 7, 10, 14], "description": "USB Zoom AF magnification."},
            "direction": {"type": "string", "enum": ["up", "down", "left", "right"],
                          "description": "USB Zoom AF move direction when loupe='move'."},
            "confirm": {"type": "boolean", "description": "True applies the change; only after the user's yes."},
        }),
        CONTROL_ANNOTATIONS,
        tool_camera_focus,
    ),
    "live_view": (
        "Start or stop the live view in E-M1 Capture (needed for live_view_frame), with optional frame size. "
        "start is a dry-run first and needs confirm=true after the user's yes; stop runs at once.",
        _schema({
            "action": {"type": "string", "enum": ["start", "stop"]},
            "size": {"type": "string", "enum": list(LV_SIZES),
                     "description": "Optional live view resolution on start (e.g. '1024x0768')."},
            "confirm": {"type": "boolean", "description": "True starts the live view; only after the user's yes."},
        }, required=["action"]),
        CONTROL_ANNOTATIONS,
        tool_live_view,
    ),
    "playback": (
        "Playback, computer download, software HSL and OM Workspace: enter/exit camera Playback, download a "
        "card file to captures/, apply an HSL preset/profile to a file in captures/, configure auto-HSL, or "
        "open a saved capture in OM Workspace on this computer. enter/exit switch the camera mode: dry-run first, "
        "confirm=true after the user's yes. The computer-side actions run at once (they never write to the camera).",
        _schema({
            "action": {"type": "string", "enum": ["enter", "exit", "download", "hsl", "hsl_auto", "open_workspace"]},
            "path": {"type": "string", "description": "Camera card path (starting with '/') for action='download'."},
            "name": {"type": "string", "description": "File name in captures/ for action='hsl' or 'open_workspace'."},
            "profile": {"description": "HSL preset name (string) or profile dict for action='hsl'."},
            "tiff": {"type": "boolean", "description": "For ORF in action='hsl': also write 16-bit TIFF (default false)."},
            "enabled": {"type": "boolean", "description": "Enable/disable auto-HSL for action='hsl_auto'."},
            "preset": {"type": "string", "description": "Preset name for action='hsl_auto'."},
            "confirm": {"type": "boolean", "description": "Required (true) for enter/exit after the user's yes."},
        }, required=["action"]),
        CONTROL_ANNOTATIONS,
        tool_playback,
    ),
    "app_control": (
        "Manage E-M1 Capture connection and computer save settings: connect ('usb'/'wifi'), disconnect, "
        "Turn off camera over Wi-Fi ('poweroff'), USB refresh, transfer target ('sd'/'both'), or save folder/naming "
        "config. connect, disconnect, poweroff and refresh default to dry-run and require confirm=true after user approval; "
        "transfer and save_config only change computer-side settings and run at once. Never quits the app.",
        _schema({
            "action": {"type": "string", "enum": ["connect", "disconnect", "poweroff", "refresh", "transfer", "save_config"]},
            "connection": {"type": "string", "enum": ["usb", "wifi"], "description": "Target for action='connect'."},
            "target": {"type": "string", "enum": ["sd", "both"], "description": "Target for action='transfer'."},
            "dir": {"type": "string", "description": "Folder path for action='save_config' (empty = default captures/)."},
            "scheme": {"type": "string", "enum": ["original", "prefix", "datetime"],
                       "description": "File naming scheme for action='save_config'."},
            "prefix": {"type": "string", "description": "File name prefix when scheme='prefix'."},
            "confirm": {"type": "boolean", "description": "Required (true) for connect, disconnect, poweroff and refresh after the user's yes."},
        }, required=["action"]),
        CONTROL_ANNOTATIONS,
        tool_app_control,
    ),
}

SHUTTER_TOOLS = {
    "camera_shoot": (
        "Trigger or stop camera capture: single shot (action='shot', optional self-timer), Press halfway ('half_press'), "
        "long exposure BULB/LIVE TIME/LIVECOMP in M ('long_exposure'), Time lapse shooting ('interval', P/A/S/M), "
        "AE BKT exposure bracketing in P/A/S ('bracket'), movie recording ('movie'), or stop a running series ('stop_job'). "
        "Defaults to confirm=false (safe dry-run plan); set confirm=true ONLY after the user said yes for this "
        "specific action. Stop actions execute immediately.",
        _schema({
            "action": {"type": "string",
                       "enum": ["shot", "half_press", "long_exposure", "interval", "bracket", "movie", "stop_job"],
                       "description": "Capture action (default 'shot')."},
            "confirm": {"type": "boolean", "description": "True executes the capture; only after the user's yes."},
            "self_timer": {"type": "integer", "minimum": 0, "maximum": MAX_SELF_TIMER,
                           "description": "App self-timer: delay in seconds (0-30) before action='shot', counted by E-M1 Capture "
                                          "(the camera's Self-timer drive mode is not changed)."},
            "step": {"type": "string", "enum": ["press", "release", "prepare", "start", "stop"],
                     "description": "Sub-step for half_press, long_exposure (prepare = USB LIVECOMP only), or movie."},
            "count": {"type": "integer", "minimum": 1, "maximum": 999,
                      "description": "Number of frames for action='interval' (Time lapse shooting)."},
            "seconds": {"type": "number", "minimum": MIN_INTERVAL,
                        "description": "Interval between shots in seconds (>= 5) for action='interval'."},
            "frames": {"type": "integer", "enum": [3, 5, 7], "description": "Frame count for action='bracket' (AE BKT)."},
            "ev_step": {"type": "integer", "enum": [1, 2, 3],
                        "description": "EV step in thirds of a stop (1=1/3, 2=2/3, 3=1 EV) for action='bracket'."},
            "exposuremin": {"type": "number", "description": "Wi-Fi optional minimum exposure for long_exposure start."},
            "upperlimit": {"type": "number", "description": "Wi-Fi optional upper limit for long_exposure start."},
        }),
        SHUTTER_ANNOTATIONS,
        tool_camera_shoot,
    ),
}

ERASE_TOOLS = {
    "card_erase": (
        "Erase files from the camera card (USB only, action='erase') or Reset Share Order over Wi-Fi "
        "(action='clear_share_order'). Defaults to confirm=false (dry-run listing the exact files); "
        "set confirm=true ONLY after the user's explicit yes. Neither action can be undone.",
        _schema({
            "action": {"type": "string", "enum": ["erase", "clear_share_order"],
                       "description": "Operation (default 'erase')."},
            "paths": {"type": "array", "items": {"type": "string"},
                      "description": "Camera card paths starting with '/' for action='erase'."},
            "confirm": {"type": "boolean", "description": "True executes deletion/reset; only after the user's yes."},
        }),
        ERASE_ANNOTATIONS,
        tool_card_erase,
    ),
}


class McpServer:
    """Stateless JSON-RPC 2.0 handler for E-M1 Capture MCP tools and Photo Coach prompts."""

    def __init__(self, client, allow_write=False, lenses=None, allow_shutter=False, allow_erase=False):
        self.client = client
        self.allow_write = bool(allow_write)
        self.allow_shutter = bool(allow_shutter) and self.allow_write
        self.allow_erase = bool(allow_erase) and self.allow_write
        self.lenses = [s.strip() for s in (lenses or ()) if str(s).strip()]

    def _tools(self):
        tools = dict(READ_TOOLS)
        if self.allow_write:
            tools.update(WRITE_TOOLS)
        if self.allow_shutter:
            tools.update(SHUTTER_TOOLS)
        if self.allow_erase:
            tools.update(ERASE_TOOLS)
        return tools

    def _instructions(self):
        if not self.allow_write:
            return INSTRUCTIONS_RO
        parts = [INSTRUCTIONS_RW]
        if self.allow_shutter:
            parts.append(SHUTTER_RULES)
        if self.allow_erase:
            parts.append(ERASE_RULES)
        return "\n\n".join(parts)

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
                "instructions": self._instructions(),
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
            ctx = {"allow_write": self.allow_write, "allow_shutter": self.allow_shutter,
                   "allow_erase": self.allow_erase, "lenses": self.lenses}
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
        help="Enable camera_configure, camera_focus, live_view, playback and app_control (E-M1 Capture must also run with --allow-write).",
    )
    ap.add_argument(
        "--allow-shutter",
        action="store_true",
        help="Also enable camera_shoot (shot, long exposure, interval, bracket, movie; dry-run by default); needs --allow-write.",
    )
    ap.add_argument(
        "--allow-erase",
        action="store_true",
        help="Also enable card_erase (USB card erase, Wi-Fi Share Order clear; dry-run by default); needs --allow-write.",
    )
    ap.add_argument(
        "--lenses",
        default=os.environ.get("OMCAP_LENSES", ""),
        help="Comma-separated list of lenses you own, for Photo Coach recommendations (or OMCAP_LENSES).",
    )
    args = ap.parse_args(argv)
    try:
        if args.allow_shutter and not args.allow_write:
            ap.error("--allow-shutter needs --allow-write")
        if args.allow_erase and not args.allow_write:
            ap.error("--allow-erase needs --allow-write")
        client = HttpClient(
            args.url,
            allow_write=args.allow_write,
            allow_shutter=args.allow_shutter,
            allow_erase=args.allow_erase,
        )
    except ValueError as e:
        ap.error(str(e))
    lenses = [s.strip() for s in args.lenses.split(",") if s.strip()]
    serve(McpServer(
        client,
        allow_write=args.allow_write,
        lenses=lenses,
        allow_shutter=args.allow_shutter,
        allow_erase=args.allow_erase,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
