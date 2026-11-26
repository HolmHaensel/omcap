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
             h[h.index("function starTrendOf"):h.index("function starAid(hfr)")],
             "var starHist=[],starPassed=false,starSmBest=null,starMiss=0,starSeen='',starCalm=0,starWord='';"
             "var el={textContent:''};function $(){return el}",
             "function run(a){starAidReset();return a.map(function(h){starStep(h);return starWord})}"]
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", "(function(){\n%s\nreturn JSON.stringify(%s)})()" % ("\n".join(funcs), expr)],
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
        r = js("[starTrendOf([5,5,5,4,4,4],4,false), starTrendOf([4,4,4,5,5,5],4,false),"
               " starTrendOf([5,4,3,2,2,2],2,true), starTrendOf([5,4,3,2,2,2],2,false), starTrendOf([3,3],3,true)]")
        # 'at best' only after going past it
        self.assertEqual(r, ["sharper", "softer", "atBest", "sharper", ""])

    def test_flickering_star_at_rest_says_nothing(self):
        r = js("run([3,3.2,2.85,3.1,2.9,3.15,2.95,3.05,2.8,3.2,3,2.9,3.1,3,2.85,3.15])")
        self.assertEqual(set(r), {""})

    def test_noisy_sweep_past_the_best_and_back(self):
        sweep = ("[6,6.2,5.8,5,4.6,4,3.4,3,2.5,2.1,2.0,1.9,2.1,"  # towards the best
                 "2.6,3.0,3.5,3.4,3.6,"                             # past it
                 "3.0,2.5,2.1,2.0,null,2.0,2.1,2.0]")              # back, with one lost frame
        r = js("run(%s)" % sweep)
        self.assertNotIn("atBest", r[:13])  # not while still approaching
        words = [w for i, w in enumerate(r) if w and w != r[i - 1]]
        self.assertEqual(words[:2], ["sharper", "softer"])
        self.assertEqual(r[-1], "atBest")

    def test_three_lost_frames_reset(self):
        self.assertEqual(js("(run([6,5,4,3,2,2,2,2,null,null,null]),[starHist.length,starWord])"), [0, ""])


if __name__ == "__main__":
    unittest.main()
