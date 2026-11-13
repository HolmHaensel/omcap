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
            "playback", "transfer", "long", "mf_drive", "movie"]

# Movie button, PTP 0x948C (Olympus OM-D MovieRecButton): 1 press, 0 release; each press toggles recording.
# The camera records in all shooting modes except PHOTO STORY, not during BULB / LIVE TIME / LIVECOMP,
# sequential shooting or time lapse (E-M1 manual, p.26-27).
OP_MOVIE_BUTTON = 0x948C

# Manual focus drive, PTP 0x9487 (Olympus OM-D MFDrive): direction 1 near / 2 far, step size as libgphoto2
# ("manualfocusdrive": Near/Far 1 = 0x03, 2 = 0x0e, 3 = 0x3c). Basis for the Star AF aid (REQ-F24).
OP_MF_DRIVE = 0x9487
MF_DIRECTION = {"near": 1, "far": 2}
MF_STEPS = {1: 0x03, 2: 0x0E, 3: 0x3C}

# d01c: special exposure time values, order as in the Wi-Fi list (still untested)
LONG_EXPOSURE = {"livecomp": "4294967290", "livetime": "4294967293", "livebulb": "4294967292"}
# This is how libgphoto2 names these values, partly translated
LONG_LABELS = {"Composite": "livecomp", "Time": "livetime", "Selbstauslöser": "livetime",
               "Bulb": "livebulb", "Langzeitbelichtung": "livebulb",
               # without a name libgphoto2 shows the raw value as a fraction (seen for Time, 2026-11-13)
               "65535/65530": "livecomp", "65535/65533": "livetime", "65535/65532": "livebulb"}

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
# Turning the mode dial sends event 0xC003 with param1 = 3 (E-M1 Mark I, tested 2026-11-12);
# the new value only arrives with a new session. d006 knows only M, P, A, S, Movie: iAUTO, ART, SCN
# and PHOTO STORY read as P
DIAL_EVENT = re.compile(r"c003, Param1 0*3\b", re.I)
DIAL_EVERY = 3.0  # seconds between event checks; each costs ~0.3 s of live view (measured 2026-11-12)
# seconds after a shutter command, written setting or live view start in which 0xC003/3 is not the dial.
# Two check intervals: the camera also sends it a little after a shot, and it is only read every DIAL_EVERY s
# (seen 3.1 s after a shot, 2026-11-13). A real dial turn in that time is missed; turn it again.
DIAL_QUIET = 2 * DIAL_EVERY
FOCUS_WAIT = 2.0
FOCUS_POSITION_WAIT = 1.5
SHOT_TIMEOUT = 20


def _gp():
    try:
        import gphoto2
    except ImportError:
        raise CameraError('USB needs the gphoto2 package: install it with .venv/bin/pip install ".[usb]" and start the app from .venv')
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


SHUTTER_VALUE = re.compile(r"\d+(/\d+)?")  # libgphoto2: "60", "1/250", "32/10" (3.2 s), "10/13" (1/1.3 s)


def _shutter_names(choices):
    """Camera style: 1/250 s -> "250", 1/1.3 s -> "1.3", 3.2 s -> '3.2"', 60 s -> '60"'."""
    names = {}
    for c in choices:
        n, _, d = c.partition("/")
        n, d = int(n), int(d or 1)
        if n >= d:
            names[c] = "%g\"" % (n / d)
        else:
            names[c] = str(d) if n == 1 else "%g" % (d / n)
    return names


def _iso_names(choices):
    """By value, not by position: libgphoto2 names AUTO and LOW "Auto" / "Low"."""
    return {c: {"auto": "AUTO", "low": "LOW"}.get(c.lower(), c) for c in choices}


def _ev_names(choices):
    return {c: ("%+.1f" % float(c) if float(c) else "0.0") for c in choices}


def _drive_names(choices):
    return {c: DRIVE_STYLE.get(int(c) >> 4, "") + DRIVE_KIND.get(int(c) & 15, c) for c in choices}


# d010 values in the order of PICTURE_NAMES; 33537 = Vivid and 2 = Natural are confirmed
PICTURE_VALUES = [33281, 33537, 2, 1, 32771, 32769, 33025, 33793, 34561, 34049] + list(range(34305, 34319))


def _picture_names(choices):
    table = dict(zip(map(str, PICTURE_VALUES), PICTURE_NAMES))
    return {c: table.get(str(c), c) for c in choices}


