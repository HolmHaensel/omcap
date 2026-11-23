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
from .ptp import (LOUPE_X_GAIN, LOUPE_MOVES, LOUPE_OFF, LOUPE_ON, LOUPE_RATIOS, OP_LOUPE_MOVE, OP_LOUPE_POINT,
                  loupe_grid, loupe_point)


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
            "playback", "transfer", "long", "mf_drive", "movie", "erase", "loupe", "star_af"]

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
# 5 releases the half press without a shot (OM Capture trace, Zoom AF); used when only focusing while zoomed
OP_RELEASE_NOSHOT = 5
# Turning the mode dial sends event 0xC003 with param1 = 3 (E-M1 Mark I, tested 2026-11-12);
# the new value only arrives with a new session. d006 knows only M, P, A, S, Movie: iAUTO, ART, SCN
# and PHOTO STORY read as P
DIAL_EVENT = re.compile(r"c003, Param1 0*3\b", re.I)
# AF result of a half press, mapped on the camera 2026-11-13: Param1 1 = in focus, Param2 = focus position
# (x << 16 | y in the 1280×960 grid), Param3 = frame size (99×67); Param1 2 = no focus (Param2/3 = 0).
# 0xC003/3 also follows a written setting or a shot. Counting any c003 reported "in focus" also when AF failed.
FOCUS_EVENT = re.compile(r"c003, Param1 0*([12])\b(?:, Param2 ([0-9a-f]{8}))?", re.I)


AF_SINGLE = 2  # d003 value of S-AF


# The 9x9 AF grid as fractions of the picture (x0, x1, y0, y1), read on the camera 2026-11-22 (single target,
# fields 1/41/81 from the AF event; matches the camera monitor, user): wider than the Wi-Fi touch frame (~60 %).
AF_GRID = (0.046, 0.955, 0.107, 0.894)
# The AF event 0xC003 gives positions in a ~920x696 space (field 41 = 460/348), not 1280x960 like d05d/d05e
# (measured once, live view 1024x768 or 1280x960; other live view sizes unchecked)
AF_EVENT_SPACE = (920, 696)


def parse_af_result(text):
    """(in focus, position or None) from a c003 AF event text, None if it is no AF result.
    The position is returned in the 1280x960 grid of d05d/d05e."""
    m = FOCUS_EVENT.search(text or "")
    if not m:
        return None
    pos = int(m.group(2), 16) if m.group(2) else 0
    ok = m.group(1) == "1"
    if not (ok and pos):
        return ok, None
    return ok, {"x": round((pos >> 16) * 1280 / AF_EVENT_SPACE[0]), "y": round((pos & 0xFFFF) * 960 / AF_EVENT_SPACE[1])}
DIAL_EVERY = 3.0  # seconds between event checks; each costs ~0.3 s of live view (measured 2026-11-12)
# seconds after a shutter command, written setting or live view start in which 0xC003/3 is not the dial.
# Two check intervals: the camera also sends it a little after a shot, and it is only read every DIAL_EVERY s
# (seen 3.1 s after a shot, 2026-11-13). A real dial turn in that time is missed; turn it again.
DIAL_QUIET = 2 * DIAL_EVERY
FOCUS_WAIT = 2.0
FOCUS_POSITION_WAIT = 1.5
SHOT_TIMEOUT = 20
# Direct store (no card): after a shot the camera sends 0xC004 (DirectStoreImage) and property d0de changes;
# then the picture is read with PTP 0x9495/0x9493 (REQ-F61). Events as the own PTP layer words them.
DIRECT_EVENT = re.compile(r"PTP Event c004\b|PTP Property d0de changed", re.I)
DIRECT_GRACE = 0.5  # after the event: a card file may still be announced (then the card path stays the truth)
DIRECT_NEXT_WAIT = 1.0  # seconds without a new event after a non-JPG file (ORF): no JPG follows; after a JPG we stop at once


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
    "d0cb": {"1": "On", "2": "Off"},  # Focus BKT (user's firmware: d0ce is Focus Stacking, mapped 2026-11-16)
    "d0ea": {"2": "Off", "1": "On1", "3": "On2"},  # Live View Boost (E-M1 manual p.176; traces B & C, 2026-11-16/22)
}
# Bracketing kind d020: 2 = Off, 3 = Focus BKT (mapped 2026-11-13). Focus Stacking needs Focus BKT; the camera then
# switches by itself to Silent Sequential H, electronic shutter (1/16000 … 1/8 s) and flash off (E-M1 manual, p.174).
BKT_OFF, BKT_FOCUS = 2, 3
BKT_MAIN = "d0a6"  # Bracketing On (1) / Off (2), the main switch of Shooting Menu 2 (found 2026-11-22 by diff)
LV_BOOST = "d0ea"  # Live View Boost: 1 = On1, 2 = Off, 3 = On2 (confirmed in OM Capture traces B & C, 2026-11-16/22)
STACK_FRAMES_WAIT = 6.0  # the 8 frames are on the card ~3.5 s after the release; then decide whether to wait on
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


