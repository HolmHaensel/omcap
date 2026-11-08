"""Lokale Weboberfläche für die E-M1 (nur auf 127.0.0.1).

  .venv/bin/python -m omcap.server                 # nur lesen
  .venv/bin/python -m omcap.server --allow-write   # Auslösen/Einstellungen möglich

Die Verbindung (USB oder Wi-Fi) wird auf dem Startbildschirm gewählt.
"""
import argparse
import contextlib
import json
import os
import subprocess
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, exif, usb_camera
from .camera import Camera, CameraError, WriteBlocked
from .liveview import LiveView

ROOT = os.path.dirname(os.path.abspath(__file__))
# Arbeitsordner (--data-dir, Standard: aktueller Ordner): Aufnahmen und Vorschau-Cache liegen darunter
CAPTURES = os.path.join(os.getcwd(), "captures")
PREVIEW_CACHE = os.path.join(os.getcwd(), "out", "cache", "previews")  # Vorschauen von der Karte
PREVIEW_CACHE_MAX = 500 << 20  # Bytes; darüber fliegen die ältesten Vorschauen raus
IMAGE_MAX_AGE = 7 * 24 * 3600  # Bild-URLs enthalten die Dateigröße, ändern sich also mit der Datei
LV_PORT = 5555
MIN_INTERVAL = 5  # eine Aufnahme dauert rund 4 s (Fokus, Auslösen, Speichern)

WIFI_FEATURES = ["liveview", "lvsize", "af_area", "stages", "scp", "time_lapse", "ae_bkt", "movie",
                 "long", "playback", "transfer", "poweroff"]

cam = None   # aktive Verbindung, None vor der Auswahl auf dem Startbildschirm
live = None
conn_type = None
options = {"host": "192.168.0.10", "allow_write": False}
allowed_hosts = set()
lens_cache = {}  # Kartenpfad -> Objektivdaten aus EXIF

busy = threading.Lock()  # immer nur eine Aufnahme-Abfolge gleichzeitig
stop_job = threading.Event()
job = {"name": None, "running": False, "done": 0, "total": 0, "error": None}
state = {"transfer": "sd", "latest": None, "transfer_error": None,
         "take": None, "movie": None, "resume_live": False, "seen": None, "wifi_field": 41,
         "wifi_af": None, "pressing": False, "play": None}


# --- Verbindung --------------------------------------------------------------
def wifi_name():
    """Modellname per get_caminfo (nur lesend) oder None, wenn keine Kamera antwortet."""
    try:
        return Camera(options["host"], timeout=1).caminfo() or "Camera"
    except (CameraError, WriteBlocked, ET.ParseError):
        return None


def connections():
    """Erkannte Verbindungen mit Kameranamen für den Startbildschirm."""
    if conn_type is not None:
        return {"connected": conn_type, "wifi": conn_type == "wifi", "usb": conn_type == "usb",
                "names": {}}
    names = {"wifi": wifi_name(), "usb": usb_camera.detect_name()}
    return {"connected": None, "wifi": names["wifi"] is not None, "usb": names["usb"] is not None,
            "names": names}


def connect(kind):
    global cam, live, conn_type
    disconnect()
    if kind == "wifi":
        c = Camera(options["host"], allow_write=options["allow_write"])
        c.features = WIFI_FEATURES
        c.caminfo()  # meldet sofort, wenn die Kamera nicht antwortet
        cam, live = c, LiveView(LV_PORT)
    elif kind == "usb":
        c = usb_camera.UsbCamera(allow_write=options["allow_write"])
        cam, live = c, c.live
    else:
        raise ValueError("Unknown connection")
    conn_type = kind


def disconnect():
    global cam, live, conn_type
    if cam is None:
        return
    try:
        if live.running:
            cam.stop_liveview()
    except (CameraError, WriteBlocked):
        pass
    live.stop()
    if conn_type == "usb":
        cam.close()
    cam, live, conn_type = None, None, None
    lens_cache.clear()
    state.update(play=None)
    state.update(transfer="sd", latest=None, transfer_error=None, take=None, movie=None,
                 resume_live=False, seen=None, wifi_field=41, wifi_af=None)


