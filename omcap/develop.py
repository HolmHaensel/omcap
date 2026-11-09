"""Develop RAW and merge focus stacks (stage 3).

  python3 -m omcap.develop raw  captures/P1010001.ORF out/P1010001.png
  python3 -m omcap.develop stack out/stack.png captures/*.ORF   # or .JPG

Needs: pip install rawpy numpy opencv-python-headless
Only reads; writes only the given output file.
"""
import argparse
import os
import sys


def _deps():
    try:
        import cv2
        import numpy as np
        import rawpy
    except ImportError as e:
        sys.exit("Fehlt: %s – pip install rawpy numpy opencv-python-headless" % e.name)
    return cv2, np, rawpy


def load(path, cv2, np, rawpy):
    """Returns a 16-bit BGR image."""
    if path.lower().endswith((".orf", ".dng")):
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=16)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        sys.exit("Nicht lesbar: " + path)
    return (img.astype(np.uint16) * 257) if img.dtype == np.uint8 else img


def safe_out(out, inputs):
    if os.path.abspath(out) in {os.path.abspath(i) for i in inputs}:
        sys.exit("Ausgabe darf keine Eingabedatei sein")
    if os.path.exists(out):
        sys.exit("Existiert schon, wird nicht überschrieben: " + out)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)


def align(ref, img, cv2, np):
    """Rough alignment via ECC (focus shift changes the scale slightly)."""
    g1 = cv2.cvtColor((ref >> 8).astype(np.uint8), cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor((img >> 8).astype(np.uint8), cv2.COLOR_BGR2GRAY)
    warp = np.eye(2, 3, dtype=np.float32)
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5)
    try:
        _, warp = cv2.findTransformECC(g1, g2, warp, cv2.MOTION_AFFINE, crit, None, 5)
    except cv2.error:
        return img
    h, w = img.shape[:2]
    return cv2.warpAffine(img, warp, (w, h), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)


def stack(paths):
    cv2, np, rawpy = _deps()
    imgs = [load(paths[0], cv2, np, rawpy)]
    for p in paths[1:]:
        imgs.append(align(imgs[0], load(p, cv2, np, rawpy), cv2, np))
    sharp = []
    for im in imgs:
        g = cv2.cvtColor((im >> 8).astype(np.uint8), cv2.COLOR_BGR2GRAY)
        s = np.abs(cv2.Laplacian(cv2.GaussianBlur(g, (0, 0), 1.0), cv2.CV_32F))
        sharp.append(cv2.GaussianBlur(s, (0, 0), 3.0))
    best = np.argmax(np.stack(sharp), axis=0)
    out = np.zeros_like(imgs[0])
    for i, im in enumerate(imgs):
        out[best == i] = im[best == i]
    return out


def main():
    a = argparse.ArgumentParser()
    sub = a.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("raw")
    r.add_argument("src")
    r.add_argument("out")
    s = sub.add_parser("stack")
    s.add_argument("out")
    s.add_argument("src", nargs="+")
    args = a.parse_args()
    cv2, np, rawpy = _deps()
    if args.cmd == "raw":
        safe_out(args.out, [args.src])
        img = load(args.src, cv2, np, rawpy)
    else:
        if len(args.src) < 2:
            sys.exit("Mindestens 2 Bilder")
        safe_out(args.out, args.src)
        img = stack(sorted(args.src))
    cv2.imwrite(args.out, img)
    print("geschrieben:", args.out)


if __name__ == "__main__":
    main()
