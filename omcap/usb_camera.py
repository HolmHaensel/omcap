"""USB connection to the E-M1 via libgphoto2 (package gphoto2 in .venv).

Offers the same methods as camera.Camera, as far as they make sense over USB.
Everything runs through a single session: live view, settings and shooting
take turns via self._lock.

The values were determined on the real camera:
  d00c  AF mode: 33024 All, 33025 Single, 33026 Group (3x3), 33027 Small
  d051  AF field 1..81, row by row from top left; for Group the centre of the block
"""
import re
import subprocess
import threading
import time

from .camera import CameraError, WriteBlocked


def _check_usb_path(path):
    """Card paths over USB look like /store_00010001/DCIM/111OLYMP/P1012345.JPG."""
    if not re.match(r"^/store_[0-9A-Fa-f]{8}/DCIM/", path) or ".." in path:
        raise CameraError("Invalid path: %r" % path)

AF_MODES = (33024, 33025, 33026, 33027)
AF_ALL = 33024
EXPOSURE_PROGRAM = {"1": "M", "2": "P", "3": "A", "4": "S", "8": "movie", "11": "B"}
WB_NAMES = ["AUTO", "5300K", "7500K", "6000K", "3000K", "4000K", "Underwater", "5500K Flash",
            "One-touch 1", "One-touch 2", "One-touch 3", "One-touch 4", "CWB"]
FEATURES = ["liveview", "af_area", "af_modes", "stages", "scp", "time_lapse", "ae_bkt",
            "playback", "transfer", "long"]

# d01c: special exposure time values, order as in the Wi-Fi list (still untested)
LONG_EXPOSURE = {"livecomp": "4294967290", "livetime": "4294967293", "livebulb": "4294967292"}
# This is how libgphoto2 names these values, partly translated
LONG_LABELS = {"Composite": "livecomp", "Time": "livetime", "Selbstauslöser": "livetime",
               "Bulb": "livebulb", "Langzeitbelichtung": "livebulb"}

# Order of the picture mode values (d010) as in the colortone list over Wi-Fi
PICTURE_NAMES = ["i-Enhance", "Vivid", "Natural", "Muted", "Portrait", "Monotone", "Custom", "e-Portrait",
                 "Underwater", "Color Creator", "Pop Art", "Soft Focus", "Pale&Light Color", "Light Tone",
                 "Grainy Film", "Pin Hole", "Diorama", "Cross Process", "Gentle Sepia", "Dramatic Tone",
                 "Key Line", "Watercolor", "Vintage", "Partial Color"]
DRIVE_KIND = {1: "Single", 2: "Sequential L", 3: "Sequential H", 4: "Self-timer 12s", 5: "Self-timer 2s",
              6: "Custom Self-timer"}
DRIVE_STYLE = {0: "", 1: "Anti-Shock ", 2: "Silent "}

# Shutter stages of PTP 0x9481, matching exec_shutter over Wi-Fi.
# 1 and 6 are tested on the camera, 3 and 6 are what libgphoto2 uses to release.
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
    """Name of the first camera on USB according to libgphoto2 (e.g. "Olympus E-M1") or None.

    Does not claim the camera.
    """
    try:
        found = _gp().Camera.autodetect()
        return found.get_name(0) if found.count() > 0 else None
    except Exception:
        return None


LV_SIZES = ((640, 480), (800, 600), (1024, 768), (1280, 960))


def af_raster(area):
    """Grid of the AF area from its position: centred, so width x0+x1 and height y0+y1.

    Rounded to the nearest usual live view size (values are accurate to ±4 px).
    """
    w, h = area["x0"] + area["x1"], area["y0"] + area["y1"]
    return min(LV_SIZES, key=lambda s: abs(s[0] - w) + abs(s[1] - h))


def focus_in_raster(pos, area):
    """Focus position (d05d/d05e) is always in 1280×960 (its PTP range); map it to the AF area grid."""
    if not pos or not (pos.get("x") or pos.get("y")):
        return None  # 0,0: the camera found no focus
    return {"x": pos["x"] * area["w"] / 1280.0, "y": pos["y"] * area["h"] / 960.0}