def af_area():
    """Über Wi-Fi gibt es keinen AF-Modus-Befehl: dort immer ein einzelnes Feld."""
    if conn_type == "usb":
        return {**cam.af_area(), "modes": True}
    f = cam.touch_frame()
    return {"mode": 33025, "field": state["wifi_field"], "modes": False, "last_af": state["wifi_af"],
            "area": {"x0": f["x"], "x1": f["x"] + f["w"], "y0": f["y"], "y1": f["y"] + f["h"],
                     "w": f["base_w"], "h": f["base_h"]}}


def set_af_area(mode, field):
    if conn_type == "usb":
        cam.set_af_area(mode, field)
        if field is not None:
            cam.focus()
        return
    if mode not in (None, 33025):
        raise CameraError("AF modes can only be changed over USB")
    field = int(field)
    if not 1 <= field <= 81:
        raise CameraError("AF point must be between 1 and 81")
    a = af_area()["area"]
    row, col = divmod(field - 1, 9)
    state["wifi_af"] = None
    res = cam.af_focus((a["x0"] + (col + .5) / 9 * (a["x1"] - a["x0"])) / a["w"],
                       (a["y0"] + (row + .5) / 9 * (a["y1"] - a["y0"])) / a["h"])
    state["wifi_field"] = field
    # Nur bei affocus=ok die Rahmenmitte melden, die Oberfläche färbt das Feld dann grün
    if res["ok"] and res["x"] is not None:
        state["wifi_af"] = {"x": res["x"], "y": res["y"]}


# --- Aufnahme-Abläufe --------------------------------------------------------
def ensure_idle():
    if cam.stage or state["take"] or state["movie"] or job["running"] or state["play"] is not None:
        raise CameraError("Camera is busy")


def power_off():
    """Kamera per Wi-Fi ausschalten und zum Startbildschirm zurück."""
    if conn_type != "wifi":
        raise CameraError("Only available over Wi-Fi")
    ensure_idle()
    try:
        if live.running:
            cam.stop_liveview()
    except CameraError:
        pass  # Liveview ist egal, die Kamera geht gleich aus
    live.stop()
    try:
        cam.power_off()
    except CameraError:
        pass  # die Kamera kappt das WLAN, oft ohne Antwort
    disconnect()


def start_live():
    if conn_type == "usb":
        cam.start_liveview(LV_PORT)  # prüft die Schreibfreigabe
        live.start()
    else:
        live.start()
        cam.start_liveview(LV_PORT)


@contextlib.contextmanager
def capture():
    """Sperrt die Kamera für eine Abfolge und startet danach den Liveview neu."""
    if not busy.acquire(blocking=False):
        raise CameraError("Camera is busy")
    was_live = live.running
    try:
        yield
    finally:
        try:
            if was_live:  # Moduswechsel beendet den Liveview
                start_live()
        finally:
            busy.release()


def jpg_last(items, name=lambda x: x):
    """JPG zuletzt, damit es als neuestes Bild angezeigt wird."""
    return sorted(items, key=lambda x: name(x).lower().endswith((".jpg", ".jpeg")))


def save_capture(path, size=None):
    """Datei von der Karte holen, ohne Vorhandenes zu überschreiben."""
    os.makedirs(CAPTURES, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(path))
    dest = os.path.join(CAPTURES, stem + ext)
    n = 0
    while os.path.exists(dest):
        if size is not None and os.path.getsize(dest) == size:
            return dest
        n += 1
        dest = os.path.join(CAPTURES, "%s-%d%s" % (stem, n, ext))
    cam.fetch_file(path, dest + ".part")
    os.replace(dest + ".part", dest)
    if ext.lower() in (".jpg", ".jpeg") or state["latest"] is None or \
            not state["latest"].lower().endswith((".jpg", ".jpeg")):
        state["latest"] = os.path.basename(dest)
    return dest


def card_snapshot():
    if state["transfer"] != "both" or conn_type == "usb":
        return None
    return {e["path"] for e in cam.images()}


def pull_new(seen):
    """Neue Dateien von der Karte holen; die Karte braucht nach dem Auslösen etwas."""
    state["transfer_error"] = None
    try:
        for attempt in range(3):
            new = [e for e in cam.images() if e["path"] not in seen]
            if new:
                for e in jpg_last(new, lambda e: e["name"]):
                    save_capture(e["path"], e["size"])
                    seen.add(e["path"])
                return
            time.sleep(1.5)
        state["transfer_error"] = "No new file found on the card"
    except (CameraError, OSError, ET.ParseError) as e:
        state["transfer_error"] = str(e)


