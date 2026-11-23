"""Star AF: star sharpness (HFR) measurement and USB automatic V-curve focus (REQ-F24).

Measures Half-Flux Radius (HFR, flux-weighted mean radius in pixels; smaller = sharper)
from live view JPEG frames, rejecting single-pixel hot pixels via a 3x3 box average.
Over USB (with MF / S-AF+MF and OMD_MFDrive 0x9487) AutoStarAF runs a two-pass
coarse-to-fine V-curve sweep with backlash compensation to find the sharpest focus.
"""
import io
import time


def _image_deps():
    try:
        import numpy as np
    except ImportError as e:
        raise ValueError("Star AF needs numpy (pip install numpy): %s" % e)
    try:
        from PIL import Image
        return np, ("pil", Image)
    except ImportError:
        try:
            import imageio.v2 as imageio
            return np, ("imageio", imageio)
        except ImportError as e:
            raise ValueError("Star AF needs Pillow or imageio (pip install pillow): %s" % e)


def decode_luma(jpeg_bytes):
    """Decode JPEG bytes into a 2D float32 luminance array (0..255)."""
    if not jpeg_bytes:
        raise ValueError("Empty live view frame")
    np, (kind, mod) = _image_deps()
    if kind == "pil":
        with mod.open(io.BytesIO(jpeg_bytes)) as im:
            arr = np.asarray(im.convert("L"), dtype=np.float32)
        return arr
    arr = np.asarray(mod.imread(io.BytesIO(jpeg_bytes)), dtype=np.float32)
    if arr.ndim == 3:
        arr = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    return arr


BRIGHT_BG_LIMIT = 180.0  # OM-1 II manual p.102: Starry Sky AF cannot focus in bright/daylight scenes
PRIORITIES = {  # AF Priority (OM-1 II manual p.119): (frames_per_step, settle_s)
    "speed": (2, 0.25),
    "accuracy": (4, 0.45),  # tripod + slower Live View Boost On2 (E-M1 manual p.176)
}