def lv_size_from_d06d(value, area=None):
    """d06d: width in the upper 16 bits, height in the lower (e.g. 0x04000300 = 1024x768).

    If it is 0 (no live view), take the smallest usual size the AF area fits into.
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


# d010 values in the order of PICTURE_NAMES; 33537 = Vivid and 2 = Natural are confirmed
PICTURE_VALUES = [33281, 33537, 2, 1, 32771, 32769, 33025, 33793, 34561, 34049] + list(range(34305, 34319))


def _picture_names(choices):
    table = dict(zip(map(str, PICTURE_VALUES), PICTURE_NAMES))
    return {c: table.get(str(c), c) for c in choices}


def parse_battery(value):
    """Battery level in percent from the gphoto2 value ('80%', '80', 80), else None."""
    m = re.fullmatch(r"\s*(\d{1,3})\s*%?\s*", str(value))
    return int(m.group(1)) if m and int(m.group(1)) <= 100 else None


def free_kbytes(infos):
    """Sum of the free space (KB) from get_storageinfo(), None if not given."""
    total = None
    for i in infos or []:
        free = getattr(i, "freekbytes", None)
        if isinstance(free, int) and free >= 0:
            total = (total or 0) + free
    return total


class UsbLive:
    """Same interface as liveview.LiveView, images arrive over USB."""

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
            if self.camera.hold:  # shooting or card list: do not disturb the connection
                failures = 0
                time.sleep(0.05)
                continue
            data = self.camera.preview_frame()
            if data is None:
                failures += 1
                if failures >= 10 and not self.camera.shooting and not self.camera.stage:
                    self.camera.reopen("live view failed 10x")  # session broken: rebuild
                    failures = 0
                time.sleep(0.3)
                continue
            failures = 0
            with self.cond:
                self.frame = data
                self.seq += 1
                self.last_frame = time.monotonic()
                self.cond.notify_all()
            time.sleep(0.005)  # leave other commands to the camera

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

    # setting named as over Wi-Fi -> gphoto name, display names from the choice values
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
        self.last_jpg = None  # JPG last reported by the camera
        self._pending = []
        self._files = None
        self._event_log = []
        self.last_af = None
        self.gp = _gp()
        self._lock = threading.Lock()
        self.hold = 0
        self.shooting = False  # short image dropouts are normal while shooting
        self._c = self.gp.Camera()
        self._open()
        self.live = UsbLive(self)

    def _open(self):
        error = None
        for _ in range(4):
            # The macOS service ptpcamerad claims the camera as soon as it is plugged in.
            subprocess.run(["killall", "-9", "ptpcamerad"], capture_output=True)
            try:
                self._c.init()
                self._c.get_single_config("d00c")  # session fully established?
                return
            except self.gp.GPhoto2Error as e:
                error = e
                try:
                    self._c.exit()
                except self.gp.GPhoto2Error:
                    pass
                self._c = self.gp.Camera()
        raise CameraError("USB camera not reachable: %s" % error)

    def reopen(self, reason="?"):
        # logged: a rebuilt session drops live view for ~9 s and loses libgphoto2's file index
        print("USB session reopened (%s)" % reason, flush=True)
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
        """Mode dial and other camera changes only arrive with a new session."""
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

    # --- Read ---------------------------------------------------------------
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
            if key == "artfilter":  # d010 also holds the kind of filter (from 34305)
                choices = [c for c in choices if int(c) >= 34305]
            if key == "shutspeedvalue":  # M only: BULB, LIVE TIME, LIVECOMP are in d01c
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
        # read only this one value, get_value() on the whole "other" group crashes libgphoto2
        try:
            return parse_battery(self._value("batterylevel"))
        except CameraError:
            return None

    def level(self):
        """Attitude values in degrees and current mode.

        d053/d055 are the real attitude values, but the camera only updates them when
        the session is established. Hence the Level Gauge is (still) hidden over USB.
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
        # The AF area is centred, so its grid is (x0+x1) × (y0+y1) – as with Wi-Fi
        # (touchactiveframe). d06d is no good: depending on the session the camera reports the area
        # in 1280×960 or 1024×768, independent of the current d06d (measured 2026-11-09).
        area["w"], area["h"] = af_raster(area)
        self.af_mode = int(self._value("d00c"))
        return {"mode": self.af_mode, "field": int(self._value("d051")), "area": area,
                "last_af": focus_in_raster(self.last_af, area), "focus_ok": getattr(self, "focus_ok", None)}

    def preview_frame(self):
        with self._lock:
            try:
                f = self._c.capture_preview()
                data = bytes(memoryview(f.get_data_and_size()))
                # no valid images during and right after shooting
                return data if data[:2] == b"\xff\xd8" and b"\xff\xd9" in data[-64:] else None
            except self.gp.GPhoto2Error:
                return None

    def fetch_file(self, path, dest):
        _check_usb_path(path)
        folder, name = path.rsplit("/", 1)

        def get():
            self._c.file_get(folder, name, self.gp.GP_FILE_TYPE_NORMAL).save(dest)
        self._call(get)

    def _file_bytes(self, path, kind):
        _check_usb_path(path)
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
        """First `size` bytes of a file by a partial read (libgphoto2 2.5+).

        Falls back to reading the whole file when the binding or the camera cannot do it.
        """
        _check_usb_path(path)
        folder, name = path.rsplit("/", 1)
        if hasattr(self._c, "file_read") and not getattr(self, "_no_partial", False):
            def part():
                buf = bytearray(size)
                try:
                    got = self._c.file_read(folder, name, self.gp.GP_FILE_TYPE_NORMAL, 0, memoryview(buf))
                except self.gp.GPhoto2Error as e:
                    if getattr(e, "code", None) == self.gp.GP_ERROR_NOT_SUPPORTED:
                        raise NotImplementedError(str(e))  # the camera cannot read partially
                    raise CameraError("USB: %s" % e)  # passing error (busy, timeout)
                # the binding returns the count read; anything else (0, error code) means no data
                if not isinstance(got, int) or got <= 0:
                    raise CameraError("USB: partial read returned nothing")
                return bytes(buf[:min(got, size)])
            try:
                return self._call(part)
            except (TypeError, AttributeError, NotImplementedError):
                self._no_partial = True  # binding or camera cannot do it: stop trying this session
            except CameraError:
                pass  # passing problem: full read for this file only, try partial again next time
        return self.read_file(path)[:size]

    def warm_index(self):
        """Read the card directory once so that the first photo of the session does not wait ~60 s.

        libgphoto2 reads the whole card on the first new image (measured: 1st photo 60 s,
        2nd photo 6 s). Listing the newest DCIM folder triggers the same read.
        Returns the newest JPG (for the lens data) or None.
        """
        self.hold += 1  # live view paused, otherwise the read aborts
        try:
            folders = []
            for store in self._list(self._c.folder_list_folders, "/"):
                base = "/" + store + "/DCIM"
                try:
                    folders += [base + "/" + f for f in self._list(self._c.folder_list_folders, base)]
                except CameraError:
                    continue
            newest = None
            # DCF folders start with the number (100…999): the highest is the current one
            for folder in sorted(folders, key=lambda f: f.rsplit("/", 1)[1][:3], reverse=True):
                jpgs = [n for n in self._list(self._c.folder_list_files, folder)
                        if n.lower().endswith((".jpg", ".jpeg"))]
                if jpgs:
                    # DCF file number is in characters 5–8 (PB082156, _B082156)
                    newest = folder + "/" + max(jpgs, key=lambda n: n[4:8])
                    break
            if newest and not self.last_jpg:
                self.last_jpg = newest
            return newest
        finally:
            self.hold -= 1

    def lens_focal(self):
        """Focal length range of the lens from d04a (range = shortest/longest, value = current)."""
        def read():
            w = self._c.get_single_config("d04a")
            now = int(float(w.get_value()))
            try:
                lo, hi, _ = w.get_range()  # range widgets only
            except Exception:
                lo = hi = None
            return (int(lo) if lo else None), (int(hi) if hi else None), now
        return self._call(read)

    def _list(self, fn, folder):
        names = self._call(fn, folder)
        return [names.get_name(i) for i in range(names.count())]

    def _entry(self, folder, name):
        full = self._call(self._c.file_get_info, folder, name)  # keeps the data of .file alive
        info = full.file
        t = time.localtime(info.mtime)
        time.sleep(0.002)  # do not starve live view and commands
        return {
            "dir": folder, "name": name, "size": info.size, "isdir": False,
            "date": ((t.tm_year - 1980) << 9) | (t.tm_mon << 5) | t.tm_mday,
            "time": (t.tm_hour << 11) | (t.tm_min << 5) | (t.tm_sec // 2),
            "path": folder.rstrip("/") + "/" + name,
        }

    def images(self, root="/"):
        """All files on the card, date and time in FAT format as over Wi-Fi.

        The list takes about 30 s over USB and is therefore fetched only once;
        new shots are added via the camera events.
        """
        if self._files is None:
            files = {}
            stack = ["/"]
            self.hold += 1  # live view paused, otherwise the list aborts
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

    # --- Write -----------------------------------------------------------
    def set_mode(self, mode, lvqty=None):
        """There are no modes over USB as with Wi-Fi.

        The live view size cannot be chosen: libgphoto2 fixes d06d at 1024x768
        for every live image.
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
            self.af_mode = int(mode)
        if field is not None:
            if not 1 <= int(field) <= 81:
                raise CameraError("AF point must be between 1 and 81")
            self._set("d051", int(field))

    def _pulse(self):
        self._shutter(OP_FULL)
        self._shutter(OP_RELEASE)

    def take_prepare(self):
        """LIVECOMP: first press, the camera prepares the exposure."""
        self._pulse()

    def _is_bulb(self):
        return LONG_LABELS.get(self._value("shutterspeed")) == "livebulb"

    def take_start(self, exposuremin=None, upperlimit=None):
        # BULB runs while the button is held; LIVE TIME and LIVECOMP take one press each
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
        """Collect events without blocking the camera in between."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            kind, data = self._call(self._c.wait_for_event, 150)
            if kind == self.gp.GP_EVENT_FILE_ADDED:
                self._new_files.append("%s/%s" % (data.folder, data.name))
                if data.name.lower().endswith((".jpg", ".jpeg")):
                    self.last_jpg = "%s/%s" % (data.folder, data.name)  # for lens data
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
        """Operate the shutter button independently: 0 release, 1 half, 2 full."""
        if stage not in (0, 1, 2):
            raise CameraError("Unknown shutter position: %r" % stage)
        if stage == self.stage:
            return
        if self.stage == 0:
            # keep last_af: _read_focus_position waits until the camera reports a new position
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
        """Focus position in the 1280x960 grid, valid only during half press.

        The camera only reports it once focus is locked.
        The value lags behind: right after AF it often still holds the previous position
        (measured 2026-11-09). So wait until it differs from the last known one; if it never
        changes within the wait (same spot again), keep it.
        """
        prev = (self.last_af or {}).get("x"), (self.last_af or {}).get("y")
        x = y = 0
        end = time.monotonic() + FOCUS_POSITION_WAIT
        while time.monotonic() < end:
            self._events(0.1)
            x, y = int(float(self._value("d05d"))), int(float(self._value("d05e")))
            if (x or y) and (x, y) != prev:
                break
        self.last_af = {"x": x, "y": y}

    def focus(self):
        """Focus like half press and release. Returns True when the camera confirmed focus (event c003).

        Live view is paused meanwhile: during AF the camera delivers no preview frames, and ten
        failed frames would make the live view loop rebuild the whole session (~9 s, file index lost).
        """
        self.focus_ok = None
        if self.stage:
            return None
        self.hold += 1
        try:
            with self._lock:  # let an in-flight preview request finish
                pass
            self._events(0.1)  # collect old events, otherwise the wait ends too early
            self._event_log = []
            self._shutter(OP_FIRST)
            try:
                self.focus_ok = bool(self._events(FOCUS_WAIT, "c003"))
                # the position is only used for All Targets; reading it costs up to 1.5 s
                if getattr(self, "af_mode", AF_ALL) == AF_ALL:
                    self._read_focus_position()
            finally:
                self._shutter(OP_RELEASE)
            self._events(0.2)
        finally:
            self.hold -= 1
        return self.focus_ok

    def shoot(self):
        """Release once. Returns the new file paths (JPG and ORF)."""
        self._new_files = []
        self.shooting = True  # the live view keeps running even if the camera does not release
        t0 = time.monotonic()
        marks = []
        # Stop the live view before shooting: a preview request running during
        # saving blocks the USB connection for up to a minute (measured 2026-11-09).
        self.hold += 1
        try:
            with self._lock:  # let a running preview request finish
                pass
            marks.append(("paused", time.monotonic() - t0))
            self._shutter(OP_FULL)
            self._shutter(OP_RELEASE)
            marks.append(("released", time.monotonic() - t0))
            self._events(SHOT_TIMEOUT, "quiet")
            marks.append(("files", time.monotonic() - t0))
            if self._new_files:
                self._events(1.5)  # the second format (ORF or JPG) follows shortly after
        finally:
            self.hold -= 1
            self.shooting = False
            marks.append(("done", time.monotonic() - t0))
            print("USB shot: " + ", ".join("%s %.1f s" % m for m in marks), flush=True)
        new = self.take_new_files()
        if not new:
            raise CameraError("Camera did not release, probably no focus found")
        return new
