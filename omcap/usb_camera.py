"""USB-Verbindung zur E-M1 über libgphoto2 (Paket gphoto2 in .venv).

Bietet dieselben Methoden wie camera.Camera, soweit sie über USB sinnvoll sind.
Alles läuft über eine einzige Sitzung: Liveview, Einstellungen und Auslösen
wechseln sich über self._lock ab.

Die Werte sind an der echten Kamera ermittelt:
  d00c  AF-Modus: 33024 All, 33025 Single, 33026 Group (3x3), 33027 Small
  d051  AF-Feld 1..81, zeilenweise von links oben; bei Group die Mitte des Blocks
"""
import re
import subprocess
import threading
import time

from .camera import CameraError, WriteBlocked

AF_MODES = (33024, 33025, 33026, 33027)
EXPOSURE_PROGRAM = {"1": "M", "2": "P", "3": "A", "4": "S", "8": "movie", "11": "B"}
WB_NAMES = ["AUTO", "5300K", "7500K", "6000K", "3000K", "4000K", "Underwater", "5500K Flash",
            "One-touch 1", "One-touch 2", "One-touch 3", "One-touch 4", "CWB"]
FEATURES = ["liveview", "af_area", "af_modes", "stages", "scp", "time_lapse", "ae_bkt",
            "playback", "transfer", "long"]

# d01c: Sonderwerte der Belichtungszeit, Reihenfolge wie die Liste über WLAN (noch ungetestet)
LONG_EXPOSURE = {"livecomp": "4294967290", "livetime": "4294967293", "livebulb": "4294967292"}
# So nennt libgphoto2 diese Werte, teils übersetzt
LONG_LABELS = {"Composite": "livecomp", "Time": "livetime", "Selbstauslöser": "livetime",
               "Bulb": "livebulb", "Langzeitbelichtung": "livebulb"}

# Reihenfolge der Picture-Mode-Werte (d010) wie die Liste colortone über WLAN
PICTURE_NAMES = ["i-Enhance", "Vivid", "Natural", "Muted", "Portrait", "Monotone", "Custom", "e-Portrait",
                 "Underwater", "Color Creator", "Pop Art", "Soft Focus", "Pale&Light Color", "Light Tone",
                 "Grainy Film", "Pin Hole", "Diorama", "Cross Process", "Gentle Sepia", "Dramatic Tone",
                 "Key Line", "Watercolor", "Vintage", "Partial Color"]
DRIVE_KIND = {1: "Single", 2: "Sequential L", 3: "Sequential H", 4: "Self-timer 12s", 5: "Self-timer 2s",
              6: "Custom Self-timer"}
DRIVE_STYLE = {0: "", 1: "Anti-Shock ", 2: "Silent "}

# Auslöser-Stufen von PTP 0x9481, entsprechen exec_shutter über WLAN.
# 1 und 6 sind an der Kamera getestet, 3 und 6 nutzt libgphoto2 zum Auslösen.
OP_FIRST, OP_SECOND, OP_FULL, OP_SECOND_BACK, OP_RELEASE = 1, 2, 3, 4, 6
FOCUS_WAIT = 2.0
FOCUS_POSITION_WAIT = 1.5
SHOT_TIMEOUT = 20


def _gp():
    try:
        import gphoto2
    except ImportError:
        raise CameraError("USB needs the gphoto2 package: start with .venv/bin/python")
    return gphoto2


def detect_name():
    """Name der ersten Kamera am USB laut libgphoto2 (z. B. "Olympus E-M1") oder None.

    Belegt die Kamera nicht.
    """
    try:
        found = _gp().Camera.autodetect()
        return found.get_name(0) if found.count() > 0 else None
    except Exception:
        return None


LV_SIZES = ((640, 480), (800, 600), (1024, 768), (1280, 960))


