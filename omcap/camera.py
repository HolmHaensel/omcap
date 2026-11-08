"""Client für die Olympus OI.Share-Schnittstelle (E-M1, Protokoll 2.60).

Lesende CGIs gehen über Camera.get(). Alles, was die Kamera verändert
(Auslösen, Einstellungen, Moduswechsel, Liveview), geht nur über
Camera.write() und nur, wenn der Client mit allow_write=True erzeugt wurde.
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
# Befehlsliste der E-M1 (Firmware 4.6), mitgeliefert als Rückfallebene für den Modus "shutter"
SAVED_COMMANDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "commandlist.xml")

FOCUS_WAIT = 2.0       # Zeit zwischen 1stpush und 2ndpush
SAVE_WAIT = 1.5        # Speichern abwarten, bevor der Modus zurückwechselt
LIST_RETRIES = 6       # get_imglist bei HTTP 520 so oft wiederholen (Kamera schreibt noch)
LIST_RETRY_WAIT = 1.0  # Sekunden zwischen den Versuchen

# Siehe CLAUDE.md: nur diese CGIs sind ohne Rückfrage erlaubt.
READ_CGIS = {
    "get_connectmode", "get_caminfo", "get_activate", "get_camprop",
    "get_imglist", "get_thumbnail", "get_screennail", "get_resizeimg",
    "get_movplaytime", "get_rsvimglist", "get_unusedcapacity",
    "get_dcffilenum", "get_gpsdivunit", "get_commandlist",
}
RESIZE_SIZES = ("1024", "1600", "1920", "2048")  # laut Befehlsliste
SHUTTER_STEPS = {"1stpush", "2ndpush", "1st2ndpush", "2nd1strelease", "2ndrelease", "1strelease"}


class WriteBlocked(Exception):
    """Schreibender Befehl ohne Freigabe."""


class CameraError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code  # HTTP-Status der Kamera, z. B. 520


def _pair(text):
    """'0259x0179' -> (259, 179), sonst None."""
    m = re.fullmatch(r"(\d+)x(\d+)", (text or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _parse_commands(raw):
    # Die Kamera deklariert Shift-JIS, ET kennt das nicht; Inhalt ist ASCII.
    root = ET.fromstring(raw.split("?>", 1)[-1])
    return {c.get("name") for c in root.iter("cgi")}


def parse_capacity(raw):
    """Freier Kartenplatz in Bytes aus der Antwort von get_unusedcapacity, sonst None.

    Das Format ist nicht bestätigt: erlaubt sind ein XML-Element mit Zahl oder eine reine Zahl.
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
    """Share-Order-Liste, defensiv: "dir,name,size,attr,date,time" oder nur ein Pfad pro Zeile."""
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
    """Filmlänge in Sekunden aus der Antwort von get_movplaytime, None wenn nicht lesbar.

    Erwartet Sekunden oder hh:mm:ss (im XML oder als Klartext); errorcode wird zum Fehler.
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
        self.stage = 0      # Auslöser: 0 offen, 1 halb, 2 voll
        self.lvqty = None   # zuletzt gewählte Liveview-Größe
        self._lock = threading.Lock()
        self._commands = None
        self._touch = None  # (lvqty, touch_frame()), die Kamera ändert ihn nur mit lvqty

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
        """Datei von der Karte lokal speichern (nur lesen auf der Kamera)."""
        _check_path(path)
        with self._lock, self._open(path.lstrip("/"), timeout=30) as r, open(dest, "wb") as f:
            while True:
                b = r.read(chunk)
                if not b:
                    break
                f.write(b)

    def read_file(self, path):
        """Datei von der Karte in den Speicher lesen (nur lesen auf der Kamera)."""
        _check_path(path)
        with self._lock, self._open(path.lstrip("/"), timeout=30) as r:
            return r.read()

    def read_head(self, path, size):
        """Nur den Anfang einer Datei lesen, z. B. für EXIF (nur lesen auf der Kamera)."""
        _check_path(path)
        with self._lock, self._open(path.lstrip("/"), timeout=15) as r:
            return r.read(size)

    # --- Befehlsliste ----------------------------------------------------
    def commandlist(self):
        if self._commands is not None:
            return self._commands
        try:
            raw = self.get("get_commandlist").decode("ascii", "replace")
        except CameraError:
            # Im Modus "shutter" beantwortet die Kamera get_* mit HTTP 520. Ohne
            # die gespeicherte Liste käme man dann nicht mehr auf "rec" zurück.
            with open(SAVED_COMMANDS, encoding="ascii", errors="replace") as f:
                return _parse_commands(f.read())
        self._commands = _parse_commands(raw)
        return self._commands

    def supports(self, name):
        return name in self.commandlist()

    # --- Lesen -----------------------------------------------------------
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
        return None  # nur über USB lesbar

    def prop(self, name):
        return ET.fromstring(self.get("get_camprop", com="get", propname=name)).findtext("value")

    def touch_frame(self):
        """Bereich für Touch-AF. Format x-y_BxH, liegt mittig im Liveview-Bild.

        Hängt nur von der Live-View-Größe ab und wird deshalb je lvqty gemerkt:
        Ein Klick ins Raster braucht sonst drei zusätzliche Anfragen.
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
        """Einträge als dict(dir, name, size, isdir, date, time)."""
        _check_path(directory)
        # Direkt nach dem Auslösen schreibt die Kamera noch auf die Karte und
        # antwortet kurz mit 520. Dann einige Male nachfragen.
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
        """Für Share Order markierte Aufnahmen (nur lesen)."""
        return parse_rsvimglist(self.get("get_rsvimglist").decode("latin-1"))

    def movie_length(self, path):
        """Filmlänge in Sekunden; die Kamera antwortet nur im Modus "play" (sonst errorcode 1001)."""
        _check_path(path)
        return parse_playtime(self.get("get_movplaytime", DIR=path).decode("latin-1"))

    def thumbnail(self, path):
        _check_path(path)
        return self.get("get_thumbnail", DIR=path)

    def screennail(self, path):
        _check_path(path)
        return self.get("get_screennail", DIR=path)

    def resizeimg(self, path, size):
        """Verkleinertes JPG (lange Seite size), nur im Modus "play" (sonst HTTP 520)."""
        _check_path(path)
        if str(size) not in RESIZE_SIZES:
            raise CameraError("Unknown preview size: %r" % size)
        return self.get("get_resizeimg", DIR=path, size=str(size))

    # --- Schreiben (nur mit allow_write) -----------------------------------
    def set_mode(self, mode, lvqty=None):
        q = {"mode": mode}
        if mode == "rec":
            self._touch = None  # nach jedem Moduswechsel einmal neu lesen
            self.lvqty = lvqty or self.lvqty
            if self.lvqty:
                # Die Kamera übernimmt lvqty nur beim Wechsel von "play" nach "rec".
                # Sonst bleibt die alte Größe, aus "shutter" kommend sogar 320x240.
                self.write("switch_cammode", mode="play")
                q["lvqty"] = self.lvqty
        return self.write("switch_cammode", **q)

    def reset_share_order(self):
        """Share-Order-Markierungen auf der Karte löschen (schreibt auf die Karte)."""
        return self.write("clear_resvflg")

    def set_prop(self, prop, value):
        body = ('<?xml version="1.0"?><set><value>%s</value></set>' % value).encode()
        return self.write("set_camprop", data=body, com="set", propname=prop)

    def start_liveview(self, port):
        return self.write("exec_takemisc", com="startliveview", port=str(port))

    def stop_liveview(self):
        return self.write("exec_takemisc", com="stopliveview")

    def af_focus(self, fx, fy):
        """Touch-AF. fx, fy: Position im Livebild als Anteil 0..1.

        assignafframe antwortet mit affocus (ok/ng), afframepoint (linke obere Ecke)
        und afframesize, alles im Raster base_w × base_h. takeready antwortet leer.
        Rückgabe: {"ok": bool, "x", "y": Rahmenmitte oder None}.
        """
        f = self.touch_frame()
        x, y = round(float(fx) * f["base_w"]), round(float(fy) * f["base_h"])
        if not (f["x"] <= x <= f["x"] + f["w"] and f["y"] <= y <= f["y"] + f["h"]):
            raise CameraError("AF point is outside the active area")
        point = "%04dx%04d" % (x, y)
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
        """Auslöser unabhängig bedienen: 0 loslassen, 1 halb, 2 voll."""
        if stage not in (0, 1, 2):
            raise CameraError("Unknown shutter position: %r" % stage)
        if stage == self.stage:
            return
        if self.stage == 0:
            # exec_shutter wird nur im Modus "shutter" angenommen (sonst HTTP 520).
            self.set_mode("shutter")
            self.stage = 1  # ab hier muss press(0) aufräumen, auch nach einem Fehler
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
        self.set_mode("rec")  # in "shutter" lehnt die Kamera get_*-Befehle ab
        if error:
            raise error

    def shoot(self):
        try:
            self.press(1)
            time.sleep(FOCUS_WAIT)
            self.press(2)
            time.sleep(0.5)
        finally:
            self.press(0)

    def take_start(self, exposuremin=None, upperlimit=None):
        """Langzeitbelichtung starten (Parameter laut Befehlsliste, Werte ungetestet)."""
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
