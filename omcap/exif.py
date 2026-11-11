"""Lens and picture data from the EXIF header of an Olympus JPG.

Over Wi-Fi the camera reports no lens data (focalvalue always lists
f/1.0 to f/91). Every shot contains it though: standard EXIF LensModel
and the Equipment group (0x2010) in the Olympus MakerNote.

The first ~128 KB of the file are enough.
"""
import struct

HEAD_BYTES = 1 << 17

_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 13: 4}

# Olympus Equipment (MakerNote 0x2010)
_EQ_MODEL, _EQ_AP_WIDE, _EQ_AP_TELE = 0x0203, 0x0205, 0x0206
_EQ_FOCAL_MIN, _EQ_FOCAL_MAX, _EQ_AP_NOW = 0x0207, 0x0208, 0x020A


class _Tiff:
    """Minimal IFD reader, offsets relative to base."""

    def __init__(self, data, base, order):
        self.data, self.base, self.e = data, base, "<" if order == b"II" else ">"

    def ifd(self, off):
        d, e, base = self.data, self.e, self.base
        n = struct.unpack_from(e + "H", d, base + off)[0]
        out = {}
        for i in range(n):
            tag, typ, cnt, val = struct.unpack_from(e + "HHI4s", d, base + off + 2 + 12 * i)
            size = _SIZES.get(typ, 1) * cnt
            if size <= 4:
                raw = val[:size]
            else:
                start = base + struct.unpack(e + "I", val)[0]
                raw = d[start:start + size]
                if len(raw) < size:  # lies beyond the bytes read
                    continue
            out[tag] = (typ, cnt, raw)
        return out

    def value(self, entry):
        typ, cnt, raw = entry
        e = self.e
        if typ == 2:
            return raw.split(b"\0")[0].decode("latin-1").strip()
        if typ == 3:
            return struct.unpack(e + "H" * cnt, raw)[0]
        if typ in (4, 13):
            return struct.unpack(e + "I" * cnt, raw)[0]
        if typ == 5:
            num, den = struct.unpack(e + "II", raw[:8])
            return num / den if den else None
        if typ == 10:
            num, den = struct.unpack(e + "ii", raw[:8])
            return num / den if den else None
        return None


def _fnumber(v):
    """Olympus stores apertures as 512 * log2(F)."""
    return round(2 ** (v / 512), 1) if v else None


def lens_info(head):
    """Lens data as dict, or None if nothing readable is inside.

    Keys: model, focal_min, focal_max (mm), aperture_wide, aperture_tele
    (maximum aperture at the short/long end), focal, aperture_now (focal length and
    maximum aperture at the time of the shot).
    """
    try:
        t = head.index(b"Exif\0\0") + 6
        tiff = _Tiff(head, t, head[t:t + 2])
        ifd0 = tiff.ifd(struct.unpack_from(tiff.e + "I", head, t + 4)[0])
        exif = tiff.ifd(tiff.value(ifd0[0x8769]))
    except (ValueError, KeyError, struct.error, TypeError):
        return None
    info = {"model": tiff.value(exif[0xA434]) if 0xA434 in exif else None,
            "focal": tiff.value(exif[0x920A]) if 0x920A in exif else None}
    note = exif.get(0x927C)
    if note and note[2][:8] == b"OLYMPUS\0":
        try:
            # MakerNote offsets count from its own start
            mn = _Tiff(head, head.index(note[2][:16], t), note[2][8:10])
            eq = mn.ifd(mn.value(mn.ifd(12)[0x2010]))
            get = lambda tag: mn.value(eq[tag]) if tag in eq else None
            info.update(model=get(_EQ_MODEL) or info["model"],
                        focal_min=get(_EQ_FOCAL_MIN), focal_max=get(_EQ_FOCAL_MAX),
                        aperture_wide=_fnumber(get(_EQ_AP_WIDE)),
                        aperture_tele=_fnumber(get(_EQ_AP_TELE)),
                        aperture_now=_fnumber(get(_EQ_AP_NOW)))
        except (ValueError, KeyError, struct.error, TypeError):
            pass
    return info if info.get("model") or info.get("aperture_wide") else None


