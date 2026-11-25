"""HFR tone for manual Star AF (REQ-F24): smaller star = higher tone; words say sharper, softer, at best."""
import json
import re
import subprocess
import unittest
from pathlib import Path

from omcap import server

HTML = Path(server.__file__).with_name("web") / "index.html"
HAVE_JS = Path("/usr/bin/osascript").exists()


def js(expr):
    h = HTML.read_text(encoding="utf-8")
    funcs = [re.search(r"^const median=.*$", h, re.M).group(0), re.search(r"^function starFreq.*$", h, re.M).group(0),
             h[h.index("function starTrendOf"):h.index("function starAidReset")]]
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", "\n".join(funcs) + "\nJSON.stringify(%s)" % expr],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip())


@unittest.skipUnless(HAVE_JS, "needs the JavaScript engine of macOS (osascript)")
class StarTone(unittest.TestCase):
    def test_smaller_star_sounds_higher_within_limits(self):
        f = js("[0.5,1,2,4,8,100].map(starFreq)")
        self.assertEqual(f[0], f[1])
        self.assertEqual(sorted(f[1:], reverse=True), f[1:])
        self.assertEqual((f[1], f[-1]), (1760, 220))

    def test_trend_words(self):
        r = js("[starTrendOf([5,5,5,4,4,4],4,5), starTrendOf([4,4,4,5,5,5],4,5),"
               " starTrendOf([5,4,3,2,2,2],2,5), starTrendOf([3,3,3,3,3,3],3,3), starTrendOf([3,3],3,3)]")
        # 'at best' only after a clearly softer value was seen
        self.assertEqual(r, ["sharper", "softer", "atBest", "", ""])


class StarToneControls(unittest.TestCase):
    def test_switch_and_words_are_on_the_page(self):
        h = HTML.read_text(encoding="utf-8")
        for needle in ('id="starTone"', 'id="starTrend"', '"star.atBest"', "starAid(res.saturated?null:res.hfr)"):
            self.assertIn(needle, h)


if __name__ == "__main__":
    unittest.main()
