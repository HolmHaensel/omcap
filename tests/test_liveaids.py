"""Anzeigehilfen im Livebild: Funktionen und Texte sind in index.html vorhanden (kein node nötig)."""
import re
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "omcap" / "web" / "index.html").read_text(encoding="utf-8")
KEYS = ["lv.hist", "lv.histRgb", "lv.clip", "lv.peak", "lv.peakColor",
        "lv.peakWhite", "lv.peakBlack", "lv.peakRed", "lv.peakYellow"]


class LiveAids(unittest.TestCase):
    def test_functions_exist(self):
        for fn in ("lumaHistogram", "rgbHistogram", "clipMask", "edgeMagnitude", "edgeThreshold"):
            self.assertRegex(HTML, r"function %s\(" % fn)

    def test_i18n_keys_present_and_used(self):
        en = HTML[HTML.index("const I18N={en:{"):HTML.index("const LANG=")]
        for k in KEYS:
            self.assertRegex(en, r'"%s": "' % re.escape(k))
            self.assertIn('data-i18n="%s"' % k, HTML)

    def test_toggles_exist(self):
        for i in ("aidHist", "aidRgb", "aidClip", "aidPeak", "aidPeakCol", "aidCv", "histCv"):
            self.assertIn('id="%s"' % i, HTML)
        self.assertIn("omcap.aids", HTML)


if __name__ == "__main__":
    unittest.main()