# Super Control Panel settings over USB, values mapped on the camera 2026-11-13 and written from the app
# (out/research/usb_value_mapping.md, usb_control_matrix.md); "inferred" values follow the pattern but were not seen
USB_TABLES = {
    "d003": {"2": "S-AF", "32770": "C-AF", "1": "MF", "32769": "S-AF+MF"},
    "d004": {"32769": "Digital ESP", "2": "Center weighted", "4": "Spot", "32785": "Spot HI",
             "32786": "Spot SH"},  # 32786 inferred
    "d005": {"1": "Flash Auto", "3": "Fill-in", "2": "Flash Off"},  # other flash modes not mapped yet
    "d00d": {"257": "LF", "258": "LN", "259": "MN", "260": "SN", "32": "RAW", "289": "LF+RAW",
             "290": "LN+RAW", "291": "MN+RAW", "292": "SN+RAW"},  # SN and LF/MN/SN+RAW inferred
    "d01d": {"0": "S-IS Off", "1": "S-IS1", "2": "S-IS2", "3": "S-IS3", "4": "S-IS AUTO"},
    "d01a": {"0": "Face Priority Off", "32769": "Face Priority On", "32770": "Face & Eye Priority On",
             "32771": "Face & R. Eye Priority On", "32772": "Face & L. Eye Priority On"},  # 32771 inferred
    "d0cb": {"1": "On", "2": "Off"},  # Focus Stacking (FW 4.x, mapped 2026-11-13; libgphoto2's d065 does not change)
}
# Bracketing kind d020: 2 = Off, 3 = Focus BKT (mapped 2026-11-13). Focus Stacking needs Focus BKT; the camera then
# switches by itself to Silent Sequential H, electronic shutter (1/16000 … 1/8 s) and flash off (E-M1 manual, p.174).
BKT_OFF, BKT_FOCUS = 2, 3
STACK_WAIT = 16.0  # 8 frames (16 files with JPG+ORF) in ~3.5 s, the merged JPG ~13.6 s after the release (2026-11-13)


def _table_names(code):
    return lambda choices: {c: USB_TABLES[code][c] for c in choices if c in USB_TABLES[code]}


