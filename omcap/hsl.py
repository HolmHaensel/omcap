"""Software-HSL-Farbprofil nach dem Vorbild des PEN-F-Frontrad-Modus COLOR.

Zahlen (12 Sektoren, Reihenfolge, Slider -7..+7, H_native = -1000 x H,
L-Tabelle -300..+300) stammen aus oly_fw_analysis/docs/color/pen-f/HSL_TABLES.md
und docs/color/MODES.md. Es wird kein Code aus der dortigen GPL-Forschung
uebernommen, nur die dokumentierten Werte.

Wahl des Farbraums: CIELAB-LCh aus linearem sRGB (D65). Die Doku sagt, die
Sektoren liegen in einem Chroma-Raum und nicht auf RGB-Winkeln; LCh ist
wahrnehmungsnah genug, damit gleiche Schritte aehnlich stark wirken.

Naeherungen (nicht die Kamerawerte):
- Sektormitten als LCh-Winkel (siehe SECTOR_ANGLES), von Hand gesetzt.
- Hue: 3 Grad pro Schritt konstant. Positiv = zum naechsten Sektor in
  Raddrehung (Gelb -> Orange -> Rot -> ...), also fallender LCh-Winkel.
- Saturation: +-6 % Chroma pro Schritt, in allen Sektoren gleich (die Kamera
  nutzt sektorabhaengige Verstaerkung, hier nicht nachgebaut).
- Lightness: L_native/1000 x 25 L* (+-300 -> +-7.5 L*).
- Gewichte: Raised-Cosine zwischen benachbarten Sektormitten (Summe = 1,
  keine harten Kanten), zusaetzlich mit der Chroma gewichtet (Grau bleibt).
"""
import json
import os

import numpy as np

SECTORS = ["yellow", "orange", "red", "rose", "magenta", "violet",
           "blue", "azure", "cyan", "teal", "green", "lime"]

# LCh-Winkel (Grad) der Sektormitten, Naeherungen. sRGB: Rot ~40, Gelb ~102,
# Gruen ~136, Cyan ~196, Blau ~265, Magenta ~328.
SECTOR_ANGLES = [100.0, 65.0, 40.0, 10.0, 335.0, 300.0,
                 265.0, 235.0, 195.0, 170.0, 140.0, 118.0]

SLIDER_MIN, SLIDER_MAX = -7, 7
HUE_DEG_PER_STEP = 3.0
SAT_GAIN_PER_STEP = 0.06
L_STAR_PER_1000 = 25.0
# Slider -7..+7 -> L_native (aus HSL_TABLES.md)
L_NATIVE = [-300, -250, -200, -150, -100, -50, -25, 0, 25, 50, 100, 150, 200, 250, 300]
# Chroma-Gewicht: unter C_LO unberuehrt, ab C_HI voll
C_LO, C_HI = 2.0, 14.0

_D65 = np.array([0.95047, 1.0, 1.08883])
_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_MI = np.linalg.inv(_M)
_EPS, _KAPPA = 216 / 24389, 24389 / 27

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PRESET_FILE = os.path.join(DATA_DIR, "hsl_presets.json")


# ---------- Profil ----------

def neutral_profile(name="Neutral"):
    return {"name": name, "sectors": {s: {"h": 0, "s": 0, "l": 0} for s in SECTORS}}


def validate_profile(profile):
    """Gibt ein normalisiertes Profil zurueck, ValueError bei Fehlern."""
    if not isinstance(profile, dict):
        raise ValueError("profile must be a dict")
    out = neutral_profile(str(profile.get("name", "Profile")))
    sectors = profile.get("sectors", {})
    if not isinstance(sectors, dict):
        raise ValueError("sectors must be a dict")
    for name, vals in sectors.items():
        if name not in SECTORS:
            raise ValueError("unknown sector: %r" % (name,))
        if not isinstance(vals, dict):
            raise ValueError("sector %s must be a dict" % name)
        for k, v in vals.items():
            if k not in ("h", "s", "l"):
                raise ValueError("unknown key %r in sector %s" % (k, name))
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v):
                raise ValueError("%s.%s must be an integer" % (name, k))
            if not SLIDER_MIN <= v <= SLIDER_MAX:
                raise ValueError("%s.%s out of range %d..%d" % (name, k, SLIDER_MIN, SLIDER_MAX))
            out["sectors"][name][k] = int(v)
    return out


