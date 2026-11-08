"""Tests fuer omcap.hsl mit synthetischen Bildern (keine Fotos)."""
import os
import tempfile
import unittest

import numpy as np

from omcap import hsl


def patch(rgb):
    return np.array([[list(rgb)]], dtype=np.float64)


def prof(**kw):
    p = hsl.neutral_profile()
    for name, vals in kw.items():
        p["sectors"][name].update(vals)
    return p


def lch(rgb):
    L, C, h = hsl.srgb_to_lch(patch(rgb))
    return float(L[0, 0]), float(C[0, 0]), float(h[0, 0])


class HslTests(unittest.TestCase):
    def test_neutral_is_identity(self):
        rng = np.random.RandomState(1)
        img = rng.rand(40, 40, 3)
        out = hsl.apply_hsl(img, hsl.neutral_profile())
        self.assertLess(np.abs(out - img).max(), 1e-6)
        self.assertEqual(out.shape, img.shape)

    def test_greys_unchanged(self):
        g = np.linspace(0, 1, 33)
        img = np.stack([g, g, g], axis=-1)[None]
        p = hsl.set_all(hsl.neutral_profile(), h=7, s=7, l=-7)
        self.assertLess(np.abs(hsl.apply_hsl(img, p) - img).max(), 1e-6)
        p = hsl.load_profile("Teal & orange")
        self.assertLess(np.abs(hsl.apply_hsl(img, p) - img).max(), 1e-6)

    def test_red_hue_shift_direction_blue_untouched(self):
        red, blue = (0.8, 0.1, 0.1), (0.1, 0.2, 0.8)
        p = prof(red={"h": 3})
        r_out = hsl.apply_hsl(patch(red), p)[0, 0]
        b_out = hsl.apply_hsl(patch(blue), p)[0, 0]
        h0, h1 = lch(red)[2], lch(tuple(r_out))[2]
        # positiv = Richtung Rose = fallender LCh-Winkel, ca. 9 Grad
        self.assertLess(h1, h0)
        self.assertAlmostEqual(h0 - h1, 9.0, delta=1.5)
        self.assertLess(np.abs(b_out - np.array(blue)).max(), 1e-4)

    def test_saturation_only_yellow(self):
        yel, blue, red = (0.75, 0.7, 0.4), (0.1, 0.2, 0.8), (0.8, 0.1, 0.1)
        p = prof(yellow={"s": 7})
        c_before = lch(yel)[1]
        c_after = lch(tuple(hsl.apply_hsl(patch(yel), p)[0, 0]))[1]
        self.assertGreater(c_after, c_before * 1.2)
        for other in (blue, red):
            out = hsl.apply_hsl(patch(other), p)[0, 0]
            self.assertLess(np.abs(out - np.array(other)).max(), 1e-4)

    def test_json_round_trip(self):
        p = prof(teal={"h": -2, "s": 5, "l": 7})
        p["name"] = "X"
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "p.json")
            hsl.save_profile(f, p)
            self.assertEqual(hsl.load_profile(f), p)
            sf = os.path.join(d, "slots.json")
            hsl.save_slots(sf, [p, hsl.neutral_profile(), hsl.neutral_profile("C")])
            self.assertEqual(hsl.load_profile(sf), p)
            self.assertEqual(hsl.load_profile(sf + "#3")["name"], "C")
            with self.assertRaises(ValueError):
                hsl.save_slots(sf, [p] * 4)

    def test_presets_load(self):
        for n in ("Neutral", "Warm skin / muted greens", "Teal & orange"):
            self.assertEqual(hsl.load_profile(n)["name"], n)
        with self.assertRaises(ValueError):
            hsl.load_profile("nope")

    def test_range_validation(self):
        for bad in (8, -8, 1.5, "1", True):
            with self.assertRaises(ValueError):
                hsl.validate_profile({"name": "x", "sectors": {"red": {"s": bad}}})
        with self.assertRaises(ValueError):
            hsl.validate_profile({"sectors": {"purple": {"s": 1}}})
        with self.assertRaises(ValueError):
            hsl.set_all(hsl.neutral_profile(), s=9)
        hsl.validate_profile({"sectors": {"red": {"s": 7, "h": -7, "l": 7}}})

    def test_wheel_chart_and_cli(self):
        before, after = hsl.wheel_chart(prof(red={"s": 7}), size=64)
        self.assertEqual(before.shape, (64, 64, 3))
        self.assertGreater(np.abs(before - after).max(), 0.01)
        import imageio.v2 as imageio
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src", "a.jpg")
            os.makedirs(os.path.dirname(src))
            rng = np.random.RandomState(2)
            imageio.imwrite(src, (rng.rand(32, 48, 3) * 255).astype(np.uint8))
            out = os.path.join(d, "o")
            self.assertEqual(hsl.main([src, "--profile", "Teal & orange", "--out", out, "--sheet"]), 0)
            self.assertEqual(sorted(os.listdir(out)),
                             ["a_hsl.jpg", "a_hsl_sheet.jpg", "a_hsl_wheel.jpg"])


if __name__ == "__main__":
    unittest.main()