def shot(seen):
    new = cam.shoot()
    if conn_type == "usb":  # USB meldet die neuen Dateien direkt
        if state["transfer"] == "both":
            state["transfer_error"] = None
            try:
                for path in jpg_last(new):
                    save_capture(path)
            except (CameraError, OSError) as e:
                state["transfer_error"] = str(e)
    elif seen is not None:
        pull_new(seen)


def run_job(name, total, work):
    if job["running"]:
        raise CameraError("A series is already running")
    ensure_idle()
    stop_job.clear()
    job.update(name=name, running=True, done=0, total=total, error=None)

    def runner():
        try:
            with capture():
                work(card_snapshot())
        except (CameraError, WriteBlocked, OSError, ValueError, ET.ParseError) as e:
            job["error"] = str(e)
        finally:
            job["running"] = False

    threading.Thread(target=runner, daemon=True).start()


def start_interval(count, seconds):
    count, seconds = int(count), float(seconds)
    if not 1 <= count <= 999:
        raise ValueError("Frame count must be between 1 and 999")
    if seconds < MIN_INTERVAL:
        raise ValueError("Interval must be at least %d s" % MIN_INTERVAL)

    def work(seen):
        for i in range(count):
            if stop_job.is_set():
                return
            begin = time.monotonic()
            shot(seen)
            job["done"] = i + 1
            if i + 1 < count:
                stop_job.wait(max(0, seconds - (time.monotonic() - begin)))

    run_job("Intervall", count, work)