def set_all(profile, h=None, s=None, l=None):
    """'ALL'-Operation: setzt die angegebenen Regler in allen 12 Sektoren."""
    out = validate_profile(profile)
    for name in SECTORS:
        for k, v in (("h", h), ("s", s), ("l", l)):
            if v is not None:
                out["sectors"][name][k] = v
    return validate_profile(out)


def load_slots(path):
    """Datei mit drei Profilplaetzen (COLOR1-3): {"slots": [p1, p2, p3]}."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    slots = data.get("slots")
    if not isinstance(slots, list) or not 1 <= len(slots) <= 3:
        raise ValueError("slot file needs a list 'slots' with 1-3 profiles")
    return [validate_profile(p) for p in slots]


def save_slots(path, profiles):
    if not 1 <= len(profiles) <= 3:
        raise ValueError("1-3 profiles")
    data = {"slots": [validate_profile(p) for p in profiles]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def save_profile(path, profile):
    data = validate_profile(profile)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_profile(path_or_name):
    """Name eines Presets (hsl_presets.json), oder Pfad zu Profil-/Slot-JSON.
    Bei einer Slot-Datei zaehlt der erste Platz; 'datei.json#2' waehlt Platz 2."""
    ref = str(path_or_name)
    path, _, slot = ref.partition("#")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "slots" in data:
            slots = load_slots(path)
            idx = int(slot) - 1 if slot else 0
            if not 0 <= idx < len(slots):
                raise ValueError("slot out of range")
            return slots[idx]
        return validate_profile(data)
    with open(PRESET_FILE, encoding="utf-8") as f:
        presets = json.load(f)["presets"]
    for p in presets:
        if p["name"].lower() == ref.lower():
            return validate_profile(p)
    raise ValueError("no such preset or file: %s (presets: %s)"
                     % (ref, ", ".join(p["name"] for p in presets)))


# ---------- Farbraum ----------

def _srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def srgb_to_lch(rgb):
    lin = _srgb_to_linear(np.asarray(rgb, dtype=np.float64))
    xyz = lin @ _M.T / _D65
    f = np.where(xyz > _EPS, np.cbrt(xyz), (_KAPPA * xyz + 16) / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return L, np.hypot(a, b), np.degrees(np.arctan2(b, a)) % 360.0


def lch_to_srgb(L, C, h):
    a = C * np.cos(np.radians(h))
    b = C * np.sin(np.radians(h))
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def inv(f):
        return np.where(f ** 3 > _EPS, f ** 3, (116 * f - 16) / _KAPPA)

    xyz = np.stack([inv(fx), inv(fy), inv(fz)], axis=-1) * _D65
    return _linear_to_srgb(xyz @ _MI.T)


# ---------- Anwendung ----------

def _sector_weights(h):
    """Pro Winkel: Sektor a, Nachbar b (naechste Mitte mit groesserem Winkel)
    und Gewicht t des Nachbarn (Raised-Cosine, a bekommt 1-t)."""
    order = sorted(range(12), key=lambda i: SECTOR_ANGLES[i])
    ang = np.array([SECTOR_ANGLES[i] for i in order])
    idx = np.array(order)
    pos = np.searchsorted(ang, h, side="right") - 1   # -1 = Umlauf
    lo = ang[pos % 12] - np.where(pos < 0, 360.0, 0.0)
    nxt = (pos + 1) % 12
    hi = ang[nxt] + np.where(pos + 1 >= 12, 360.0, 0.0)
    f = (h - lo) / (hi - lo)
    t = (1 - np.cos(np.pi * f)) / 2
    return idx[pos % 12], idx[nxt], t


def apply_hsl(rgb_float, profile):
    """rgb_float: H x W x 3 (oder ... x 3), sRGB 0..1. Gibt gleiche Form zurueck."""
    prof = validate_profile(profile)
    rgb = np.asarray(rgb_float, dtype=np.float64)
    if rgb.shape[-1] != 3:
        raise ValueError("last axis must be 3 (RGB)")
    sec = prof["sectors"]
    dh = np.array([-HUE_DEG_PER_STEP * sec[s]["h"] for s in SECTORS], dtype=np.float64)
    gain = np.array([1 + SAT_GAIN_PER_STEP * sec[s]["s"] for s in SECTORS], dtype=np.float64)
    dl = np.array([L_NATIVE[sec[s]["l"] - SLIDER_MIN] / 1000.0 * L_STAR_PER_1000
                   for s in SECTORS], dtype=np.float64)

    L, C, h = srgb_to_lch(rgb)
    a, b, t = _sector_weights(h)

    def mix(arr):
        return (1 - t) * arr[a] + t * arr[b]

    x = np.clip((C - C_LO) / (C_HI - C_LO), 0, 1)
    cw = x * x * (3 - 2 * x)
    h2 = (h + mix(dh) * cw) % 360.0
    C2 = np.maximum(C * (1 + (mix(gain) - 1) * cw), 0)
    L2 = np.clip(L + mix(dl) * cw, 0, 100)
    return lch_to_srgb(L2, C2, h2).reshape(rgb.shape)


# ---------- Testbilder, Ein-/Ausgabe ----------

def wheel_chart(profile, size=360):
    """12-Sektor-Farbrad (L*=65, Chroma steigt nach aussen): (vorher, nachher).
    Gelb oben, im Uhrzeigersinn in Raddrehung."""
    ys, xs = np.mgrid[0:size, 0:size]
    dx, dy = xs - (size - 1) / 2, (size - 1) / 2 - ys
    r = np.hypot(dx, dy) / (size / 2)
    pos = ((90 - np.degrees(np.arctan2(dy, dx))) % 360.0) / 30.0   # 0..12
    i0 = np.floor(pos).astype(int) % 12
    f = pos - np.floor(pos)
    ang = np.array(SECTOR_ANGLES)
    d = ((ang[(i0 + 1) % 12] - ang[i0] + 180) % 360) - 180
    hue = (ang[i0] + d * f) % 360.0
    img = lch_to_srgb(np.full(r.shape, 65.0), np.clip(r, 0, 1) * 70.0, hue)
    img[r > 1] = 1.0
    out = apply_hsl(img, profile)
    out[r > 1] = 1.0
    return img, out


def _read_image(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".orf", ".dng", ".raw"):
        import rawpy   # nur fuer RAW noetig
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True,
                                  output_bps=16, output_color=rawpy.ColorSpace.sRGB)
        return rgb.astype(np.float64) / 65535.0, True
    import imageio.v2 as imageio
    img = np.asarray(imageio.imread(path))[..., :3]
    return img.astype(np.float64) / (65535.0 if img.dtype == np.uint16 else 255.0), False


def _to_u8(x):
    return (np.clip(x, 0, 1) * 255 + 0.5).astype(np.uint8)


def _shrink(x, maxw=1200):
    step = max(1, x.shape[1] // maxw)
    return x[::step, ::step]


def process_file(path, profile, out_dir, sheet=False):
    import imageio.v2 as imageio
    rgb, is_raw = _read_image(path)
    res = apply_hsl(rgb, profile)
    stem = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(out_dir, exist_ok=True)
    written = []
    if is_raw:
        p = os.path.join(out_dir, stem + "_hsl.tif")
        imageio.imwrite(p, (np.clip(res, 0, 1) * 65535 + 0.5).astype(np.uint16))
    else:
        p = os.path.join(out_dir, stem + "_hsl.jpg")
        imageio.imwrite(p, _to_u8(res), quality=95)
    written.append(p)
    if sheet:
        both = np.concatenate([_shrink(rgb), _shrink(res)], axis=1)
        p = os.path.join(out_dir, stem + "_hsl_sheet.jpg")
        imageio.imwrite(p, _to_u8(both), quality=90)
        written.append(p)
        before, after = wheel_chart(profile)
        p = os.path.join(out_dir, stem + "_hsl_wheel.jpg")
        imageio.imwrite(p, _to_u8(np.concatenate([before, after], axis=1)), quality=92)
        written.append(p)
    return written


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m omcap.hsl",
                                 description="Apply a software HSL colour profile to ORF/JPG files.")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--profile", required=True, help="preset name or JSON file (file.json#2 = slot 2)")
    ap.add_argument("--out", default=os.path.join("out", "hsl"))
    ap.add_argument("--sheet", action="store_true", help="also write before/after sheet and wheel chart")
    args = ap.parse_args(argv)
    profile = load_profile(args.profile)
    out_dir = os.path.abspath(args.out)
    if os.sep + "captures" + os.sep in out_dir + os.sep:
        ap.error("do not write into captures/")
    for src in args.inputs:
        if os.path.dirname(os.path.abspath(src)) == out_dir:
            ap.error("output folder must not be the source folder: %s" % src)
        for p in process_file(src, profile, out_dir, args.sheet):
            print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
