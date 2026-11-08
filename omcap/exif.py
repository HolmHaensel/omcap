"""Objektivdaten aus dem EXIF-Kopf einer Olympus-JPG.

Die Kamera meldet über Wi-Fi keine Objektivdaten (focalvalue listet immer
f/1.0 bis f/91). In jeder Aufnahme stehen sie aber: Standard-EXIF LensModel
und in der Olympus-MakerNote die Gruppe Equipment (0x2010).

Es reichen die ersten rund 128 KB der Datei.
"""
import struct

HEAD_BYTES = 1 << 17

_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 13: 4}

# Olympus Equipment (MakerNote 0x2010)
_EQ_MODEL, _EQ_AP_WIDE, _EQ_AP_TELE = 0x0203, 0x0205, 0x0206
_EQ_FOCAL_MIN, _EQ_FOCAL_MAX, _EQ_AP_NOW = 0x0207, 0x0208, 0x020A


class _Tiff:
    """Minimaler IFD-Leser, Offsets relativ zu base."""

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
                if len(raw) < size:  # liegt hinter dem gelesenen Kopf
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
        return None


def _fnumber(v):
    """Olympus speichert Blenden als 512 * log2(F)."""
    return round(2 ** (v / 512), 1) if v else None


def lens_info(head):
    """Objektivdaten als dict oder None, wenn nichts Lesbares drin ist.

    Schlüssel: model, focal_min, focal_max (mm), aperture_wide, aperture_tele
    (offene Blende am kurzen/langen Ende), focal, aperture_now (Brennweite und
    offene Blende bei der Aufnahme).
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
            # Offsets der MakerNote zählen ab ihrem eigenen Anfang
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