def bracket_plan(enum, current, frames, step):
    """Belichtungswerte einer Reihe, step in Drittelstufen des Kamera-Rasters."""
    if frames not in (3, 5, 7) or step not in (1, 2, 3):
        raise ValueError("Bracketing: 3, 5 or 7 frames, step 1 to 3")
    i = enum.index(current)
    wanted = [i + k * step for k in range(-(frames // 2), frames // 2 + 1)]
    if wanted[0] < 0 or wanted[-1] >= len(enum):
        raise ValueError("Bracketing exceeds the camera's compensation range")
    return [enum[j] for j in wanted]


def start_bracket(frames, step):
    p = cam.props()["expcomp"]
    plan = bracket_plan(p["enum"], p["value"], int(frames), int(step))

    def work(seen):
        try:
            for i, value in enumerate(plan):
                if stop_job.is_set():
                    return
                cam.set_prop("expcomp", value)
                shot(seen)
                job["done"] = i + 1
        finally:
            cam.set_prop("expcomp", p["value"])

    run_job("Reihe", len(plan), work)


def orf_preview(path):
    """Größtes eingebettetes JPEG einer ORF-Datei (Browser können ORF nicht zeigen)."""
    with open(path, "rb") as f:
        data = f.read()
    best, i = b"", data.find(b"\xff\xd8\xff")
    while i >= 0:
        end = data.find(b"\xff\xd9", i)
        if end < 0:
            break
        if end + 2 - i > len(best):
            best = data[i:end + 2]
        i = data.find(b"\xff\xd8\xff", end)
    return best


def local_files():
    if not os.path.isdir(CAPTURES):
        return []
    out = []
    for name in os.listdir(CAPTURES):
        p = os.path.join(CAPTURES, name)
        if name.lower().endswith((".jpg", ".jpeg", ".orf")) and os.path.isfile(p):
            out.append({"name": name, "size": os.path.getsize(p), "mtime": os.path.getmtime(p)})
    return sorted(out, key=lambda e: e["mtime"], reverse=True)


def capture_path(name):
    p = os.path.join(CAPTURES, os.path.basename(name))
    if not os.path.isfile(p):
        raise KeyError("File not found: %s" % name)
    return p


def cached_preview(kind, path, size, fetch):
    """Vorschau von der Karte, auf der Platte gemerkt (Schlüssel: Pfad, Dateigröße, Art).

    Ohne Dateigröße wird nichts gemerkt, weil sich hinter dem Pfad ein anderes Bild verbergen könnte.
    """
    if not size:
        return fetch()
    name = "%s_%s_%s.jpg" % (path.strip("/").replace("/", "_"), int(size), kind)
    dest = os.path.join(PREVIEW_CACHE, name)
    if os.path.isfile(dest):
        with open(dest, "rb") as f:
            return f.read()
    data = fetch()
    if data[:2] == b"\xff\xd8":
        os.makedirs(PREVIEW_CACHE, exist_ok=True)
        with open(dest + ".part", "wb") as f:
            f.write(data)
        os.replace(dest + ".part", dest)
        prune_preview_cache()
    return data


def prune_preview_cache():
    """Cache auf PREVIEW_CACHE_MAX begrenzen, älteste Dateien zuerst löschen (bis 80 %)."""
    files = [e for e in os.scandir(PREVIEW_CACHE) if e.is_file()]
    total = sum(e.stat().st_size for e in files)
    if total <= PREVIEW_CACHE_MAX:
        return
    for e in sorted(files, key=lambda e: e.stat().st_mtime):
        if total <= PREVIEW_CACHE_MAX * 0.8:
            break
        total -= e.stat().st_size
        os.remove(e.path)


def playback(enter):
    """Wi-Fi: Für Playback in den Modus "play", nur dort liefert die Kamera mittlere Vorschauen.

    Der Live View pausiert so lange und läuft beim Verlassen wieder an.
    """
    if conn_type != "wifi":
        return
    if enter:
        if state["play"] is not None:
            return
        ensure_idle()
        resume = live.running
        if resume:
            cam.stop_liveview()
            live.stop()
        cam.set_mode("play")
        state["play"] = {"resume": resume}
    elif state["play"] is not None:
        resume = state["play"]["resume"]
        state["play"] = None
        cam.set_mode("rec")
        if resume:
            start_live()


def lens(path):
    """Objektivdaten der Aufnahme path (JPG auf der Karte), je Pfad nur einmal gelesen."""
    if not path.lower().endswith((".jpg", ".jpeg")):
        raise CameraError("Lens data only from JPG files")
    if path not in lens_cache:
        lens_cache[path] = exif.lens_info(cam.read_head(path, exif.HEAD_BYTES))
    return lens_cache[path]


def preview_path(path):
    """Für Vorschauen das JPG derselben Aufnahme nehmen, falls vorhanden (statt der kleinen Vorschau im ORF)."""
    stem, ext = os.path.splitext(path)
    if ext.lower() != ".orf":
        return path
    for jpg in (".JPG", ".jpg", ".JPEG", ".jpeg"):
        if os.path.isfile(stem + jpg):
            return stem + jpg
    return path


def public_state():
    now = time.time()
    return {
        # busy: Aufnahme-Abfolge oder Auslöser-Befehl läuft (Kamera evtl. nicht im Modus "rec")
        "stage": cam.stage, "busy": busy.locked() or state["pressing"], "live": live.running, "lv_age": live.age, "lvqty": cam.lvqty, "job": job,
        "transfer": state["transfer"], "latest": state["latest"], "play": state["play"] is not None,
        "transfer_error": state["transfer_error"],
        "take": now - state["take"] if state["take"] else None,
        "movie": now - state["movie"]["since"] if state["movie"] else None,
    }


# --- HTTP --------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json", code=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _image(self, body, q):
        """JPG senden; mit Dateigröße in der URL darf der Browser es eine Woche behalten."""
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        if q.get("size"):
            self.send_header("Cache-Control", "private, max-age=%d, immutable" % IMAGE_MAX_AGE)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _trusted(self):
        """Nur die eigene Oberfläche darf die Kamera steuern, keine fremde Webseite."""
        if self.headers.get("Host") not in allowed_hosts:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {"http://" + h for h in allowed_hosts}

    def do_GET(self):
        if not self._trusted():
            return self._send({"error": "Access denied"}, code=403)
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/":
                with open(os.path.join(ROOT, "web", "index.html"), "rb") as f:
                    return self._send(f.read(), "text/html; charset=utf-8")
            if u.path == "/api/connections":
                return self._send(connections())
            if u.path == "/api/local":
                return self._send(local_files())
            if u.path.startswith("/captures/"):
                p = preview_path(capture_path(urllib.parse.unquote(u.path[len("/captures/"):])))
                if p.lower().endswith(".orf"):
                    return self._send(orf_preview(p), "image/jpeg")
                with open(p, "rb") as f:
                    return self._send(f.read(), "image/jpeg")
            if cam is None:
                return self._send({"error": "Not connected"}, code=409)
            if u.path == "/api/status":
                return self._send({
                    "type": conn_type, "features": cam.features,
                    "model": cam.caminfo(), "host": cam.host,
                    "cgis": sorted(cam.commandlist()), "allow_write": cam.allow_write,
                })
            if u.path == "/api/level":
                if conn_type != "usb":
                    raise CameraError("Level Gauge only works over USB")
                return self._send(cam.level())
            if u.path == "/api/afarea":
                return self._send(af_area())
            if u.path == "/api/state":
                return self._send(public_state())
            if u.path == "/api/props":
                return self._send(cam.props())
            if u.path == "/api/afframe":
                return self._send(cam.touch_frame())
            if u.path == "/api/images":
                imgs = cam.images(q.get("dir", "/DCIM"))
                imgs.sort(key=lambda e: (e["date"], e["time"]), reverse=True)
                return self._send(imgs)
            if u.path == "/api/lens":
                return self._send({"lens": lens(q["path"])})
            if u.path == "/api/thumb":
                return self._image(cached_preview("thumb", q["path"], q.get("size"),
                                                  lambda: cam.thumbnail(q["path"])), q)
            if u.path == "/api/resize":  # nur im Modus "play" (Playback über Wi-Fi)
                px = q.get("px", "1024")
                return self._image(cached_preview("r" + px, q["path"], q.get("size"),
                                                  lambda: cam.resizeimg(q["path"], px)), q)
            if u.path == "/api/screen":
                return self._image(cam.screennail(q["path"]), q)
            if u.path == "/api/full":  # im Aufnahmemodus gibt es keine großen Vorschauen
                if not q["path"].lower().endswith((".jpg", ".jpeg")):
                    raise CameraError("Only JPG files can be shown this way")
                return self._image(cam.read_file(q["path"]), q)
            if u.path == "/live.mjpg":
                return self._mjpeg()
            self._send({"error": "not found"}, code=404)
        except (CameraError, WriteBlocked, KeyError, OSError, ET.ParseError) as e:
            self._send({"error": str(e)}, code=502)

    def _mjpeg(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=f")
        self.end_headers()
        seq = 0
        stream = live  # bleibt gültig, auch wenn die Verbindung gewechselt wird
        try:
            while live is stream:
                seq, frame = stream.wait_frame(seq)
                if frame is None:
                    continue
                self.wfile.write(b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(frame))
                self.wfile.write(frame + b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if not self._trusted():
            return self._send({"error": "Access denied"}, code=403)
        try:
            b = self._body()
            extra = self._action(self.path, b)
            if extra is False:
                return self._send({"error": "not found"}, code=404)
            self._send({"ok": True, **(extra or {})})
        except WriteBlocked as e:
            self._send({"error": str(e)}, code=403)
        except (CameraError, KeyError, OSError, ValueError, TypeError,
                ET.ParseError, subprocess.SubprocessError) as e:
            self._send({"error": str(e)}, code=502)

    def _shutter(self, stage):
        """Auslöser-Stufe setzen: 0 loslassen, 1 halb, 2 voll."""
        if cam.stage == 0 and stage:
            ensure_idle()
            state["resume_live"] = live.running
            state["seen"] = card_snapshot()  # im Modus "shutter" nicht mehr lesbar
        cam.press(stage)
        if conn_type == "usb":  # der Live View läuft über USB einfach weiter
            state["resume_live"] = False
            if stage == 0 and state["transfer"] == "both":
                for p in jpg_last(cam.take_new_files()):
                    save_capture(p)
            if stage == 1:
                return {"last_af": cam.last_af}
        elif stage == 0:
            if state["seen"] is not None:
                pull_new(state["seen"])
                state["seen"] = None
            if state["resume_live"]:
                state["resume_live"] = False
                start_live()
        return None

    def _action(self, path, b):
        if path == "/api/connect":
            connect(b["type"])
            return {"type": conn_type}
        if path == "/api/disconnect":
            disconnect()
            return None
        if path == "/api/poweroff":
            power_off()
            return None
        if path == "/api/open":
            subprocess.run(["open", "-a", "OM Workspace", capture_path(b["name"])], check=True)
            return None
        if cam is None:
            raise CameraError("Not connected")
        if path == "/api/refresh":
            if conn_type != "usb":
                raise CameraError("Only needed over USB")
            ensure_idle()
            cam.refresh()
            return None
        if path == "/api/afarea":
            if b.get("focus") and conn_type == "usb":  # All Targets: nur scharfstellen
                cam.focus()
            else:
                set_af_area(b.get("mode"), b.get("field"))
            return af_area()
        if path == "/api/playback":
            playback(b.get("action") == "enter")
            return {"play": state["play"] is not None}
        if path == "/api/liveview":
            if b.get("action") == "start":
                cam.set_mode("rec", b.get("lvqty", "0800x0600") if conn_type == "wifi" else b.get("lvqty"))
                start_live()
            else:
                cam.stop_liveview()
                live.stop()
        elif path == "/api/mode":
            if conn_type == "usb":
                cam.press(0)
            cam.set_mode(b["mode"])
            if b["mode"] == "rec":
                cam.stage = 0  # Notausgang, falls die Kamera in "shutter" hängt
        elif path == "/api/set":
            cam.set_prop(b["prop"], b["value"])
        elif path == "/api/shoot":
            ensure_idle()
            with capture():
                shot(card_snapshot())
        elif path == "/api/shutter":
            state["pressing"] = True
            try:
                return self._shutter(int(b["stage"]))
            finally:
                state["pressing"] = False
        elif path == "/api/interval":
            start_interval(b["count"], b["seconds"])
        elif path == "/api/bracket":
            start_bracket(b["frames"], b["step"])
        elif path == "/api/job/stop":
            stop_job.set()
        elif path == "/api/take":
            if b.get("action") == "prepare":
                ensure_idle()
                cam.take_prepare()
            elif b.get("action") == "start":
                ensure_idle()
                cam.take_start(b.get("exposuremin"), b.get("upperlimit"))
                state["take"] = time.time()
            else:
                try:
                    cam.take_stop()
                finally:
                    state["take"] = None
        elif path == "/api/movie":
            if b.get("action") == "start":
                # Über Wi-Fi nimmt die Kamera Filme nur im Movie-Modus (n) auf: kurz umschalten
                ensure_idle()
                before = cam.prop("takemode")
                if before != "movie":
                    cam.set_prop("takemode", "movie")
                try:
                    cam.movie_start()
                except (CameraError, WriteBlocked):
                    if before != "movie":
                        cam.set_prop("takemode", before)
                    raise
                state["movie"] = {"since": time.time(), "before": before}
            else:
                before = (state["movie"] or {}).get("before")
                try:
                    cam.movie_stop()
                finally:
                    state["movie"] = None
                if before and before != "movie":
                    cam.set_prop("takemode", before)
        elif path == "/api/transfer":
            if b["target"] not in ("sd", "both"):
                raise ValueError("Unknown target")
            state["transfer"] = b["target"]
        elif path == "/api/download":
            return {"saved": save_capture(b["path"], b.get("size"))}
        else:
            return False


def main():
    global CAPTURES, PREVIEW_CACHE
    p = argparse.ArgumentParser(prog="em1-capture", description="Local web app to control an Olympus OM-D E-M1 over Wi-Fi or USB.")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    p.add_argument("--host", default="192.168.0.10", help="camera IP in the camera's Wi-Fi (default 192.168.0.10)")
    p.add_argument("--port", type=int, default=8765, help="local port of the web app (default 8765)")
    p.add_argument("--allow-write", action="store_true",
                   help="allow taking pictures and changing settings (default: read only)")
    p.add_argument("--data-dir", default=os.getcwd(),
                   help="folder for saved pictures (captures/) and the preview cache (out/cache/); default: current folder")
    a = p.parse_args()
    CAPTURES = os.path.join(a.data_dir, "captures")
    PREVIEW_CACHE = os.path.join(a.data_dir, "out", "cache", "previews")
    options.update(host=a.host, allow_write=a.allow_write)
    allowed_hosts.update({"127.0.0.1:%d" % a.port, "localhost:%d" % a.port})
    print("em1-capture %s  http://127.0.0.1:%d  (%s)" % (__version__, a.port, "WRITE ENABLED" if a.allow_write else "read only"))
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