def measure_star(luma, cx=None, cy=None, box=96, aperture=18):
    """Find the brightest non-hotpixel star near (cx, cy) and compute its Half-Flux Radius (HFR).

    luma: 2D array (H x W), values 0..255.
    cx, cy: optional normalised search centre (0..1); defaults to the image centre (0.5, 0.5).
    Returns dict: {"found": bool, "hfr": float, "peak": float, "snr": float, "x": float, "y": float, ...}.
    """
    import numpy as np

    img = np.asarray(luma, dtype=np.float32)
    if img.ndim != 2 or img.shape[0] < 9 or img.shape[1] < 9:
        return {"found": False, "reason": "Frame too small"}
    h, w = img.shape
    px = int(round((0.5 if cx is None else max(0.0, min(1.0, float(cx)))) * (w - 1)))
    py = int(round((0.5 if cy is None else max(0.0, min(1.0, float(cy)))) * (h - 1)))

    half = max(12, min(int(box), h // 2, w // 2))
    x0, x1 = max(0, px - half), min(w, px + half)
    y0, y1 = max(0, py - half), min(h, py + half)
    roi = img[y0:y1, x0:x1]
    if roi.shape[0] < 7 or roi.shape[1] < 7:
        return {"found": False, "reason": "Search area too small"}

    bg = float(np.median(roi))
    mad = float(np.median(np.abs(roi - bg)))
    sigma = max(1.4826 * mad, 1.0)

    # 3x3 box mean suppresses isolated 1-pixel hot pixels (~9x drop) while keeping real star PSFs.
    # Search inside an inner margin so the aperture around the peak never underflows the ROI border.
    smooth = (
        roi[:-2, :-2] + roi[:-2, 1:-1] + roi[:-2, 2:]
        + roi[1:-1, :-2] + roi[1:-1, 1:-1] + roi[1:-1, 2:]
        + roi[2:, :-2] + roi[2:, 1:-1] + roi[2:, 2:]
    ) / 9.0
    margin = 3 if smooth.shape[0] > 8 and smooth.shape[1] > 8 else 0
    inner = smooth[margin:smooth.shape[0] - margin, margin:smooth.shape[1] - margin] if margin else smooth
    idx = int(np.argmax(inner))
    sy_in, sx_in = divmod(idx, inner.shape[1])
    sy_rel, sx_rel = sy_in + margin, sx_in + margin
    sx_roi, sy_roi = sx_rel + 1, sy_rel + 1

    smooth_peak = float(smooth[sy_rel, sx_rel]) - bg
    raw_peak = float(roi[sy_roi, sx_roi]) - bg
    snr = smooth_peak / sigma
    if smooth_peak < 8.0 or raw_peak < 12.0 or snr < 3.5:
        bright = bg >= BRIGHT_BG_LIMIT
        out = {"found": False, "bg": round(bg, 1), "noise": round(sigma, 2), "snr": round(snr, 1), "bright": bright}
        if bright:
            out["reason"] = "Too bright for Star AF"
        return out

    ap = min(int(aperture), sx_roi, sy_roi, roi.shape[1] - 1 - sx_roi, roi.shape[0] - 1 - sy_roi)
    if ap < 3:
        return {"found": False, "reason": "Star too close to edge"}

    patch = roi[sy_roi - ap:sy_roi + ap + 1, sx_roi - ap:sx_roi + ap + 1]
    if patch.shape[0] < 3 or patch.shape[1] < 3:
        return {"found": False, "reason": "Star too close to edge"}
    # Local annulus background around the aperture improves HFR accuracy on uneven sky gradients
    border = np.concatenate([patch[0, :], patch[-1, :], patch[1:-1, 0], patch[1:-1, -1]])
    local_bg = float(np.median(border))
    flux_map = np.maximum(patch - local_bg, 0.0)
    total_flux = float(flux_map.sum())
    if total_flux <= 1.0:
        return {"found": False, "bg": round(local_bg, 1), "noise": round(sigma, 2), "snr": round(snr, 1)}

    yy, xx = np.mgrid[-ap:ap + 1, -ap:ap + 1]
    dx = float((flux_map * xx).sum() / total_flux)
    dy = float((flux_map * yy).sum() / total_flux)
    r = np.hypot(xx - dx, yy - dy)
    hfr = float((flux_map * r).sum() / total_flux)

    star_x = (x0 + sx_roi + dx) / float(w)
    star_y = (y0 + sy_roi + dy) / float(h)
    return {
        "found": True,
        "hfr": round(hfr, 2),
        "peak": round(raw_peak, 1),
        "snr": round(snr, 1),
        "bg": round(local_bg, 1),
        "saturated": float(roi[sy_roi - 1:sy_roi + 2, sx_roi - 1:sx_roi + 2].max()) >= 250.0,
        "x": round(max(0.0, min(1.0, star_x)), 4),
        "y": round(max(0.0, min(1.0, star_y)), 4),
    }


MFT_COC_MM = 0.015  # Micro Four Thirds circle of confusion (17.3 x 13.0 mm sensor)


def hyperfocal_m(focal_mm, f_number, coc_mm=MFT_COC_MM):
    """Hyperfocal distance in metres and near-sharp limit (H/2) for Micro Four Thirds, else None."""
    try:
        f = float(focal_mm)
        n = float(f_number)
    except (TypeError, ValueError):
        return None
    if f <= 0 or n <= 0 or coc_mm <= 0:
        return None
    h_m = (f * f / (n * coc_mm) + f) / 1000.0
    return {"hyperfocal_m": round(h_m, 2), "near_m": round(h_m / 2.0, 2)}


def _dilate_mask(mask, radius):
    """Return boolean mask True wherever any True pixel lies within Chebyshev distance <= radius."""
    import numpy as np

    if not mask.any() or radius <= 0:
        return mask.copy()
    h, w = mask.shape
    r = int(radius)
    padded = np.pad(mask.astype(np.int32), r, mode="constant", constant_values=0)
    cs = np.zeros((h + 2 * r + 1, w + 2 * r + 1), dtype=np.int32)
    cs[1:, 1:] = padded.cumsum(axis=0).cumsum(axis=1)
    k = 2 * r + 1
    box_sum = cs[k:, k:] - cs[:-k, k:] - cs[k:, :-k] + cs[:-k, :-k]
    return box_sum > 0


def _local_max_mask(arr, radius=2):
    """Boolean mask of pixels that are >= every neighbour within Chebyshev distance <= radius."""
    import numpy as np

    h, w = arr.shape
    r = int(radius)
    p = np.pad(arr, r, mode="constant", constant_values=-np.inf)
    k = 2 * r + 1
    hmax = np.maximum.reduce([p[:, i:i + w] for i in range(k)])
    vmax = np.maximum.reduce([hmax[i:i + h, :] for i in range(k)])
    return arr >= vmax


def find_brightest_star(luma, margin=24):
    """Scan the full frame for the brightest star, preferring non-saturated stars over clipped beacons.

    margin: border pixels excluded so Zoom AF x10 stays inside the camera's 10-90 % crop limits.
    Returns {"found": True, "x": 0..1, "y": 0..1, "peak": ..., "snr": ..., "saturated": bool} or {"found": False}.
    """
    import numpy as np

    img = np.asarray(luma, dtype=np.float32)
    if img.ndim != 2 or img.shape[0] < 16 or img.shape[1] < 16:
        return {"found": False}
    h, w = img.shape
    m = max(4, min(int(margin), h // 6, w // 6))
    roi = img[m:h - m, m:w - m]
    bg = float(np.median(roi))
    mad = float(np.median(np.abs(roi - bg)))
    sigma = max(1.4826 * mad, 1.0)

    # 3x3 mean rejects isolated 1-pixel hot pixels
    smooth = (
        roi[:-2, :-2] + roi[:-2, 1:-1] + roi[:-2, 2:]
        + roi[1:-1, :-2] + roi[1:-1, 1:-1] + roi[1:-1, 2:]
        + roi[2:, :-2] + roi[2:, 1:-1] + roi[2:, 2:]
    ) / 9.0
    center = roi[1:-1, 1:-1]

    # Exclude saturated cores and their halo (both by local-max check and an exclusion radius around >= 250)
    sat_core = center >= 250.0
    sat3 = _dilate_mask(sat_core, 1)
    near_sat = _dilate_mask(sat_core, 10)
    is_peak = _local_max_mask(smooth, 2)

    # Prefer bright unsaturated star peaks so HFR is not distorted by flat-topped clipping
    unsat = np.where(is_peak & ~near_sat, smooth, -1.0)
    idx = int(np.argmax(unsat))
    sy_rel, sx_rel = divmod(idx, smooth.shape[1])
    use_val = float(unsat[sy_rel, sx_rel])
    if use_val - bg < 8.0 or float(center[sy_rel, sx_rel]) - bg < 12.0 or (use_val - bg) / sigma < 3.5:
        idx = int(np.argmax(smooth))
        sy_rel, sx_rel = divmod(idx, smooth.shape[1])
        use_val = float(smooth[sy_rel, sx_rel])

    smooth_peak = use_val - bg
    raw_peak = float(center[sy_rel, sx_rel]) - bg
    snr = smooth_peak / sigma
    if smooth_peak < 8.0 or raw_peak < 12.0 or snr < 3.5:
        bright = bg >= BRIGHT_BG_LIMIT
        out = {"found": False, "bg": round(bg, 1), "noise": round(sigma, 2), "snr": round(snr, 1), "bright": bright}
        if bright:
            out["reason"] = "Too bright for Star AF"
        return out

    sx = m + sx_rel + 1
    sy = m + sy_rel + 1
    return {
        "found": True,
        "x": round(sx / float(w), 4),
        "y": round(sy / float(h), 4),
        "peak": round(raw_peak, 1),
        "snr": round(snr, 1),
        "saturated": bool(sat3[sy_rel, sx_rel]),
    }


def find_brightest_star_jpeg(jpeg_bytes, margin=24):
    return find_brightest_star(decode_luma(jpeg_bytes), margin=margin)


def measure_jpeg(jpeg_bytes, cx=None, cy=None, box=96, aperture=18):
    return measure_star(decode_luma(jpeg_bytes), cx=cx, cy=cy, box=box, aperture=aperture)


def measure_frames(frames, cx=None, cy=None, box=96, aperture=18):
    """Measure multiple frames and return the median HFR result to suppress seeing and noise."""
    hits = []
    last = {"found": False}
    for frame in frames:
        m = measure_jpeg(frame, cx=cx, cy=cy, box=box, aperture=aperture) if isinstance(frame, (bytes, bytearray)) \
            else measure_star(frame, cx=cx, cy=cy, box=box, aperture=aperture)
        last = m
        if m.get("found"):
            hits.append(m)
    if not hits:
        return last
    hits.sort(key=lambda m: m["hfr"])
    return hits[len(hits) // 2]


class AutoStarAF:
    """Two-pass V-curve Star AF using USB MFDrive (0x9487): coarse (step 2) then fine (step 1).

    Backlash compensation: every final move to a target position approaches from the same
    direction (overshoot 1 step near, then step back far).
    """

    def __init__(
        self,
        drive_fn,
        grab_fn,
        stop_event,
        on_progress=None,
        cx=0.5,
        cy=0.5,
        coarse_step=2,
        fine_step=1,
        max_coarse=8,
        fine_span=5,
        frames_per_step=2,
        settle_s=0.22,
    ):
        self.drive_fn = drive_fn
        self.grab_fn = grab_fn
        self.stop_event = stop_event
        self.on_progress = on_progress
        self.cx = cx
        self.cy = cy
        self.coarse_step = coarse_step
        self.fine_step = fine_step
        self.max_coarse = max_coarse
        self.fine_span = fine_span
        self.frames_per_step = max(1, int(frames_per_step))
        self.settle_s = settle_s
        self.samples = []
        self.start_hfr = None
        self.best_hfr = None
        self.current_hfr = None
        self.saturated = False

    def _emit(self, phase, message, step=0):
        if self.on_progress:
            self.on_progress({
                "phase": phase,
                "message": message,
                "step": step,
                "hfr": self.current_hfr,
                "best_hfr": self.best_hfr,
                "start_hfr": self.start_hfr,
                "saturated": self.saturated,
                "samples": list(self.samples[-30:]),
            })

    def _stopped(self):
        return bool(self.stop_event and self.stop_event.is_set())

    def _drive(self, direction, step):
        if self._stopped():
            return False
        self.drive_fn(direction, step)
        if self.settle_s > 0:
            if self.stop_event:
                if self.stop_event.wait(self.settle_s):
                    return False
            else:
                time.sleep(self.settle_s)
        return not self._stopped()

    def _measure(self, pos, stage):
        frames = []
        for _ in range(self.frames_per_step):
            if self._stopped():
                return None
            f = self.grab_fn()
            if f is not None:
                frames.append(f)
        if not frames:
            return {"found": False}
        m = measure_frames(frames, cx=self.cx, cy=self.cy)
        if m.get("found"):
            self.current_hfr = m["hfr"]
            self.saturated = bool(m.get("saturated"))
            if self.start_hfr is None:
                self.start_hfr = m["hfr"]
            if self.best_hfr is None or m["hfr"] < self.best_hfr:
                self.best_hfr = m["hfr"]
            self.samples.append({"pos": pos, "hfr": m["hfr"], "pass": stage})
        return m

    def _move_steps(self, delta, step_size, backlash=False):
        """Move `delta` steps (+ = far, - = near) at `step_size`, optionally ending with a 'far' approach."""
        if delta == 0:
            return True
        if backlash and delta < 0:
            # Overshoot 1 step further near, then approach from the 'far' direction
            for _ in range(abs(delta) + 1):
                if not self._drive("near", step_size):
                    return False
            return self._drive("far", step_size)
        direction = "far" if delta > 0 else "near"
        for _ in range(abs(delta)):
            if not self._drive(direction, step_size):
                return False
        return True

    def run(self):
        """Run coarse + fine V-curve focus. Returns final summary dict."""
        step_n = 0
        self._emit("coarse", "Measuring star…", step_n)
        m0 = self._measure(0, "coarse")
        if self._stopped():
            return self._finish("stopped", "Star AF stopped")
        if not m0 or not m0.get("found"):
            if m0 and m0.get("bright"):
                return self._finish("error", "Too bright for Star AF (use in dark sky / night).")
            return self._finish("error", "No star found near the centre. Aim at a bright star or LED first.")

        # --- Pass 1: coarse search ---
        pos = 0
        best_pos, best_hfr = 0, m0["hfr"]
        self._emit("coarse", "Coarse search (HFR %.2f px)…" % best_hfr, step_n)

        # Probe one step 'far' to pick the improving direction
        if not self._drive("far", self.coarse_step):
            return self._finish("stopped", "Star AF stopped")
        pos += 1
        step_n += 1
        m1 = self._measure(pos, "coarse")
        if self._stopped():
            return self._finish("stopped", "Star AF stopped")

        if m1 and m1.get("found") and m1["hfr"] < best_hfr:
            direction, sign = "far", 1
            best_pos, best_hfr = pos, m1["hfr"]
        else:
            # 'far' did not improve: reverse past 0 to 'near'
            direction, sign = "near", -1
            if not self._drive("near", self.coarse_step):
                return self._finish("stopped", "Star AF stopped")
            pos -= 1

        worse = 0
        for _ in range(self.max_coarse):
            if not self._drive(direction, self.coarse_step):
                return self._finish("stopped", "Star AF stopped")
            pos += sign
            step_n += 1
            m = self._measure(pos, "coarse")
            if self._stopped():
                return self._finish("stopped", "Star AF stopped")
            if m and m.get("found"):
                if m["hfr"] < best_hfr - 0.05:
                    best_pos, best_hfr = pos, m["hfr"]
                    worse = 0
                else:
                    worse += 1
                self._emit("coarse", "Coarse search (HFR %.2f px, best %.2f px)…" % (m["hfr"], best_hfr), step_n)
                if worse >= 2:
                    break
            else:
                worse += 1
                if worse >= 2:
                    break

        # Return to the coarse minimum (with backlash compensation)
        self._emit("returning", "Returning to coarse focus…", step_n)
        if not self._move_steps(best_pos - pos, self.coarse_step, backlash=True):
            return self._finish("stopped", "Star AF stopped")

        # --- Pass 2: fine sweep around the coarse minimum ---
        half_fine = max(1, self.fine_span // 2)
        self._emit("fine", "Fine search…", step_n)
        if not self._move_steps(-half_fine, self.fine_step, backlash=True):
            return self._finish("stopped", "Star AF stopped")

        fpos = -half_fine
        fine_best_pos, fine_best_hfr = fpos, None
        for i in range(self.fine_span):
            if i > 0:
                if not self._drive("far", self.fine_step):
                    return self._finish("stopped", "Star AF stopped")
                fpos += 1
                step_n += 1
            m = self._measure(fpos, "fine")
            if self._stopped():
                return self._finish("stopped", "Star AF stopped")
            if m and m.get("found"):
                if fine_best_hfr is None or m["hfr"] < fine_best_hfr:
                    fine_best_pos, fine_best_hfr = fpos, m["hfr"]
                self._emit("fine", "Fine search (HFR %.2f px, best %.2f px)…" % (m["hfr"], fine_best_hfr), step_n)

        if fine_best_hfr is None:
            return self._finish("error", "Lost the star during fine search.")

        # Return to finest HFR minimum with backlash compensation
        self._emit("returning", "Setting best focus…", step_n)
        if not self._move_steps(fine_best_pos - fpos, self.fine_step, backlash=True):
            return self._finish("stopped", "Star AF stopped")

        final = self._measure(fine_best_pos, "final")
        final_hfr = final["hfr"] if (final and final.get("found")) else fine_best_hfr
        sat_note = " (star clipped – try a dimmer star)" if self.saturated else ""
        return self._finish("done", "Focused · HFR %.2f px (start %.2f px)%s" % (final_hfr, self.start_hfr, sat_note))

    def _finish(self, phase, message):
        out = {
            "phase": phase,
            "message": message,
            "hfr": self.current_hfr,
            "best_hfr": self.best_hfr,
            "start_hfr": self.start_hfr,
            "saturated": self.saturated,
            "samples": list(self.samples[-30:]),
        }
        if self.on_progress:
            self.on_progress(out)
        return out