def _aspect_names(choices):
    """d01b: width << 16 | height, e.g. 262147 = 4:3."""
    return {c: "%d:%d" % (int(c) >> 16, int(c) & 0xFFFF) for c in choices if int(c) >> 16 and int(c) & 0xFFFF}


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
        self.camera.last_press = time.monotonic()  # the camera also sends 0xC003/3 when live view starts
        self._run = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._run = False
        if self._thread:
            self._thread.join(3)
            self._thread = None

    def _loop(self):
        failures, next_dial = 0, 0.0
        while self._run:
            if self.camera.hold:  # shooting or card list: do not disturb the connection
                failures = 0
                time.sleep(0.05)
                continue
            if time.monotonic() >= next_dial:
                next_dial = time.monotonic() + DIAL_EVERY
                if self.camera.dial_turned() and self.camera.reopen_if_idle(
                        "mode dial turned, %s" % getattr(self.camera, "dial_reason", "?")):
                    self.camera.mode_changed_at = time.time()
                    continue
            data = self.camera.preview_frame()
            if data is None:
                failures += 1
                # not during an exposure or its noise reduction (last_press lies in the future then)
                if failures >= 10 and not self.camera.shooting and not self.camera.stage \
                        and time.monotonic() >= self.camera.last_press:
                    # session broken: rebuild; name the camera's last answer for the diagnosis
                    self.camera.reopen("live view failed 10x: %s" % getattr(self.camera, "lv_reason", None))
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
    shooting = False
    _take_t0 = None  # start of a running long exposure (BULB, LIVE TIME, LIVECOMP)
    last_press = 0.0  # time of the last shutter command or written setting (see __init__)

    # setting named as over Wi-Fi -> gphoto name, display names from the choice values
    PROPS = {
        "shutspeedvalue": ("shutterspeed", _shutter_names),
        "focalvalue": ("aperture", None),
        "expcomp": ("exposurecompensation", _ev_names),
        "isospeedvalue": ("iso", _iso_names),
        "wbvalue": ("whitebalance", lambda ch: dict(zip(ch, WB_NAMES)) if len(ch) == len(WB_NAMES) else {}),
        "drivemode": ("d009", _drive_names),
        "colortone": ("d010", _picture_names),
        "artfilter": ("d010", _picture_names),
        "focusmode": ("d003", _table_names("d003")),
        "metering": ("d004", _table_names("d004")),
        "flashmode": ("d005", _table_names("d005")),
        "recordmode": ("d00d", _table_names("d00d")),
        "aspect": ("d01b", _aspect_names),
        "stabilizer": ("d01d", _table_names("d01d")),
        "facepriority": ("d01a", _table_names("d01a")),
        "focusstacking": ("d0cb", _table_names("d0cb")),
    }
    OPTIONAL = {"focusstacking"}  # not on every body / firmware

    def __init__(self, allow_write=False, backend="gphoto2"):
        """backend: "ptp" (own PTP layer, omcap/ptp_gphoto.py), "gphoto2" (libgphoto2) or "auto"
        (own PTP layer, libgphoto2 if it cannot connect, e.g. on Linux)."""
        self.allow_write = allow_write
        self.stage = 0
        self._new_files = []
        self.last_jpg = None  # JPG last reported by the camera
        self.last_press = 0.0  # time of the last shutter command (AF also sends 0xC003)
        self.mode_changed_at = None  # set when the mode dial was turned (page reloads values)
        self._model = None    # model name, read once
        self._pending = []
        self._files = None
        self._event_log = []
        self.last_af = None
        self._lock = threading.Lock()
        self._hold, self._hold_lock = 0, threading.Lock()
        self.shooting = False  # short image dropouts are normal while shooting
        self._connect(backend)
        # libgphoto2 2.5.34 forces 1024x768 on every live image; newer versions (master 2.5.34.1,
        # 2026-11-12) keep a chosen size and offer the widget "liveviewsize" (REQ-F36)
        self.features = FEATURES + (["lvsize"] if self._has_widget("liveviewsize") else [])
        self.live = UsbLive(self)

    def _connect(self, backend):
        if backend not in ("ptp", "gphoto2", "auto"):
            raise CameraError("Unknown USB backend: %s" % backend)
        if backend in ("ptp", "auto"):
            from . import ptp_gphoto
            self.gp, self.backend = ptp_gphoto, "ptp"
            self._c = self.gp.Camera()
            try:
                self._open(tries=4 if backend == "ptp" else 1)  # auto: one try, then libgphoto2
                return
            except CameraError as e:
                if backend == "ptp":
                    raise
                print("USB: own PTP layer could not connect (%s), using libgphoto2" % e, flush=True)
        self.gp, self.backend = _gp(), "gphoto2"
        self._c = self.gp.Camera()
        self._open()

    def _open(self, tries=4):
        error = None
        for _ in range(tries):
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
        raise CameraError("USB camera not reachable (%s). Quit the Photos app and choose the computer + camera entry "
                          "in the camera's USB menu; after plugging the cable in again, restart E-M1 Capture." % error)

    def reopen(self, reason="?"):
        with self._lock:
            self._reopen_locked(reason)

    def reopen_if_idle(self, reason):
        """Rebuild the session unless a shot or card read started meanwhile (checked under the lock)."""
        with self._lock:
            if self.hold or self.stage:
                return False
            self._reopen_locked(reason)
            return True

    def _reopen_locked(self, reason):
        # logged: a rebuilt session drops live view for ~9 s and loses libgphoto2's file index
        print("USB session reopened (%s)" % reason, flush=True)
        try:
            self._c.exit()
        except self.gp.GPhoto2Error:
            pass
        self._c = self.gp.Camera()
        try:
            self._open()
            self._apply_lv_size_locked()  # keep the chosen size after a rebuilt session
            self._resync_files_locked()
        except (CameraError, self.gp.GPhoto2Error):
            pass

    def _resync_files_locked(self):
        """After a rebuilt session: files whose "added" event was lost go to the card list (PTP backend)."""
        if getattr(self, "_files", None) is None or not hasattr(self._c, "file_paths"):
            return
        for path in self._c.file_paths():
            if path not in self._files and path not in self._pending:
                self._pending.append(path)
                if path.lower().endswith((".jpg", ".jpeg")):
                    self.last_jpg = path

    @property
    def hold(self):
        """> 0 while a shot, card list or file read pauses the live view."""
        return self._hold

    def _hold_add(self, n):
        # several request threads pause the live view at once; a lost update would pause it for good
        with self._hold_lock:
            self._hold += n

    def dial_turned(self):
        """Read pending events without waiting; True if the mode dial was turned.

        Files shot on the camera body go to the card list only, not to the app's next shot."""
        if self.hold or self.stage or self.shooting:  # a long exposure also sends 0xC003
            return False
        turned = False
        with self._lock:
            for _ in range(8):
                try:
                    kind, data = self._c.wait_for_event(1)
                except self.gp.GPhoto2Error:
                    return False
                if kind == self.gp.GP_EVENT_TIMEOUT:
                    break
                self._on_event(kind, data, shot=False)
                if kind == self.gp.GP_EVENT_UNKNOWN and DIAL_EVENT.search(str(data)):
                    turned = True
        since = time.monotonic() - self.last_press
        # named in the rebuild message: tells a real dial turn from an event after AF or a setting
        self.dial_reason = "%.1f s after the last command" % since
        return turned and since > DIAL_QUIET

    def refresh(self):
        """Mode dial and other camera changes only arrive with a new session."""
        self._hold_add(1)
        try:
            self.reopen()
        finally:
            self._hold_add(-1)

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

    def read_props(self, codes):
        """Research: value and choices of single properties ("d003"), one by one.

        Never reads the whole group "other" (empty values crash libgphoto2)."""
        out = {}
        for code in codes:
            if not re.fullmatch(r"d[0-9a-f]{3}", code):
                continue
            def read(c=code):
                w = self._c.get_single_config(c)
                choices = [w.get_choice(i) for i in range(w.count_choices())] \
                    if w.get_type() in (self.gp.GP_WIDGET_MENU, self.gp.GP_WIDGET_RADIO) else None
                return {"value": w.get_value(), "choices": choices}
            try:
                out[code] = self._call(read)
            except CameraError as e:
                out[code] = {"error": str(e)}
        return out

    def _within_lens_limits(self, choices):
        """d07f / d080: smallest and largest f-number x10 of the lens (E-M1: 35 / 220 with a 14-140)."""
        try:
            lo, hi = (int(float(self._value(c))) / 10 for c in ("d07f", "d080"))
        except (CameraError, ValueError):
            return choices
        if not (lo and hi):
            return choices
        return [c for c in choices if not re.fullmatch(r"[\d.]+", c) or lo - 0.05 <= float(c) <= hi + 0.05]

    def _has_widget(self, name):
        try:
            self._call(lambda: self._c.get_single_config(name))
            return True
        except CameraError:
            return False

    def _apply_lv_size_locked(self, lvqty=None):
        """Set a live view size ("1280x0960"; default: the chosen one); caller holds the lock.

        A new session starts at 0, which libgphoto2 turns into 1024x768."""
        lvqty = lvqty or self.lvqty
        if not lvqty or "lvsize" not in self.features:
            return
        w, h = (int(v) for v in lvqty.split("x"))
        widget = self._c.get_single_config("liveviewsize")
        label = "%dx%d" % (w, h)
        if label not in [widget.get_choice(i) for i in range(widget.count_choices())]:
            raise CameraError("Live view size not offered by the camera: %s" % label)
        widget.set_value(label)
        self._c.set_single_config("liveviewsize", widget)

    def _set(self, name, value):
        self._need_write()

        def apply():
            w = self._c.get_single_config(name)
            w.set_value(str(value))
            self._c.set_single_config(name, w)
        self._call(apply)
        # a written setting (e.g. the tapped AF field) may also send 0xC003/3; keep a later end (exposure)
        self.last_press = max(self.last_press, time.monotonic())

    # --- Read ---------------------------------------------------------------
    def caminfo(self):
        # kept: the page asks on every load, and the camera is busy while the card index is read
        if not self._model:
            self._model = self._value("cameramodel")
        return self._model

    def commandlist(self):
        return []

    def props(self):
        out = {"takemode": {"value": EXPOSURE_PROGRAM.get(str(self._value("d006")), "?"),
                            "writable": False, "enum": []}}
        for key, (name, namer) in self.PROPS.items():
            def read():
                w = self._c.get_single_config(name)
                return w.get_value(), list(w.get_choices()), not w.get_readonly()
            try:
                value, choices, writable = self._call(read)
            except CameraError:
                if key in self.OPTIONAL:
                    continue  # e.g. firmware without Focus Stacking: hide the setting, keep the panel
                raise
            if key == "artfilter":  # d010 also holds the kind of filter (from 34305)
                choices = [c for c in choices if int(c) >= 34305]
            if key == "shutspeedvalue":  # M only: BULB, LIVE TIME, LIVECOMP are in d01c
                choices = [c for c in choices if SHUTTER_VALUE.fullmatch(c) and c not in LONG_LABELS]
                specials = list(LONG_EXPOSURE)
                value = LONG_LABELS.get(value, value)
                choices = specials + choices
            if name in USB_TABLES:  # offer only mapped values
                choices = [c for c in choices if c in USB_TABLES[name]]
            if key == "focalvalue":  # the lens limits (current at session setup, at the current focal length)
                choices = self._within_lens_limits(choices)
            out[key] = {"value": value, "writable": writable, "enum": choices,
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
                ok = data[:2] == b"\xff\xd8" and b"\xff\xd9" in data[-64:]
                self.lv_reason = None if ok else "incomplete JPEG (%d bytes)" % len(data)
                return data if ok else None
            except self.gp.GPhoto2Error as e:
                self.lv_reason = str(e)  # shown when the session is rebuilt
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
        self._hold_add(1)  # live view paused, otherwise the read aborts
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
            self._hold_add(-1)

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
        if self.backend == "gphoto2":
            time.sleep(0.002)  # do not starve live view and commands (libgphoto2 reads each file here)
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
            self._hold_add(1)  # live view paused, otherwise the list aborts
            try:
                while stack:
                    folder = stack.pop()
                    for sub in self._list(self._c.folder_list_folders, folder):
                        stack.append(folder.rstrip("/") + "/" + sub)
                    for name in self._list(self._c.folder_list_files, folder):
                        e = self._entry(folder, name)
                        files[e["path"]] = e
            finally:
                self._hold_add(-1)
            self._files = files
        pending, self._pending = self._pending, []
        for path in pending:
            folder, name = path.rsplit("/", 1)
            self._files[path] = self._entry(folder, name)
        return list(self._files.values())

    # --- Write -----------------------------------------------------------
    def set_mode(self, mode, lvqty=None):
        """There are no modes over USB as with Wi-Fi; only the live view size can be chosen,
        and only with a libgphoto2 that keeps it (feature "lvsize", otherwise fixed 1024x768)."""
        if lvqty and "lvsize" in self.features:
            self._need_write()
            if not re.fullmatch(r"\d{4}x\d{4}", lvqty):
                raise CameraError("Unknown live view size: %s" % lvqty)
            self._call(self._apply_lv_size_locked, lvqty)
            self.lvqty = lvqty  # only once the camera took it

    def start_liveview(self, port):
        self._need_write()

    def stop_liveview(self):
        pass

    def set_prop(self, prop, value):
        if prop not in self.PROPS:
            raise CameraError("Not available over USB: %s" % prop)
        if prop == "focusstacking":
            self._set_focus_stacking(str(value) == "1")
        elif prop == "shutspeedvalue" and value in LONG_EXPOSURE:
            self._set("d01c", LONG_EXPOSURE[value])
        else:
            self._set(self.PROPS[prop][0], value)

    def _set_focus_stacking(self, on):
        """Focus Stacking on or off; also sets the bracketing kind (Focus BKT) and keeps the earlier one."""
        self._need_write()
        if on:
            if LONG_LABELS.get(self._value("shutterspeed")):  # the camera stacks with the electronic shutter only
                raise CameraError("Focus Stacking: choose a normal shutter speed first (not BULB, LIVE TIME, LIVECOMP)")
            kind = int(float(self._value("d020")))
            if kind != BKT_FOCUS:
                self._bkt_before = kind  # lost after a reconnect: Off then sets Bracketing Off
            self._set("d020", BKT_FOCUS)
            try:
                self._set("d0cb", 1)
            except CameraError:
                self._set("d020", getattr(self, "_bkt_before", BKT_OFF))  # e.g. a lens without Focus BKT (p.173)
                raise
        else:
            self._set("d0cb", 2)
            if int(float(self._value("d020"))) == BKT_FOCUS:  # leave another bracketing kind alone
                self._set("d020", getattr(self, "_bkt_before", BKT_OFF))
        self.refresh()  # drive mode, shutter limits and flash change with it; they arrive with a new session

    def _stacking_on(self):
        try:
            return str(self._value("d0cb")) == "1"
        except CameraError:
            return False

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
        self.shooting = True  # no live view images during the exposure: never rebuild the session meanwhile
        self._take_t0 = time.monotonic()
        try:
            if self._is_bulb():
                self._shutter(OP_FULL)
            else:
                self._pulse()
        except Exception:
            self.shooting, self._take_t0 = False, None
            raise

    def take_stop(self):
        try:
            if self._is_bulb():
                self._shutter(OP_RELEASE)
            else:
                self._pulse()
            self._events(2.0)
        finally:
            self.shooting = False
            # noise reduction after a long exposure takes about as long as the exposure and ends with
            # 0xC003/3 like the mode dial: keep the dial check and session rebuilds quiet for that time
            # (seen 2026-11-13). A Stop without a running exposure (e.g. to end a stuck LIVECOMP) only presses.
            if self._take_t0 is not None:
                now = time.monotonic()
                self.last_press = now + (now - self._take_t0)
            self._take_t0 = None

    def _shutter(self, step):
        self._need_write()
        self.last_press = time.monotonic()
        self._opcode(0x9481, step)

    def _opcode(self, code, *params):
        """Run a PTP operation without data through the "opcode" widget (both backends)."""
        def send():
            w = self._c.get_single_config("opcode")
            w.set_value(",".join("0x%x" % v for v in (code,) + params))
            self._c.set_single_config("opcode", w)
        self._call(send)

    def _movie_button(self):
        self._need_write()
        self.last_press = time.monotonic()
        try:
            self._opcode(OP_MOVIE_BUTTON, 1)
        finally:
            self._opcode(OP_MOVIE_BUTTON, 0)  # always let go, or the camera may keep the button pressed

    def movie_start(self):
        """Start recording like the movie button; the session is not rebuilt while recording."""
        self.shooting = True
        try:
            self._movie_button()
        except Exception:
            self.shooting = False
            raise

    def movie_stop(self):
        """Stop recording; the new movie file goes to the card list when the camera reports it."""
        try:
            self._movie_button()
            self._events(3.0, "quiet")
        finally:
            self.shooting = False
            self.last_press = time.monotonic() + 5  # writing the file ends with events like the mode dial
        self._new_files = []  # the movie is no "new shot" of the shutter: card list only

    def mf_drive(self, direction, step):
        """Move the focus like turning the focus ring (MF, S-AF+MF): direction "near"/"far", step 1-3."""
        self._need_write()
        if direction not in MF_DIRECTION or step not in MF_STEPS:
            raise CameraError("Focus drive: direction near or far, step 1 to 3")
        self._opcode(OP_MF_DRIVE, MF_DIRECTION[direction], MF_STEPS[step])

    def _on_event(self, kind, data, shot=True):
        """Keep new files (card list; with `shot` also the app's current shot) and log unknown events."""
        if kind == self.gp.GP_EVENT_FILE_ADDED:
            path = "%s/%s" % (data.folder, data.name)
            if shot:
                self._new_files.append(path)
            if data.name.lower().endswith((".jpg", ".jpeg")):
                self.last_jpg = path  # for lens data
            self._pending.append(path)
        elif kind == self.gp.GP_EVENT_UNKNOWN:
            self._event_log.append(str(data))

    def _events(self, seconds, stop=None):
        """Collect events without blocking the camera in between."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            kind, data = self._call(self._c.wait_for_event, 150)
            self._on_event(kind, data)
            if kind == self.gp.GP_EVENT_UNKNOWN and stop and stop in str(data).lower():
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
        self._hold_add(1)
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
            # no extra event wait here: each idle libgphoto2 event check costs ~0.3 s (150 ms timeout
            # plus one retry); the next check (dial watch or next focus) collects what is left
        finally:
            self._hold_add(-1)
        return self.focus_ok

    def shoot(self):
        """Release once. Returns the new file paths (JPG and ORF)."""
        self._new_files = []
        self.shooting = True  # the live view keeps running even if the camera does not release
        t0 = time.monotonic()
        marks = []
        # Stop the live view before shooting: a preview request running during
        # saving blocks the USB connection for up to a minute (measured 2026-11-09).
        self._hold_add(1)
        try:
            with self._lock:  # let a running preview request finish
                pass
            marks.append(("paused", time.monotonic() - t0))
            stacking = self._stacking_on()  # read before the release: the camera is busy afterwards
            self._shutter(OP_FULL)
            self._shutter(OP_RELEASE)
            marks.append(("released", time.monotonic() - t0))
            self._events(SHOT_TIMEOUT, "quiet")
            if stacking:  # 8 frames (16 files) come first, the merged picture last
                self._events(max(0.0, STACK_WAIT - (time.monotonic() - t0)))
            marks.append(("files", time.monotonic() - t0))
            if self._new_files:
                self._events(1.5)  # the second format (ORF or JPG) follows shortly after
        finally:
            self._hold_add(-1)
            self.shooting = False
            marks.append(("done", time.monotonic() - t0))
            print("USB shot: " + ", ".join("%s %.1f s" % m for m in marks), flush=True)
        new = self.take_new_files()
        if not new:
            raise CameraError("Camera did not release, probably no focus found")
        return new