def _no_card_error(e):
    """Without a card the camera still lists a slot but refuses it: 0x2008 InvalidStorageID or 0x2013
    StoreNotAvailable (no-card test 2026-11-21). A card just put in also answers 0x2013 for 1-2 s."""
    return any(c in str(e) for c in ("0x2008", "0x2013"))


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
        self.stamp = (0, 0)  # (zoom revision, zoom on) of the camera when `frame` was fetched (REQ-F54)
        self.seq = 0
        self.last_frame = None
        self.cond = threading.Condition()
        self._run = False
        self._thread = None
        self._backoff = 0.0      # seconds to wait after a failed rebuild (5, 10, ... 60)
        self._retry_at = 0.0     # monotonic time of the next rebuild attempt
        self._back_since = None  # when the missing camera showed up on USB again

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
            # read before the fetch: a write in between only makes the stamp older, never newer than the frame
            stamp = (getattr(self.camera, "loupe_rev", 0), int(getattr(self.camera, "loupe_on", False)))
            data = self.camera.preview_frame()
            if data is None:
                failures += 1
                # not during an exposure or its noise reduction (last_press lies in the future then)
                if failures >= 10 and not self.camera.shooting and not self.camera.stage \
                        and time.monotonic() >= self.camera.last_press:
                    if self._rebuild():
                        failures = 0
                time.sleep(0.3)
                continue
            failures, self._backoff, self.camera.gone = 0, 0.0, False
            with self.cond:
                self.frame, self.stamp = data, stamp
                self.seq += 1
                self.last_frame = time.monotonic()
                self.cond.notify_all()
            time.sleep(0.005)  # leave other commands to the camera

    def _rebuild(self):
        """Live view keeps failing: rebuild the session, but not in a loop (seen 2026-11-15).

        Camera gone from USB (cable pulled, switched off): no rebuild - each one stops the macOS camera service and
        claims the bus, which blocked other apps - but a quiet check every 2 s without claiming the camera, and a
        rebuild once it is back. Camera there but the rebuild fails: wait 5, 10, 20 ... 60 s before the next try.
        Returns True when a rebuild was tried (the failure count starts again)."""
        if detect_name() is None:
            if not self.camera.gone:
                print("USB: camera gone, waiting for it (cable, power, USB menu)", flush=True)
                # give up the dead session now, while the camera is away: a handle still open on the vanished
                # device made libusb crash when the camera came back (segmentation fault, camera test 2026-11-15)
                self.camera.release()
            self.camera.gone, self._back_since = True, None
            time.sleep(1.7)  # with the 0.3 s of the loop: one check every 2 s
            return False
        if self.camera.gone:
            # back on USB: the camera shows its USB menu first and appears and vanishes while the entry is chosen
            # (camera test 2026-11-15), so it has to stay for 3 s before the rebuild
            if self._back_since is None:
                self._back_since = time.monotonic()
            if time.monotonic() - self._back_since < 3.0:
                time.sleep(0.7)
                return False
        if time.monotonic() < self._retry_at:
            return False
        # session broken: rebuild; name the camera's last answer for the diagnosis
        ok = self.camera.reopen("live view failed 10x: %s" % getattr(self.camera, "lv_reason", None))
        self._back_since = None  # reopen() clears camera.gone when the camera answers
        self._backoff = 0.0 if ok else min(60.0, max(5.0, self._backoff * 2))
        self._retry_at = time.monotonic() + self._backoff
        return True

    def wait_frame(self, last_seq, timeout=3.0):
        """(seq, frame, stamp): stamp = (zoom revision, zoom on) of the camera when that frame was fetched."""
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq, timeout)
            return self.seq, self.frame, self.stamp