def lv_size_from_d06d(value, area=None):
    """d06d: Breite in den oberen 16 Bit, Höhe in den unteren (z. B. 0x04000300 = 1024x768).

    Steht dort 0 (kein Live View), die kleinste übliche Größe nehmen, in die der AF-Bereich passt.
    """
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        v = 0
    w, h = v >> 16, v & 0xFFFF
    if w and h:
        return w, h
    for w, h in LV_SIZES:
        if not area or (area["x1"] <= w and area["y1"] <= h):
            return w, h
    return 1280, 960


def _shutter_names(choices):
    names = {}
    for c in choices:
        names[c] = c.split("/", 1)[1] if c.startswith("1/") else c + '"'
    return names


def _ev_names(choices):
    return {c: ("%+.1f" % float(c) if float(c) else "0.0") for c in choices}


def _drive_names(choices):
    return {c: DRIVE_STYLE.get(int(c) >> 4, "") + DRIVE_KIND.get(int(c) & 15, c) for c in choices}


# Werte von d010 in der Reihenfolge von PICTURE_NAMES; 33537 = Vivid und 2 = Natural sind bestätigt
PICTURE_VALUES = [33281, 33537, 2, 1, 32771, 32769, 33025, 33793, 34561, 34049] + list(range(34305, 34319))


def _picture_names(choices):
    table = dict(zip(map(str, PICTURE_VALUES), PICTURE_NAMES))
    return {c: table.get(str(c), c) for c in choices}


def parse_battery(value):
    """Akkustand in Prozent aus dem gphoto2-Wert ('80%', '80', 80), sonst None."""
    m = re.fullmatch(r"\s*(\d{1,3})\s*%?\s*", str(value))
    return int(m.group(1)) if m and int(m.group(1)) <= 100 else None


def free_kbytes(infos):
    """Summe des freien Platzes (KB) aus get_storageinfo(), None ohne Angabe."""
    total = None
    for i in infos or []:
        free = getattr(i, "freekbytes", None)
        if isinstance(free, int) and free >= 0:
            total = (total or 0) + free
    return total


class UsbLive:
    """Gleiche Schnittstelle wie liveview.LiveView, Bilder kommen per USB."""

    def __init__(self, camera):
        self.camera = camera
        self.frame = None
        self.seq = 0
        self.last_frame = None
        self.cond = threading.Condition()
        self._run = False
        self._thread = None

    @property
    def running(self):
        return self._run

    @property
    def age(self):
        return None if self.last_frame is None else time.monotonic() - self.last_frame

    def start(self):
        self.stop()
        self.last_frame = time.monotonic()
        self._run = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._run = False
        if self._thread:
            self._thread.join(3)
            self._thread = None

    def _loop(self):
        failures = 0
        while self._run:
            if self.camera.hold:  # Auslösen oder Kartenliste: Verbindung nicht stören
                failures = 0
                time.sleep(0.05)
                continue
            data = self.camera.preview_frame()
            if data is None:
                failures += 1
                if failures >= 10 and not self.camera.shooting:
                    self.camera.reopen()  # Sitzung abgerissen: neu aufbauen
                    failures = 0
                time.sleep(0.3)
                continue
            failures = 0
            with self.cond:
                self.frame = data
                self.seq += 1
                self.last_frame = time.monotonic()
                self.cond.notify_all()
            time.sleep(0.005)  # andere Befehle an die Kamera lassen

    def wait_frame(self, last_seq, timeout=3.0):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq, timeout)
            return self.seq, self.frame


