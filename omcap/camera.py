"""Client for the Olympus OI.Share interface (E-M1, protocol 2.60).

Read-only CGIs go through Camera.get(). Everything that changes the camera
(shooting, settings, mode switch, live view) goes only through
Camera.write() and only if the client was created with allow_write=True.
"""
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HOST = "192.168.0.10"
HEADERS = {"User-Agent": "OlympusCameraKit"}
# E-M1 command list (firmware 4.6), bundled as a fallback for mode "shutter"
SAVED_COMMANDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "commandlist.xml")

FOCUS_WAIT = 2.0       # time between 1stpush and 2ndpush
TAKE_STOP_WAIT = 0.5  # s between starttake and stoptake (one frame in single-frame drive)
SAVE_WAIT = 1.5        # wait for the camera to finish saving before switching the mode back
LIST_RETRIES = 6       # retry get_imglist this many times on HTTP 520 (camera is still writing)
LIST_RETRY_WAIT = 1.0  # seconds between attempts

# See CLAUDE.md: only these CGIs are allowed without asking.
READ_CGIS = {
    "get_connectmode", "get_caminfo", "get_activate", "get_camprop",
    "get_imglist", "get_thumbnail", "get_screennail", "get_resizeimg",
    "get_movplaytime", "get_rsvimglist", "get_unusedcapacity",
    "get_dcffilenum", "get_gpsdivunit", "get_commandlist",
}
RESIZE_SIZES = ("1024", "1600", "1920", "2048")  # as in the command list
SHUTTER_STEPS = {"1stpush", "2ndpush", "1st2ndpush", "2nd1strelease", "2ndrelease", "1strelease"}


class WriteBlocked(Exception):
    """Write command without permission."""


class CameraError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code  # HTTP status of the camera, e.g. 520