# --- picture info for the playback "Overall display" ---------------------------------------
EXPOSURE_PROGRAM = {1: "M", 2: "P", 3: "A", 4: "S", 5: "Creative", 6: "Action", 7: "Portrait", 8: "Landscape"}
METERING = {1: "Average", 2: "Center-weighted", 3: "Spot", 4: "Multi-pattern", 5: "ESP", 6: "Partial"}
# Olympus CameraSettings (0x2020) tag 0x0520, first value
PICTURE_MODE = {1: "Vivid", 2: "Natural", 3: "Muted", 4: "Portrait", 5: "i-Enhance", 6: "e-Portrait",
                7: "Color Creator", 8: "Underwater", 256: "Monotone", 512: "Custom"}
_MN_CAMERA_SETTINGS, _CS_PICTURE_MODE = 0x2020, 0x0520


def _shutter(v):
    if not v or v <= 0:
        return None
    if v >= 0.5:
        return ("%.1f" % v).rstrip("0").rstrip(".") + " s"
    return "1/%d" % round(1 / v)


def picture_info(head):
    """Shooting data of a JPG as dict; fields that are not in the file are left out.

    Keys: mode (P/A/S/M ...), shutter ("1/250"), aperture (F number), compensation (EV), iso,
    white_balance, metering, flash, focal (mm), lens, picture_mode, color_space, pixels
    ("4608x3456"), datetime ("2026-11-09 09:14:12"). Returns None if there is no EXIF at all.
    """
    try:
        t = head.index(b"Exif\0\0") + 6
        tiff = _Tiff(head, t, head[t:t + 2])
        ifd0 = tiff.ifd(struct.unpack_from(tiff.e + "I", head, t + 4)[0])
        ex = tiff.ifd(tiff.value(ifd0[0x8769]))
    except (ValueError, KeyError, struct.error, TypeError):
        return None
    get = lambda tag: tiff.value(ex[tag]) if tag in ex else None
    out = {}

    def put(key, val):
        if val not in (None, ""):
            out[key] = val
    put("mode", EXPOSURE_PROGRAM.get(get(0x8822)))
    put("shutter", _shutter(get(0x829A)))
    fn = get(0x829D)
    put("aperture", round(fn, 1) if fn else None)
    bias = get(0x9204)
    put("compensation", round(bias, 1) if bias is not None else None)
    put("iso", get(0x8827))
    put("white_balance", {0: "Auto", 1: "Manual"}.get(get(0xA403)))
    put("metering", METERING.get(get(0x9207)))
    fl = get(0x9209)
    if fl is not None:
        out["flash"] = bool(fl & 1)
    fo = get(0x920A)
    put("focal", round(fo, 1) if fo else None)
    put("lens", get(0xA434))
    put("color_space", {1: "sRGB", 2: "Adobe RGB", 0xFFFF: "Adobe RGB"}.get(get(0xA001)))
    w, h = get(0xA002), get(0xA003)
    if w and h:
        out["pixels"] = "%dx%d" % (w, h)
    dt = get(0x9003)
    if isinstance(dt, str) and len(dt) >= 19:
        out["datetime"] = dt[:4] + "-" + dt[5:7] + "-" + dt[8:10] + dt[10:19]
    note = ex.get(0x927C)
    if note and note[2][:8] == b"OLYMPUS\0":
        try:
            # MakerNote offsets count from its own start (as in lens_info)
            mn = _Tiff(head, head.index(note[2][:16], t), note[2][8:10])
            top = mn.ifd(12)
            try:
                cs = mn.ifd(mn.value(top[_MN_CAMERA_SETTINGS]))
                put("picture_mode", PICTURE_MODE.get(mn.value(cs[_CS_PICTURE_MODE])))
            except (KeyError, struct.error, TypeError):
                pass
            if "lens" not in out and 0x2010 in top:
                eq = mn.ifd(mn.value(top[0x2010]))
                put("lens", mn.value(eq[_EQ_MODEL]) if _EQ_MODEL in eq else None)
        except (ValueError, KeyError, struct.error, TypeError):
            pass
    return out or None