class UsbCamera:
    usb = True
    host = "USB"
    stage = 0
    lvqty = None
    features = FEATURES

    # Einstellung wie bei WLAN benannt -> gphoto-Name, Anzeigenamen aus den Auswahlwerten
    PROPS = {
        "shutspeedvalue": ("shutterspeed", _shutter_names),
        "focalvalue": ("aperture", None),
        "expcomp": ("exposurecompensation", _ev_names),
        "isospeedvalue": ("iso", lambda ch: {ch[0]: "AUTO", ch[1]: "LOW"}),
        "wbvalue": ("whitebalance", lambda ch: dict(zip(ch, WB_NAMES)) if len(ch) == len(WB_NAMES) else {}),
        "drivemode": ("d009", _drive_names),
        "colortone": ("d010", _picture_names),
        "artfilter": ("d010", _picture_names),
    }

    def __init__(self, allow_write=False):
        self.allow_write = allow_write
        self.stage = 0
        self._new_files = []
        self.last_jpg = None  # zuletzt von der Kamera gemeldetes JPG
        self._pending = []
        self._files = None
        self._event_log = []
        self.last_af = None
        self.gp = _gp()
        self._lock = threading.Lock()
        self.hold = 0
        self.shooting = False  # beim Auslösen sind kurze Bildausfälle normal
        self._c = self.gp.Camera()
        self._open()
        self.live = UsbLive(self)

    def _open(self):
        error = None
        for _ in range(4):
            # Der macOS-Dienst ptpcamerad belegt die Kamera, sobald sie angesteckt wird.
            subprocess.run(["killall", "-9", "ptpcamerad"], capture_output=True)
            try:
                self._c.init()
                self._c.get_single_config("d00c")  # Sitzung vollständig aufgebaut?
                return
            except self.gp.GPhoto2Error as e:
                error = e
                try:
                    self._c.exit()
                except self.gp.GPhoto2Error:
                    pass
                self._c = self.gp.Camera()
        raise CameraError("USB camera not reachable: %s" % error)

    def reopen(self):
        with self._lock:
            try:
                self._c.exit()
            except self.gp.GPhoto2Error:
                pass
            self._c = self.gp.Camera()
            try:
                self._open()
            except CameraError:
                pass

    def refresh(self):
        """Modusrad und andere Kameraänderungen kommen erst mit einer neuen Sitzung an."""
        self.hold += 1
        try:
            self.reopen()
        finally:
            self.hold -= 1

    def close(self):
        self.live.stop()
        with self._lock:
            try:
                self._c.exit()
            except self.gp.GPhoto2Error:
                pass

    def _call(self, fn, *args):
        with self._lock:
            try:
                return fn(*args)
            except self.gp.GPhoto2Error as e:
                raise CameraError("USB: %s" % e)

    def _need_write(self):
        if not self.allow_write:
            raise WriteBlocked("Writing not enabled (--allow-write)")

    def _value(self, name):
        return self._call(lambda: self._c.get_single_config(name).get_value())

    def _set(self, name, value):
        self._need_write()

        def apply():
            w = self._c.get_single_config(name)
            w.set_value(str(value))
            self._c.set_single_config(name, w)
        self._call(apply)

    # --- Lesen ---------------------------------------------------------------
    def caminfo(self):
        return self._value("cameramodel")

    def commandlist(self):
        return []

    def props(self):
        out = {"takemode": {"value": EXPOSURE_PROGRAM.get(str(self._value("d006")), "?"),
                            "writable": False, "enum": []}}
        for key, (name, namer) in self.PROPS.items():
            def read():
                w = self._c.get_single_config(name)
                return w.get_value(), list(w.get_choices())
            value, choices = self._call(read)
            if key == "artfilter":  # d010 enthält auch die Art Filter (ab 34305)
                choices = [c for c in choices if int(c) >= 34305]
            if key == "shutspeedvalue":  # nur M: BULB, LIVE TIME, LIVECOMP stehen in d01c
                choices = [c for c in choices if re.fullmatch(r"(1/)?\d+(\.\d+)?", c)]
                specials = list(LONG_EXPOSURE)
                value = LONG_LABELS.get(value, value)
                choices = specials + choices
            out[key] = {"value": value, "writable": True, "enum": choices,
                        "names": namer([c for c in choices if not c.startswith("live")]) if namer else {}}
        return out

    def free_bytes(self):
        kb = free_kbytes(self._call(self._c.get_storageinfo))
        return kb * 1024 if kb is not None else None

    def battery(self):
        # nur diesen einen Wert lesen, get_value() auf der ganzen Gruppe "other" stürzt libgphoto2 ab
        try:
            return parse_battery(self._value("batterylevel"))
        except CameraError:
            return None

    def level(self):
        """Lagewerte in Grad und aktueller Modus.

        d053/d055 sind die echten Lagewerte, die Kamera aktualisiert sie aber nur beim
        Aufbau der Sitzung. Deshalb ist die Level Gauge über USB (noch) ausgeblendet.
        """
        def signed(v):
            v = int(float(v))
            return (v - 65536 if v > 32767 else v) / 10
        return {"a": signed(self._value("d053")), "b": signed(self._value("d055")),
                "mode": EXPOSURE_PROGRAM.get(str(self._value("d006")), "?")}

    def af_area(self):
        area = {"x0": 216, "x1": 1060, "y0": 160, "y1": 796, "w": 1280, "h": 960}
        for key, name in (("x0", "d05a"), ("x1", "d05b"), ("y0", "d071"), ("y1", "d072")):
            area[key] = int(self._value(name))
        # Die Kamera meldet den AF-Bereich im Raster der Live-View-Größe (d06d), nicht fest 1280x960
        area["w"], area["h"] = self._lv_size(area)
        return {"mode": int(self._value("d00c")), "field": int(self._value("d051")), "area": area,
                "last_af": self.last_af}

    def _lv_size(self, area):
        """Live-View-Größe aus d06d (Breite << 16 | Höhe), sonst aus dem AF-Bereich geschlossen."""
        try:
            return lv_size_from_d06d(self._value("d06d"), area)
        except CameraError:
            return lv_size_from_d06d(0, area)

    def preview_frame(self):
        with self._lock:
            try:
                f = self._c.capture_preview()
                data = bytes(memoryview(f.get_data_and_size()))
                # Während und direkt nach dem Auslösen kommen keine gültigen Bilder
                return data if data[:2] == b"\xff\xd8" and b"\xff\xd9" in data[-64:] else None
            except self.gp.GPhoto2Error:
                return None

    def fetch_file(self, path, dest):
        folder, name = path.rsplit("/", 1)

        def get():
            self._c.file_get(folder, name, self.gp.GP_FILE_TYPE_NORMAL).save(dest)
        self._call(get)

    def _file_bytes(self, path, kind):
        folder, name = path.rsplit("/", 1)

        def get():
            f = self._c.file_get(folder, name, kind)
            return bytes(memoryview(f.get_data_and_size()))
        return self._call(get)

    def thumbnail(self, path):
        return self._file_bytes(path, self.gp.GP_FILE_TYPE_PREVIEW)

    def screennail(self, path):
        raise CameraError("No medium-size preview over USB")

    def resizeimg(self, path, size):
        raise CameraError("No medium-size preview over USB")

    def read_file(self, path):
        return self._file_bytes(path, self.gp.GP_FILE_TYPE_NORMAL)

    def read_head(self, path, size):
        """libgphoto2 liest nur ganze Dateien."""
        return self.read_file(path)[:size]

    def lens_focal(self):
        """Brennweitenbereich des Objektivs aus d04a (Bereich = kürzeste/längste, Wert = aktuell)."""
        def read():
            w = self._c.get_single_config("d04a")
            now = int(float(w.get_value()))
            try:
                lo, hi, _ = w.get_range()  # nur bei Bereichs-Widgets
            except Exception:
                lo = hi = None
            return (int(lo) if lo else None), (int(hi) if hi else None), now
        return self._call(read)

    def _list(self, fn, folder):
        names = self._call(fn, folder)
        return [names.get_name(i) for i in range(names.count())]

    def _entry(self, folder, name):
        full = self._call(self._c.file_get_info, folder, name)  # hält die Daten von .file am Leben
        info = full.file
        t = time.localtime(info.mtime)
        time.sleep(0.002)  # Live View und Befehle nicht aushungern
        return {
            "dir": folder, "name": name, "size": info.size, "isdir": False,
            "date": ((t.tm_year - 1980) << 9) | (t.tm_mon << 5) | t.tm_mday,
            "time": (t.tm_hour << 11) | (t.tm_min << 5) | (t.tm_sec // 2),
            "path": folder.rstrip("/") + "/" + name,
        }

    def images(self, root="/"):
        """Alle Dateien der Karte, Datum und Zeit im FAT-Format wie über WLAN.

        Die Liste dauert über USB rund 30 s und wird daher nur einmal geholt;
        neue Aufnahmen kommen über die Kamera-Ereignisse dazu.
        """
        if self._files is None:
            files = {}
            stack = ["/"]
            self.hold += 1  # Live View pausiert, sonst bricht die Liste ab
            try:
                while stack:
                    folder = stack.pop()
                    for sub in self._list(self._c.folder_list_folders, folder):
                        stack.append(folder.rstrip("/") + "/" + sub)
                    for name in self._list(self._c.folder_list_files, folder):
                        e = self._entry(folder, name)
                        files[e["path"]] = e
            finally:
                self.hold -= 1
            self._files = files
        pending, self._pending = self._pending, []
        for path in pending:
            folder, name = path.rsplit("/", 1)
            self._files[path] = self._entry(folder, name)
        return list(self._files.values())

    # --- Schreiben -----------------------------------------------------------
    def set_mode(self, mode, lvqty=None):
        """Über USB gibt es keine Modi wie bei WLAN.

        Die Live-View-Größe ist nicht wählbar: libgphoto2 setzt d06d bei jedem
        Livebild fest auf 1024x768.
        """

    def start_liveview(self, port):
        self._need_write()

    def stop_liveview(self):
        pass

    def set_prop(self, prop, value):
        if prop not in self.PROPS:
            raise CameraError("Not available over USB: %s" % prop)
        if prop == "shutspeedvalue" and value in LONG_EXPOSURE:
            self._set("d01c", LONG_EXPOSURE[value])
        else:
            self._set(self.PROPS[prop][0], value)

    def set_af_area(self, mode=None, field=None):
        if mode is not None:
            if int(mode) not in AF_MODES:
                raise CameraError("Unknown AF mode: %r" % mode)
            self._set("d00c", int(mode))
        if field is not None:
            if not 1 <= int(field) <= 81:
                raise CameraError("AF point must be between 1 and 81")
            self._set("d051", int(field))

    def _pulse(self):
        self._shutter(OP_FULL)
        self._shutter(OP_RELEASE)

    def take_prepare(self):
        """LIVECOMP: erster Druck, die Kamera bereitet die Aufnahme vor."""
        self._pulse()

    def _is_bulb(self):
        return LONG_LABELS.get(self._value("shutterspeed")) == "livebulb"

    def take_start(self, exposuremin=None, upperlimit=None):
        # BULB läuft, solange gedrückt ist; LIVE TIME und LIVECOMP mit je einem Druck
        if self._is_bulb():
            self._shutter(OP_FULL)
        else:
            self._pulse()

    def take_stop(self):
        if self._is_bulb():
            self._shutter(OP_RELEASE)
        else:
            self._pulse()
        self._events(2.0)

    def _shutter(self, step):
        self._need_write()

        def send():
            w = self._c.get_single_config("opcode")
            w.set_value("0x9481,0x%x" % step)
            self._c.set_single_config("opcode", w)
        self._call(send)

    def _events(self, seconds, stop=None):
        """Ereignisse abholen, ohne die Kamera dazwischen zu blockieren."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            kind, data = self._call(self._c.wait_for_event, 150)
            if kind == self.gp.GP_EVENT_FILE_ADDED:
                self._new_files.append("%s/%s" % (data.folder, data.name))
                if data.name.lower().endswith((".jpg", ".jpeg")):
                    self.last_jpg = "%s/%s" % (data.folder, data.name)  # für Objektivdaten
                self._pending.append("%s/%s" % (data.folder, data.name))
            elif kind == self.gp.GP_EVENT_UNKNOWN:
                self._event_log.append(str(data))
                if stop and stop in str(data).lower():
                    return True
            if self._new_files and kind == self.gp.GP_EVENT_TIMEOUT and stop == "quiet":
                return True
        return False

    def take_new_files(self):
        new = list(dict.fromkeys(self._new_files))
        self._new_files = []
        return new

    def press(self, stage):
        """Auslöser unabhängig bedienen: 0 loslassen, 1 halb, 2 voll."""
        if stage not in (0, 1, 2):
            raise CameraError("Unknown shutter position: %r" % stage)
        if stage == self.stage:
            return
        if self.stage == 0:
            self.last_af = None
            self._shutter(OP_FIRST)
            self.stage = 1
            if stage == 1:
                self._read_focus_position()
            else:
                self._events(FOCUS_WAIT)
                self._shutter(OP_SECOND)
                self.stage = 2
        elif stage == 2:
            self._shutter(OP_SECOND)
            self.stage = 2
        elif stage == 1:
            self._shutter(OP_SECOND_BACK)
            self.stage = 1
        else:
            full = self.stage == 2
            try:
                if full:
                    self._shutter(OP_SECOND_BACK)
            finally:
                self.stage = 0
                self._shutter(OP_RELEASE)
            self._events(2.0 if full else 0.2, "quiet" if full else None)

    def _read_focus_position(self):
        """Fokusposition im Raster 1280x960, nur während des Halbdrucks gültig.

        Die Kamera meldet sie erst, wenn der Fokus sitzt.
        """
        x = y = 0
        end = time.monotonic() + FOCUS_POSITION_WAIT
        while not (x or y) and time.monotonic() < end:
            self._events(0.1)
            x, y = int(float(self._value("d05d"))), int(float(self._value("d05e")))
        self.last_af = {"x": x, "y": y}

    def focus(self):
        """Scharfstellen wie Halbdruck und Loslassen."""
        if self.stage:
            return
        self._events(0.3)  # alte Ereignisse abholen, sonst endet das Warten zu früh
        self._event_log = []
        self._shutter(OP_FIRST)
        try:
            self._events(FOCUS_WAIT, "c003")
            self._read_focus_position()
        finally:
            self._shutter(OP_RELEASE)
        self._events(0.2)

    def shoot(self):
        """Einmal auslösen. Gibt die neuen Dateipfade zurück (JPG und ORF)."""
        self._new_files = []
        self.shooting = True  # der Live View läuft weiter, auch wenn die Kamera nicht auslöst
        t0 = time.monotonic()
        marks = []
        # Live View schon vor dem Auslösen anhalten: Eine Vorschau-Anfrage, die während des
        # Speicherns läuft, blockiert die USB-Verbindung bis zu einer Minute (gemessen 2026-11-09).
        self.hold += 1
        try:
            with self._lock:  # laufende Vorschau-Anfrage zu Ende kommen lassen
                pass
            marks.append(("paused", time.monotonic() - t0))
            self._shutter(OP_FULL)
            self._shutter(OP_RELEASE)
            marks.append(("released", time.monotonic() - t0))
            self._events(SHOT_TIMEOUT, "quiet")
            marks.append(("files", time.monotonic() - t0))
            if self._new_files:
                self._events(1.5)  # das zweite Format (ORF oder JPG) folgt kurz danach
        finally:
            self.hold -= 1
            self.shooting = False
            marks.append(("done", time.monotonic() - t0))
            print("USB shot: " + ", ".join("%s %.1f s" % m for m in marks), flush=True)
        new = self.take_new_files()
        if not new:
            raise CameraError("Camera did not release, probably no focus found")
        return new