def _pair(text):
    """'0259x0179' -> (259, 179), else None."""
    m = re.fullmatch(r"(\d+)x(\d+)", (text or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _parse_commands(raw):
    # The camera declares Shift-JIS, which ET does not know; the content is ASCII.
    root = ET.fromstring(raw.split("?>", 1)[-1])
    return {c.get("name") for c in root.iter("cgi")}


def parse_capacity(raw):
    """Free card space in bytes from the get_unusedcapacity answer, else None.

    The format is unconfirmed: an XML element with a number or a bare number is accepted.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("latin-1")
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("<"):
        try:
            root = ET.fromstring(text.split("?>", 1)[-1] if text.startswith("<?") else text)
        except ET.ParseError:
            return None
        text = next((e.text.strip() for e in root.iter()
                     if len(e) == 0 and e.text and re.fullmatch(r"\s*\d+\s*", e.text)), "")
    m = re.fullmatch(r"\d+", text)
    return int(text) if m else None


def parse_rsvimglist(text):
    """Share order list, defensive: "dir,name,size,attr,date,time" or just a path per line."""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("VER_") or line.startswith("<"):
            continue
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 2 and parts[1] and "/" not in parts[1]:
            d, name = parts[0], parts[1]
        else:
            d, _, name = parts[0].rpartition("/")
        if not name or "." not in name:
            continue
        num = lambda i: int(parts[i]) if len(parts) > i and parts[i].isdigit() else 0
        items.append({"dir": d, "name": name, "size": num(2), "path": d.rstrip("/") + "/" + name})
    return items


def parse_playtime(text):
    """Movie length in seconds from the get_movplaytime answer, None if unreadable.

    Expects seconds or hh:mm:ss (in XML or plain text); errorcode becomes an error.
    """
    m = re.search(r"<errorcode>\s*(\d+)\s*</errorcode>", text)
    if m and int(m.group(1)):
        raise CameraError("get_movplaytime: errorcode %s" % m.group(1))
    body = re.sub(r"<\?.*?\?>", "", text, flags=re.S)
    m = re.search(r"(\d+):(\d{1,2}):(\d{1,2})", body)
    if m:
        h, mi, sec = map(int, m.groups())
        return h * 3600 + mi * 60 + sec
    m = re.search(r"(\d+):(\d{1,2})(?!\d)", body)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.search(r"(\d+(?:\.\d+)?)", re.sub(r"<[^>]*>", " ", body))
    return int(float(m.group(1))) if m else None


class Camera:
    def __init__(self, host=HOST, timeout=8, allow_write=False):
        self.host = host
        self.timeout = timeout
        self.allow_write = allow_write
        self.stage = 0      # shutter: 0 open, 1 half, 2 full
        self.lvqty = None   # last chosen live view size
        self._lock = threading.Lock()
        self._commands = None
        self._touch = None  # (lvqty, touch_frame()); the camera only changes it together with lvqty
        self.af_point = None  # last tapped AF point "XXXXxYYYY" (touch frame grid), used by shoot()

    # --- Transport -------------------------------------------------------
    def _open(self, cgi, query=None, data=None, timeout=None):
        url = "http://%s/%s" % (self.host, cgi)
        if query:
            url += "?" + urllib.parse.urlencode(query, safe="/")
        headers = dict(HEADERS)
        if data is not None:
            headers["Content-Type"] = "text/plain;charset=utf-8"
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.timeout)
        except (urllib.error.URLError, OSError) as e:
            raise CameraError("%s: %s" % (cgi, e), getattr(e, "code", None))

    def get(self, cgi, **query):
        name = cgi[:-4] if cgi.endswith(".cgi") else cgi
        if name not in READ_CGIS:
            raise WriteBlocked("%s is not a read-only command" % name)
        with self._lock, self._open(name + ".cgi", query) as r:
            return r.read()

    def write(self, cgi, data=None, **query):
        name = cgi[:-4] if cgi.endswith(".cgi") else cgi
        if not self.allow_write:
            raise WriteBlocked("Writing not enabled (--allow-write)")
        if not self.supports(name):
            raise CameraError("%s is not in the camera's command list" % name)
        with self._lock, self._open(name + ".cgi", query, data) as r:
            return r.read()

    def fetch_file(self, path, dest, chunk=1 << 16):
        """Save a file from the card locally (read-only on the camera)."""
        _check_path(path)
        with self._lock, self._open(path.lstrip("/"), timeout=30) as r, open(dest, "wb") as f:
            while True:
                b = r.read(chunk)
                if not b:
                    break
                f.write(b)

    def read_file(self, path):
        """Read a file from the card into memory (read-only on the camera)."""
        _check_path(path)
        with self._lock, self._open(path.lstrip("/"), timeout=30) as r:
            return r.read()

    def read_head(self, path, size):
        """Read only the start of a file, e.g. for EXIF (read-only on the camera)."""
        _check_path(path)
        with self._lock, self._open(path.lstrip("/"), timeout=15) as r:
            return r.read(size)

    # --- Command list ----------------------------------------------------
    def commandlist(self):
        if self._commands is not None:
            return self._commands
        try:
            raw = self.get("get_commandlist").decode("ascii", "replace")
        except CameraError:
            # In mode "shutter" the camera answers get_* with HTTP 520. Without
            # the stored list there would be no way back to "rec".
            with open(SAVED_COMMANDS, encoding="ascii", errors="replace") as f:
                return _parse_commands(f.read())
        self._commands = _parse_commands(raw)
        return self._commands

    def supports(self, name):
        return name in self.commandlist()

    # --- Read ------------------------------------------------------------
    def caminfo(self):
        return ET.fromstring(self.get("get_caminfo")).findtext("model")

    def props(self):
        root = ET.fromstring(self.get("get_camprop", com="desc", propname="desclist"))
        out = {}
        for d in root.iter("desc"):
            out[d.findtext("propname")] = {
                "value": d.findtext("value"),
                "writable": "set" in (d.findtext("attribute") or ""),
                "enum": (d.findtext("enum") or "").split(),
            }
        return out

    def free_bytes(self):
        return parse_capacity(self.get("get_unusedcapacity"))

    def battery(self):
        return None  # readable over USB only

    def prop(self, name):
        return ET.fromstring(self.get("get_camprop", com="get", propname=name)).findtext("value")

    def touch_frame(self):
        """Area for touch AF. Format x-y_BxH, centred in the live view image.

        Depends only on the live view size and is therefore remembered per lvqty:
        a click into the grid would otherwise need three extra requests.
        """
        if self._touch and self._touch[0] == self.lvqty:
            return self._touch[1]
        m = re.fullmatch(r"(\d+)-(\d+)_(\d+)x(\d+)", self.prop("touchactiveframe") or "")
        if not m:
            raise CameraError("touchactiveframe not readable")
        x, y, w, h = map(int, m.groups())
        frame = {"x": x, "y": y, "w": w, "h": h, "base_w": 2 * x + w, "base_h": 2 * y + h}
        self._touch = (self.lvqty, frame)
        return frame

    def listdir(self, directory):
        """Entries as dict(dir, name, size, isdir, date, time)."""
        _check_path(directory)
        # Right after a shot the camera is still writing to the card and
        # briefly answers 520. Ask again a few times.
        for attempt in range(LIST_RETRIES + 1):
            try:
                text = self.get("get_imglist", DIR=directory).decode("latin-1")
                break
            except CameraError as e:
                if e.code != 520 or attempt == LIST_RETRIES:
                    raise
                time.sleep(LIST_RETRY_WAIT)
        items = []
        for line in text.splitlines():
            parts = line.split(",")
            if len(parts) < 6 or line.startswith("VER_"):
                continue
            items.append({
                "dir": parts[0], "name": parts[1], "size": int(parts[2]),
                "isdir": bool(int(parts[3]) & 0x10),
                "date": int(parts[4]), "time": int(parts[5]),
            })
        return items

    def images(self, root="/DCIM"):
        files = []
        for e in self.listdir(root):
            path = e["dir"].rstrip("/") + "/" + e["name"]
            if e["isdir"]:
                files.extend(self.images(path))
            else:
                e["path"] = path
                files.append(e)
        return files

    def share_order(self):
        """Shots marked for Share Order (read-only)."""
        return parse_rsvimglist(self.get("get_rsvimglist").decode("latin-1"))

    def movie_length(self, path):
        """Movie length in seconds; the camera only answers in mode "play" (otherwise errorcode 1001)."""
        _check_path(path)
        return parse_playtime(self.get("get_movplaytime", DIR=path).decode("latin-1"))

    def thumbnail(self, path):
        _check_path(path)
        return self.get("get_thumbnail", DIR=path)

    def screennail(self, path):
        _check_path(path)
        return self.get("get_screennail", DIR=path)

    def resizeimg(self, path, size):
        """Reduced JPG (long side size), only in mode "play" (otherwise HTTP 520)."""
        _check_path(path)
        if str(size) not in RESIZE_SIZES:
            raise CameraError("Unknown preview size: %r" % size)
        return self.get("get_resizeimg", DIR=path, size=str(size))

    # --- Write (only with allow_write) -------------------------------------
    def set_mode(self, mode, lvqty=None):
        q = {"mode": mode}
        if mode == "rec":
            self._touch = None  # re-read once after every mode switch
            if lvqty and lvqty != self.lvqty:
                self.af_point = None  # the touch grid depends on the live view size
            self.lvqty = lvqty or self.lvqty
            if self.lvqty:
                # The camera takes lvqty only on a switch from "play" to "rec".
                # Otherwise the old size stays, coming from "shutter" even 320x240.
                self.write("switch_cammode", mode="play")
                q["lvqty"] = self.lvqty
        return self.write("switch_cammode", **q)

    def reset_share_order(self):
        """Clear the Share Order marks on the card (writes to the card)."""
        return self.write("clear_resvflg")

    def set_prop(self, prop, value):
        body = ('<?xml version="1.0"?><set><value>%s</value></set>' % value).encode()
        return self.write("set_camprop", data=body, com="set", propname=prop)

    def power_off(self):
        """Switch the camera off; the camera then ends the Wi-Fi."""
        return self.write("exec_pwoff")

    def start_liveview(self, port):
        return self.write("exec_takemisc", com="startliveview", port=str(port))

    def stop_liveview(self):
        return self.write("exec_takemisc", com="stopliveview")

    def af_focus(self, fx, fy):
        """Touch AF. fx, fy: position in the live image as a fraction 0..1.

        assignafframe answers with affocus (ok/ng), afframepoint (top left corner)
        and afframesize, all in the grid base_w × base_h. takeready answers empty.
        Returns {"ok": bool, "x", "y": frame centre or None}.
        """
        f = self.touch_frame()
        x, y = round(float(fx) * f["base_w"]), round(float(fy) * f["base_h"])
        if not (f["x"] <= x <= f["x"] + f["w"] and f["y"] <= y <= f["y"] + f["h"]):
            raise CameraError("AF point is outside the active area")
        point = "%04dx%04d" % (x, y)
        self.af_point = point
        reply = self.write("exec_takemotion", com="assignafframe", point=point)
        self.write("exec_takemotion", com="takeready", point=point)
        try:
            root = ET.fromstring(reply)
        except ET.ParseError:
            return {"ok": False, "x": None, "y": None}
        p, s = _pair(root.findtext("afframepoint")), _pair(root.findtext("afframesize"))
        return {"ok": (root.findtext("affocus") or "").strip().lower() == "ok",
                "x": p[0] + s[0] / 2 if p and s else None,
                "y": p[1] + s[1] / 2 if p and s else None}

    def shutter(self, step):
        if step not in SHUTTER_STEPS:
            raise CameraError("Unknown shutter step: %r" % step)
        return self.write("exec_shutter", com=step)

    def press(self, stage):
        """Operate the shutter button independently: 0 release, 1 half, 2 full."""
        if stage not in (0, 1, 2):
            raise CameraError("Unknown shutter position: %r" % stage)
        if stage == self.stage:
            return
        if self.stage == 0:
            # exec_shutter is only accepted in mode "shutter" (otherwise HTTP 520).
            self.set_mode("shutter")
            self.stage = 1  # from here on press(0) must clean up, even after an error
            self.shutter("1stpush")
            if stage == 2:
                time.sleep(FOCUS_WAIT)
                self.shutter("2ndpush")
                self.stage = 2
        elif stage == 2:
            self.shutter("2ndpush")
            self.stage = 2
        elif stage == 1:
            self.shutter("2nd1strelease")
            self.stage = 1
        else:
            self._release()

    def _release(self):
        full = self.stage == 2
        error = None
        for step in (["2nd1strelease"] if full else []) + ["1strelease"]:
            try:
                self.shutter(step)
            except CameraError as e:
                error = e
        self.stage = 0
        if full:
            time.sleep(SAVE_WAIT)
        self.set_mode("rec")  # in "shutter" the camera rejects get_* commands
        if error:
            raise error

    def shoot(self):
        """Take one picture. First `starttake` with the tapped point in mode "rec" (E-M1: answer after
        ~0.8 s, focuses on that point, no switch to "shutter"; REQ-F34); if the camera refuses,
        the shutter-button route (~7 s)."""
        self.mode_switched = False
        if self._starttake_suits() and self.take_point():
            return
        self.mode_switched = True  # the shutter-button route ends the live view
        try:
            self.press(1)
            time.sleep(FOCUS_WAIT)
            self.press(2)
            time.sleep(0.5)
        finally:
            self.press(0)

    def _starttake_suits(self):
        """starttake/stoptake is tested for normal shots only (2026-11-13). Long exposures (BULB, LIVE TIME,
        LIVECOMP, slower than 1/4 s), the self-timer and Movie mode keep the shutter-button route."""
        try:
            mode, speed, drive = (self.prop(p) or "" for p in ("takemode", "shutspeedvalue", "drivemode"))
        except CameraError:
            return False
        slow = '"' in speed or (re.fullmatch(r"[\d.]+", speed) and float(speed) < 4)  # "4" = 1/4 s
        return mode != "movie" and not speed.startswith("live") and not slow and "selftimer" not in drive

    def take_point(self):
        """Focus on the last tapped point (or the camera's AF target) and shoot.

        False only if the camera refuses (HTTP 520 or <take> not ok): then nothing was taken and the
        caller may use the shutter-button route. Other errors are raised, so no second picture."""
        q = {"com": "starttake"}
        if self.af_point:
            q["point"] = self.af_point
        try:
            reply = self.write("exec_takemotion", **q)
        except CameraError as e:
            if e.code == 520:
                return False
            self._stop_take()  # a timeout may still have started the take
            raise
        try:
            ok = ET.fromstring(reply).findtext("take", "").strip().lower() == "ok"
        except ET.ParseError:
            ok = None  # unknown answer: stop and report, do not shoot a second time
        time.sleep(TAKE_STOP_WAIT)
        self._stop_take()  # ends the take (sequential drive: the burst)
        if ok is None:
            raise CameraError("Unexpected answer to starttake")
        return ok

    def _stop_take(self):
        try:
            self.write("exec_takemotion", com="stoptake")
        except CameraError:
            pass

    def take_start(self, exposuremin=None, upperlimit=None):
        """Start a long exposure (parameters per the command list, values untested)."""
        q = {"com": "starttake"}
        if exposuremin:
            q["exposuremin"] = str(int(exposuremin))
        if upperlimit:
            q["upperlimit"] = str(int(upperlimit))
        return self.write("exec_takemotion", **q)

    def take_stop(self):
        return self.write("exec_takemotion", com="stoptake")

    def movie_start(self):
        return self.write("exec_takemotion", com="startmovietake", liveview="on")

    def movie_stop(self):
        return self.write("exec_takemotion", com="stopmovietake")


def _check_path(path):
    if not path.startswith("/DCIM") or ".." in path:
        raise CameraError("Invalid path: %r" % path)