class UsbCamera:
    usb = True
    host = "USB"
    stage = 0
    card = None  # cached card flag for the page (True / False / None unknown), see refresh_card
    _card_read = False  # _pre_release just read the card: the next refresh_card reuses it
    _card_due = False  # a rebuilt session must read the card again (_settle_card, outside the lock)
    gone = False  # set by the live view loop while the camera is missing from USB
    lvqty = None
    features = FEATURES
    shooting = False
    _take_t0 = None  # start of a running long exposure (BULB, LIVE TIME, LIVECOMP)
    _last_level = None  # last level gauge reading, returned while a shot, movie or card read holds the camera
    last_press = 0.0  # time of the last shutter command or written setting (see __init__)
    saf_shot = False  # S-AF during the running shot: no focus means no release
    _fast_note = ""  # what the last fast picture attempt did (shown in the shot log line)
    on_direct_file = None  # (class default: objects built without __init__)
    _direct_hit = _direct_wait = False  # 0xC004 seen / waiting for it (direct store, REQ-F61)
    _fast_empty = 0  # empty 0x9485 answers in a row (RAW only, no card): then only a short probe
    loupe_on = False  # Zoom AF (camera magnification) switched on by the app
    loupe_ratio = 5  # magnification last sent (x)
    loupe_x = loupe_y = None  # wanted zoom centre as last requested (picture fractions, before the x gain)
    loupe_owner = None  # client id of the page that sent the last zoom request; None when the server ended the zoom
    loupe_rev = 0  # counts every change of the camera's zoom state; live frames carry it (REQ-F54)

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
        "lvboost": ("d0ea", _table_names("d0ea")),
    }
    OPTIONAL = {"focusstacking", "lvboost"}  # not on every body / firmware

    def __init__(self, allow_write=False, backend="gphoto2"):
        """backend: "ptp" (own PTP layer, omcap/ptp_gphoto.py), "gphoto2" (libgphoto2) or "auto"
        (own PTP layer, libgphoto2 if it cannot connect, e.g. on Linux)."""
        self.allow_write = allow_write
        self.stage = 0
        self._new_files = []
        self.on_direct_file = None  # server callback(ext, size, pieces, late=False) -> saved path (REQ-F61)
        self.direct_paths = []  # paths saved for the shot just taken
        self.on_fast_jpeg = None  # server callback(bytes): JPEG of a shot before the card lists it (REQ-F60)
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
        if hasattr(self._c, "get_prop_value"):  # PTP backend: live tilt (REQ-F23)
            self.features = self.features + ["level"]
        self.live = UsbLive(self)
        self.card = self._card_state_settled()

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
                          "in the camera's USB menu; after plugging the cable in again, wait a few seconds or restart E-M1 Capture." % error)

    def release(self):
        """Close the session of a camera that is gone from USB; reopen() starts a fresh one later."""
        with self._lock:
            try:
                self._c.exit()
            except Exception:  # noqa: BLE001 - the device is gone, every call may fail
                pass
            self._c = self.gp.Camera()

    def reopen(self, reason="?"):
        """Rebuild the session; True if the camera answered again."""
        with self._lock:
            ok = self._reopen_locked(reason)
        self._settle_card()
        return ok

    def reopen_if_idle(self, reason):
        """Rebuild the session unless a shot or card read started meanwhile (checked under the lock)."""
        with self._lock:
            if self.hold or self.stage:
                return False
            self._reopen_locked(reason)
        self._settle_card()
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
            self._loupe_off_locked()  # a magnified view outlives the session; the page shows it off
            self._apply_lv_size_locked()  # keep the chosen size after a rebuilt session
            self._resync_files_locked()
            self._card_due = True  # a card may have been put in or taken out: read after the lock (_settle_card)
            self.gone = False  # also after reload (refresh) or a rebuild without live view
            return True
        except (CameraError, self.gp.GPhoto2Error):
            return False

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
        if self.hold or self.stage or self.shooting or self.gone:  # a long exposure also sends 0xC003
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
        self._loupe_off()
        with self._lock:
            try:
                self._c.exit()
            except self.gp.GPhoto2Error:
                pass

    def _call(self, fn, *args):
        # while the camera is gone from USB, libgphoto2 would open the fresh camera object by itself on any call
        # (without the 3 s wait or stopping ptpcamerad), so nothing touches it until the live view loop reopens it
        if self.gone:
            raise CameraError("USB: camera not found")
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
            if key == "focusstacking":  # On only when the camera really stacks: Bracketing, Focus BKT and d0ce (live)
                value = "1" if self._stacking_on() else "2"
            if key == "lvboost":  # live value so menu or Star AF boost changes reflect immediately
                value = self._prop_now(LV_BOOST)
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
        """Free card space; also keeps the card flag current: right after a connect the camera can answer
        0x2013 for a moment although a card is in (USB test 2026-11-22), and that must not stick."""
        try:
            kb = free_kbytes(self._call(self._c.get_storageinfo))
        except Exception as e:
            if _no_card_error(e):
                self.card = False
            raise
        self.card = kb is not None
        return kb * 1024 if kb is not None else None

    def battery(self):
        # read only this one value, get_value() on the whole "other" group crashes libgphoto2
        try:
            return parse_battery(self._value("batterylevel"))
        except CameraError:
            return None

    def level(self):
        """Horizon (a, d053) and tilt (b, d055) in degrees, as the camera's Level gauge (manual p.37).

        The descriptor of d053/d055 keeps the session-start value; GetDevicePropValue follows the camera
        live under PC control (camera-tested 2026-11-14). Only the PTP backend can read it, so the
        Level Gauge is shown with that backend only (feature "level"). While a shot or card read holds
        the connection the last values (or None) are returned, so the gauge stands still meanwhile."""
        if not hasattr(self._c, "get_prop_value"):
            raise CameraError("Level gauge needs the own PTP backend (--usb-backend ptp or auto)")
        if self.hold or self.shooting:
            return self._last_level
        def tenths(v):  # the E-M1 reports d053/d055 as unsigned 16 bit: 65532 = -0.4 degrees
            return (v - 65536 if v > 32767 else v) / 10
        a, b = (tenths(self._call(self._c.get_prop_value, code)) for code in (0xD053, 0xD055))
        self._last_level = {"a": a, "b": b}  # no mode: d006 only changes with a new session (mode dial events)
        return self._last_level

    def _live_int(self, name):
        """Own PTP backend: GetDevicePropValue follows the camera live, the descriptor (_value) keeps a stale
        value inside a session (see level()). gphoto2 backend: the descriptor is all there is."""
        if hasattr(self._c, "get_prop_value"):
            return int(self._call(self._c.get_prop_value, int(name, 16)))
        return int(self._value(name))

    # The AF area of the E-M1 is fixed: AF_GRID (read on the camera 2026-11-22), centred in 1280x960.
    # d05a/d05b/d071/d072 are NOT this area: they are the Zoom AF frame-centre limits for the current
    # zoom ratio d0cf, [0.1+0.5/r, 0.9-0.5/r] of the picture (measured 2026-11-18).
    AF_AREA = {"x0": 59, "x1": 1221, "y0": 103, "y1": 857, "w": 1280, "h": 960}

    def af_area(self):
        area = dict(self.AF_AREA)  # centred, so its grid is (x0+x1) x (y0+y1) as with Wi-Fi
        area["w"], area["h"] = af_raster(area)
        self.af_mode = self._live_int("d00c")
        return {"mode": self.af_mode, "field": self._live_int("d051"), "area": area,
                "last_af": focus_in_raster(self.last_af, area), "focus_ok": getattr(self, "focus_ok", None)}

    def preview_frame(self):
        if self.gone:  # camera gone from USB: only the live view loop may open it again (REQ-Q11)
            return None
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

    def erase(self, paths):
        """Delete files from the card (PTP DeleteObject). One failing file (e.g. protected picture) does not stop
        the others. Returns {"erased": [...], "failed": [...]}."""
        self._need_write()
        paths = list(dict.fromkeys(paths))  # each file once
        for p in paths:
            _check_usb_path(p)
            if not re.search(r"/[^/]+\.[A-Za-z0-9]{3,4}$", p):  # a file, never a folder
                raise CameraError("Invalid path: %r" % p)
        erased, failed = [], []
        self._hold_add(1)  # live view paused, as for every card access
        try:
            for p in paths:
                folder, name = p.rsplit("/", 1)
                try:
                    self._call(self._c.file_delete, folder, name)
                except CameraError as e:
                    print("USB erase failed: %s (%s)" % (p, e), flush=True)
                    failed.append(p)
                    continue
                erased.append(p)
                print("USB erased: %s" % p, flush=True)  # every delete is in the log, so it can be traced later
                if getattr(self, "_files", None) is not None:
                    self._files.pop(p, None)
                if p in self._pending:
                    self._pending.remove(p)
                if self.last_jpg == p:
                    self.last_jpg = None
        finally:
            self._hold_add(-1)
        return {"erased": erased, "failed": failed}

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
        self._loupe_off()  # a magnified view can be left over from an earlier session (OM Capture, crash)
        self.refresh_card()  # the card may have changed since the connect

    def stop_liveview(self):
        self._loupe_off()

    # --- Zoom AF (the camera's magnified live view, E-M1 manual p.56; protocol in omcap/ptp.py) ---
    def loupe(self, on, ratio=None, x=None, y=None):
        """Zoom AF on or off. ratio: 3, 5, 7, 10 or 14 (x); x, y: centre of the zoom frame as a fraction
        of the live picture (0-1), sent before switching on. Order as OM Capture: d0cf, 0x9483, d04b; with the zoom already
        on and a new centre or ratio: d04b=2 first, so the camera never re-scales the old crop to the new ratio (it did when d0cf
        came first: old crop, re-scaled old crop, normal frames, new crop; camera test 2026-11-18)."""
        self._need_write()
        value = None
        if ratio is not None:
            value = next((k for k, v in LOUPE_RATIOS.items() if v == int(ratio)), None)
            if value is None:
                raise CameraError("Zoom ratio: one of %s" % ", ".join("%dx" % v for v in LOUPE_RATIOS.values()))
        point = on and x is not None and y is not None
        if point:
            fx, fy = float(x), float(y)
            if not (0 <= fx <= 1 and 0 <= fy <= 1):
                raise CameraError("Zoom frame: x and y between 0 and 1")
        # a new centre (0x9483 only takes effect while d04b goes to 1, camera test 2026-11-16) or a new ratio while the zoom
        # is on: off first
        if self.loupe_on and on and (point or value is not None):
            self._set("d04b", LOUPE_OFF)
            self.loupe_on = False  # frames in between are normal, and a failing 0x9483 leaves a true state
            self.loupe_rev += 1
        if value is not None:
            self._set("d0cf", value)
            self.loupe_ratio = int(ratio)
        if point:
            self.loupe_x, self.loupe_y = fx, fy
            fx = 0.5 + (fx - 0.5) / LOUPE_X_GAIN  # the camera overshoots x: send less so the crop lands where asked
            gw, gh = loupe_grid(self.lvqty)  # the camera reads the point in the grid of the live view size
            self._opcode(OP_LOUPE_POINT, loupe_point(fx * gw, fy * gh, (gw, gh)))
        self._set("d04b", LOUPE_ON if on else LOUPE_OFF)
        self.loupe_on = bool(on)
        self.loupe_rev += 1

    def loupe_move(self, direction):
        """Move the zoom frame one step: up, down, left or right."""
        self._need_write()
        if direction not in LOUPE_MOVES:
            raise CameraError("Zoom frame: direction up, down, left or right")
        self._opcode(OP_LOUPE_MOVE, LOUPE_MOVES[direction])

    def _loupe_off_locked(self):
        """d04b = 2 without raising; caller holds the lock. Only with the write permission."""
        self.loupe_on = False
        self.loupe_x = self.loupe_y = self.loupe_owner = None  # ended by the server: nobody owns the zoom
        self.loupe_rev += 1
        if not self.allow_write:
            return
        try:
            w = self._c.get_single_config("d04b")
            w.set_value(str(LOUPE_OFF))
            self._c.set_single_config("d04b", w)
        except self.gp.GPhoto2Error:
            pass  # body without d04b, or the camera is gone: nothing left to end

    def _loupe_off(self):
        if self.gone:
            self.loupe_on = False
            self.loupe_x = self.loupe_y = self.loupe_owner = None
            self.loupe_rev += 1
            return
        with self._lock:
            self._loupe_off_locked()

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
        """Focus Stacking on or off: bracketing kind d020 = Focus BKT, Focus BKT d0cb and the stacking flag d0ce;
        the earlier bracketing kind is kept and comes back on Off."""
        self._need_write()
        if on:
            if LONG_LABELS.get(self._value("shutterspeed")):  # the camera stacks with the electronic shutter only
                raise CameraError("Focus Stacking: choose a normal shutter speed first (not BULB, LIVE TIME, LIVECOMP)")
            kind = int(float(self._value("d020")))
            if kind != BKT_FOCUS:  # first switch-on: remember what to restore (lost after a reconnect: Off then)
                self._bkt_before = kind
                self._bkt_main_before = None
            try:
                before = self._set_bkt_main(1)  # Bracketing On: else the camera takes one picture (2026-11-22)
                if kind != BKT_FOCUS:
                    self._bkt_main_before = before
                self._set("d020", BKT_FOCUS)
                self._set("d0cb", 1)  # Focus BKT on
                try:
                    self._set_stack_flag(1)  # d0ce: merge the series in the camera (Focus Stacking)
                except CameraError:
                    self._set("d0cb", 2)  # not a plain series left behind
                    raise
            except CameraError:
                self._set("d020", getattr(self, "_bkt_before", BKT_OFF))  # e.g. a lens without Focus BKT (p.173)
                self._set_bkt_main(getattr(self, "_bkt_main_before", None) or 2)
                raise
        else:
            self._set_stack_flag(2)
            self._set("d0cb", 2)
            if int(float(self._value("d020"))) == BKT_FOCUS:  # leave another bracketing kind alone
                self._set("d020", getattr(self, "_bkt_before", BKT_OFF))
                self._set_bkt_main(getattr(self, "_bkt_main_before", None) or 2)  # as it was (default Off)
        self.refresh()  # drive mode, shutter limits and flash change with it; they arrive with a new session

    def _set_stack_flag(self, value):
        """d0ce = Focus Stacking On (1) / Off (2), mapped 2026-11-16 (changed alone when the stacking switch was
        flipped on the camera). d0cb is only Focus BKT, a plain series. Not every body has it: then it is skipped."""
        try:
            self._value("d0ce")
        except CameraError:
            return
        self._set("d0ce", value)

    def _prop_now(self, code):
        """Property value as the camera has it now: live (GetDevicePropValue) on the own PTP layer, because the
        descriptor keeps the value from the session start (a change in the camera menu would not show)."""
        try:
            return str(self._live_int(code))
        except (CameraError, AttributeError):  # no live read (libgphoto2 backend): the descriptor value
            return str(self._value(code))

    def _set_bkt_main(self, value):
        """Bracketing main switch d0a6 (USB test 2026-11-22); returns the value before, None on a body without it."""
        try:
            before = self._prop_now(BKT_MAIN)
        except CameraError:
            return None
        self._set(BKT_MAIN, value)
        return before

    def _bkt_main_off(self):
        try:
            return self._prop_now(BKT_MAIN) == "2"
        except CameraError:
            return False  # a body without the switch

    def _stack_flag_on(self):
        try:
            return self._prop_now("d0ce") == "1"  # Focus BKT alone is a plain series, not stacking
        except CameraError:
            return True  # a body without d0ce: Focus BKT is the only switch

    def _stacking_on(self):
        try:
            if self._bkt_main_off() or self._prop_now("d0cb") != "1":
                return False
        except CameraError:
            return False
        return self._stack_flag_on()

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
            self.direct_paths, self._direct_hit = [], False
            self._pre_release()  # no card: decided here, while the camera is idle
            if self._is_bulb():
                self._shutter(OP_FULL)
            else:
                self._pulse()
        except Exception:
            self.shooting, self._take_t0 = False, None
            raise

    def take_stop(self):
        t_start = self._take_t0
        try:
            if self._is_bulb():
                self._shutter(OP_RELEASE)
            else:
                self._pulse()
            if self._direct_wait:
                # no card: noise reduction takes about as long as the exposure, then the camera offers the picture
                t0 = time.monotonic()
                wait = max(SHOT_TIMEOUT, (t0 - t_start if t_start else 0.0) * 1.2 + 15.0)
                self._hold_add(1)
                try:
                    self._events(wait, "quiet")
                    self._direct_store(t0 + wait)
                finally:
                    self._hold_add(-1)
            else:
                self._events(2.0)
        finally:
            self._direct_wait = False
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

    def focus_mode(self):
        """Current AF mode code as string ('1' = MF, '32769' = S-AF+MF, '2' = S-AF, '32770' = C-AF)."""
        return self._prop_now("d003")

    def take_mode(self):
        """Current shooting mode name ('P', 'A', 'S', 'M', 'movie', or '?')."""
        return EXPOSURE_PROGRAM.get(str(self._value("d006")), "?")

    def set_lv_boost(self, value):
        """Set Live View Boost d0ea (1 On1, 2 Off, 3 On2); returns previous int value or None if unsupported."""
        self._need_write()
        try:
            before = int(float(self._prop_now(LV_BOOST)))
        except (CameraError, ValueError):
            return None
        want = int(value)
        if before != want:
            self._set(LV_BOOST, want)
        return before

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
            if shot and DIRECT_EVENT.search(str(data)):
                self._direct_hit = True

    def _events(self, seconds, stop=None):
        """Collect events without blocking the camera in between."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            kind, data = self._call(self._c.wait_for_event, 150)
            self._on_event(kind, data)
            if kind == self.gp.GP_EVENT_UNKNOWN and stop and (
                    stop.search(str(data)) if hasattr(stop, "search") else stop in str(data).lower()):
                return True
            if self._new_files and kind == self.gp.GP_EVENT_TIMEOUT and stop == "quiet":
                return True
            if stop == "quiet" and self._direct_wait and self._direct_hit and not self._new_files:
                return True  # no card: the camera offers the picture itself
            if stop == "quiet" and self.saf_shot and not self._new_files and kind == self.gp.GP_EVENT_UNKNOWN \
                    and parse_af_result(str(data)) == (False, None):
                # no focus in S-AF: the camera does not release (Release Priority S is off by default); C-AF
                # releases anyway by default, so only S-AF stops early
                self.af_failed = True
                end = min(end, time.monotonic() + 1.0)
        return False

    def _no_fast_picture(self):
        """True when 0x9485 could hand back the wrong picture: the previous shot's JPEG or one of many frames.

        Self-timer (the camera exposes seconds later), Focus Stacking (one of 8 source frames), movie,
        Bulb/Time/Composite, and S-AF without focus (no release). An unreadable value does not skip by itself.
        """
        if getattr(self, "af_failed", False):
            return "af failed"
        def read(name):
            try:
                return self._value(name)
            except Exception:
                return None
        drive = read("drivemode")
        try:
            if int(float(drive)) & 15 in (4, 5, 6):
                return "self-timer"
        except (TypeError, ValueError):
            pass
        if str(read("d006")) == "8":
            return "movie"
        if LONG_LABELS.get(read("shutterspeed")):
            return "long exposure"
        try:
            return "focus stacking" if self._stacking_on() else ""
        except Exception:
            return ""

    def _fast_picture(self):
        """After a full release: fetch the shot's JPEG (PTP 0x9485) so it can be shown before the card lists it.

        Only the own PTP layer has the call; on libgphoto2 or on any error/empty answer nothing happens
        and the card path stays the only source.
        """
        self._fast_note = ""
        fetch = getattr(self._c, "omd_get_image", None)
        if not fetch or not self.on_fast_jpeg:
            return
        skip = self._no_fast_picture()
        if skip:
            self._fast_note = "skipped: %s" % skip
            return
        # after two empty answers in a row (RAW only, no card) only probe briefly, so shots are not held back
        wait = 1.2 if self._fast_empty < 2 else 0.2
        try:
            data = self._call(fetch, wait)
        except Exception as e:
            self._fast_note = "error: %s" % e
            return
        if data and data[:2] == b"\xff\xd8":
            self._fast_empty = 0
            self._fast_note = "delivered"
            self.on_fast_jpeg(data)
        else:
            self._fast_empty += 1
            self._fast_note = "empty (wait %.1f s)" % wait

    def _direct_capable(self):
        """The server wants direct files and the backend can read them (own PTP layer, not libgphoto2)."""
        return bool(self.on_direct_file and getattr(self._c, "omd_direct_info", None))

    def _card_state(self):
        """True: the camera lists a storage with a size (a card, also a write-protected one); False: none;
        None: unknown (read error). Unknown is treated like a card by the callers: the old behaviour."""
        try:
            return free_kbytes(self._call(self._c.get_storageinfo)) is not None
        except Exception as e:
            # no card: the camera still lists a slot (id 0x10000) but every request to it is refused: 0x2008
            # InvalidStorageID (GetStorageInfo / GetObjectHandles) or 0x2013 StoreNotAvailable (no-card test
            # 2026-11-21); that is "no card", not "unknown"
            return False if _no_card_error(e) else None

    CARD_SETTLE = (1.0, 1.0, 1.0)  # pauses: right after a (re)connect a card answers 0x2013 for 1-2 s

    def _card_state_settled(self):
        """Card state after a connect or a rebuilt session (e.g. after a card change): "no card" is only
        believed after a few tries, because a card that was just put in answers 0x2013 for a moment
        (USB test 2026-11-22). Costs up to 3 s only when there really is no card."""
        state = self._card_state()
        for pause in self.CARD_SETTLE:
            if state is not False:
                break
            time.sleep(pause)
            state = self._card_state()
        return state

    def _settle_card(self):
        """After a rebuilt session, outside the camera lock: the tries may sleep up to 3 s without a card."""
        if self._card_due:
            self._card_due = False
            self.card = self._card_state_settled()

    def refresh_card(self):
        """Read the card state once and keep it: the page asks often, the camera must not be polled for it.
        Right after a release that already read it (_pre_release) the stored value is kept: no second read."""
        if self._card_read:
            self._card_read = False
            return self.card
        self.card = self._card_state()
        return self.card

    def _pre_release(self, stacking=None):
        """Decide ONCE, while the camera is idle, whether this shot comes without a card (then `_direct_wait`
        makes the wait end at the camera's own offer). Also saves a picture the camera still holds from an
        earlier shot, so it cannot show up under this shot's name. Focus Stacking needs a card."""
        self._direct_wait = False
        if not self._direct_capable():
            return
        self.card, self._card_read = self._card_state(), True
        if self.card is not False:
            return
        if self._stacking_on() if stacking is None else stacking:
            raise CameraError("Focus Stacking needs a card: the camera keeps the merged picture on the card")
        self._save_leftover()
        self._direct_wait = True

    def _save_leftover(self):
        """A picture still offered before the release belongs to an earlier shot: save it as `_late`."""
        last = None
        self._hold_add(1)  # no live view frame may slip between the pieces
        try:
            for _ in range(4):
                info = self._call(self._c.omd_direct_info)
                if not info:
                    return
                if (info["ext"], info["size"]) == last:
                    return  # same file again: the camera ignored clear=1, do not save it repeatedly
                last = (info["ext"], info["size"])
                path = self.on_direct_file(info["ext"], info["size"], self._pieces(info), True)
                print("USB direct store: saved a leftover picture first: %s" % path, flush=True)
        except (CameraError, OSError) as e:
            print("USB direct store: leftover picture not read: %s" % e, flush=True)
        finally:
            self._hold_add(-1)

    def _pieces(self, info):
        """The pieces of one picture, read lazily from the camera (the sink writes each to disk as it arrives)."""
        it = iter(self._call(self._c.omd_direct_fetch, info))
        while True:
            piece = self._call(next, it, None)
            if piece is None:
                return
            yield piece

    def _direct_store(self, deadline=None):
        """No card file came but the camera announced the picture: read it (ORF, then JPG) and hand each file
        to `on_direct_file`. Own PTP layer only. Raises CameraError on a failed read (what was saved stays).
        `deadline` (monotonic): when a card shows up after all, the card path waits until then."""
        wanted, self._direct_wait = self._direct_wait, False  # set before the release, only without a card
        if not (wanted and self._direct_hit and self._direct_capable()):
            return
        self._events(DIRECT_GRACE)  # a card file announced right after 0xC004 means the card is the truth
        if self._new_files or self._card_state() is True:
            if deadline:
                self._events(max(0.0, deadline - time.monotonic()), "quiet")
            return
        try:
            while True:
                self._drain_events()  # events of the file in hand (c004, d0de) must not count as "next file"
                info = self._call(self._c.omd_direct_info)
                if not info:
                    break
                t0 = time.monotonic()
                path = self.on_direct_file(info["ext"], info["size"], self._pieces(info))
                self._direct_hit = False
                self.direct_paths.append(path)
                print("USB direct store: %s %.1f MB in %.1f s" % (info["ext"], info["size"] / 1e6, time.monotonic() - t0),
                      flush=True)
                if str(info["ext"]).lower() in (".jpg", ".jpeg"):
                    break  # the camera sends ORF first, the JPG is last (by extension: the info kind differs)
                if not self._events(DIRECT_NEXT_WAIT, DIRECT_EVENT):
                    break  # no further file announced
        except (CameraError, OSError) as e:
            if not self.direct_paths:  # nothing saved: a clean failure for the caller
                raise CameraError("Picture could not be read from the camera (no card): %s" % e)
            print("USB direct store: stopped after %d file(s): %s" % (len(self.direct_paths), e), flush=True)
        self._direct_hit = False

    def _drain_events(self):
        """Take every event that is already waiting (own layer: cheap, about 40 ms when idle)."""
        for _ in range(20):
            kind, data = self._call(self._c.wait_for_event, 40)
            self._on_event(kind, data)
            if kind == self.gp.GP_EVENT_TIMEOUT:
                return

    def take_direct_files(self):
        done, self.direct_paths = self.direct_paths, []
        return done

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
            if stage == 2:
                self.direct_paths, self._direct_hit = [], False
                self._pre_release()
            self._event_log = []  # _read_focus_position looks for this half press's AF event
            self._shutter(OP_FIRST)
            self.stage = 1
            if stage == 1:
                self._read_focus_position()
            else:
                self._events(FOCUS_WAIT)
                self._shutter(OP_SECOND)
                self.stage = 2
        elif stage == 2:
            self.direct_paths, self._direct_hit = [], False
            self._pre_release()
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
                # half press only while zoomed: release without a shot, as OM Capture does (step 6 untested there)
                self._shutter(OP_RELEASE_NOSHOT if self.loupe_on and not full else OP_RELEASE)
            if full:
                self._fast_picture()
            t_ev = time.monotonic()
            self._events(2.0 if full else 0.2, "quiet" if full else None)
            if full and self._direct_wait:
                self._hold_add(1)  # no live view frames between the pieces of a picture
                try:
                    if not (self._new_files or self._direct_hit):
                        self._events(SHOT_TIMEOUT - 2.0, "quiet")  # no card: the camera takes longer than 2 s
                    self._direct_store(t_ev + SHOT_TIMEOUT)
                finally:
                    self._direct_wait = False
                    self._hold_add(-1)

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
            # own PTP layer: the AF event 0xC003 carries the exact position at once (d05d/d05e read through
            # 0x1014 can keep an old value for the whole session, USB test 2026-11-22)
            for text in reversed(self._event_log):
                result = parse_af_result(text)
                if result and (result[1] or not result[0]):  # libgphoto2 events carry no position: read below
                    self.focus_ok = bool(result[0])
                    self.last_af = result[1] or {"x": 0, "y": 0}
                    return
            x, y = int(float(self._value("d05d"))), int(float(self._value("d05e")))
            if (x or y) and (x, y) != prev:
                break
        self.last_af = {"x": x, "y": y}

    def focus(self):
        """Focus like half press and release. Returns True when the camera reports focus (event c003, Param1 1),
        False when it reports none (Param1 2) or sends no result.

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
                result = parse_af_result(self._event_log[-1]) if self._events(FOCUS_WAIT, FOCUS_EVENT) else None
                self.focus_ok = bool(result and result[0])
                if result and result[1]:
                    self.last_af = result[1]  # exact and at once (d05d/d05e lag behind)
                elif result and not result[0]:
                    self.last_af = {"x": 0, "y": 0}  # no focus: no green field
                elif self.focus_ok and getattr(self, "af_mode", AF_ALL) == AF_ALL and not self.loupe_on:
                    self._read_focus_position()  # libgphoto2 backend: events carry Param1 only
                if result is None:
                    print("USB focus: no AF result from the camera within %.0f s" % FOCUS_WAIT, flush=True)
            finally:
                # zoomed: 5 ends the half press without a shot (the camera answers 0xC003 (1,0,0), no position)
                self._shutter(OP_RELEASE_NOSHOT if self.loupe_on else OP_RELEASE)
            # no extra event wait here: each idle libgphoto2 event check costs ~0.3 s (150 ms timeout
            # plus one retry); the next check (dial watch or next focus) collects what is left
        finally:
            self._hold_add(-1)
        return self.focus_ok

    def shoot(self):
        """Release once. Returns the new file paths (JPG and ORF)."""
        try:
            return self._shoot()
        except Exception:
            self._card_read = False  # the card read of a failed release must not stand in for a fresh one
            raise

    def _stack_events(self, until, marks, t0):
        """Collect the stacking files until `until`. While the camera merges the 8 frames it does not answer
        over USB for a while (USB test 2026-11-22: "camera not connected" although all files were written);
        that is waiting, not a lost camera."""
        busy = False
        while time.monotonic() < until:
            try:
                self._events(max(0.0, until - time.monotonic()))
            except CameraError:
                if self.gone:  # the live view loop saw the camera leave USB: not merging
                    raise
                if not busy:
                    busy = True
                    marks.append(("camera busy merging", time.monotonic() - t0))
                time.sleep(0.5)

    def _shoot(self):
        self.stack_note = None
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
            self.saf_shot = int(float(self._value("d003"))) == AF_SINGLE
            self.direct_paths, self._direct_hit = [], False
            self._pre_release(stacking)  # no card: decided once, before the release
            self._shutter(OP_FULL)
            self._shutter(OP_RELEASE)
            marks.append(("released", time.monotonic() - t0))
            self._fast_picture()
            marks.append(("fast picture [%s]" % self._fast_note, time.monotonic() - t0))
            self.af_failed = False
            self._event_log = []
            t_ev = time.monotonic()
            self._events(SHOT_TIMEOUT, "quiet")
            self._direct_store(t_ev + SHOT_TIMEOUT)
            if stacking:  # 8 frames (16 files) come first, the merged picture last
                self._stack_events(t0 + STACK_FRAMES_WAIT, marks, t0)
                if len(set(self._new_files)) <= 2:  # one frame (JPG+ORF): the camera did not stack
                    self.stack_note = True
                    marks.append(("stacking: 1 frame", time.monotonic() - t0))
                else:
                    self._stack_events(t0 + STACK_WAIT, marks, t0)
            marks.append(("files" if not self.direct_paths else "direct store", time.monotonic() - t0))
            if self._new_files:
                self._events(1.5)  # the second format (ORF or JPG) follows shortly after
        except Exception as e:
            marks.append(("error [%s]" % e, time.monotonic() - t0))
            raise
        finally:
            self._direct_wait = False
            self._hold_add(-1)
            self.shooting = False
            marks.append(("done", time.monotonic() - t0))
            print("USB shot: " + ", ".join("%s %.1f s" % m for m in marks)
                  + ("" if self._new_files or self.direct_paths else ", events " + ("; ".join(self._event_log[-6:]) or "none")), flush=True)
        new = self.take_new_files()
        if not new and self.direct_paths:
            return []  # saved by the direct store: the caller reads take_direct_files()
        if not new:
            if getattr(self, "af_failed", False):
                raise CameraError("Camera did not release: no focus found (S-AF releases only in focus)")
            raise CameraError("Camera did not release, probably no focus found")
        return new
