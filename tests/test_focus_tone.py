"""Focus tone (REQ-F59) and silent half press over Wi-Fi: page markup and server logic, no camera."""
import json
import os
import shutil
import subprocess
import unittest

from omcap import camera, server, usb_camera

WEB = os.path.join(os.path.dirname(__file__), "..", "omcap", "web", "index.html")
HAVE_JS = shutil.which("osascript")

STUBS = """
var calls=[],msgs=[],beeps=[],tr=function(k){return k},msg=function(m,e){msgs.push([m,!!e])},
  el=function(){return {value:'',checked:false,hidden:false,textContent:''}},els={},Q=function(s){return els[s]||(els[s]=el())},
  body={cl:{},classList:{toggle:function(c,on){body.cl[c]=!!on}}},document={body:body},
  st={stage:0,live:true,lv_age:0},isUsb=false,canWrite=true,features={has:function(f){return f!=='none'}},
  MOBILE_LIVE={matches:false},wzFocusOnly=false,focusing=false,focusMiss=0,afTapShow=0,FOCUS_SHOW=4000,focusHit=null,af=null,
  wzFocusAction=function(){},focusChipUpdate=function(){},showAf=function(){},drawAf=function(){},showNoFocus=function(){},
  focusField=function(a){return a&&a.hit?3:null},lvlBeep=function(f,l,w){beeps.push(f)},setTimeout=function(){},
  api=function(p,b){calls.push(p);return {hit:true}},wzSizingEnabled=function(){return !isUsb&&canWrite};
"""


def fn(h, name):
    """Source of one top-level function, found by brace matching."""
    a = h.index("function %s(" % name)
    if h[a - 6:a] == "async ":
        a -= 6
    d, i = 0, h.index("{", a)
    while True:
        d += h[i] == "{"
        d -= h[i] == "}"
        i += 1
        if d == 0:
            return h[a:i]


def run_js(scenario, names, pre=""):
    with open(WEB, encoding="utf-8") as f:
        h = f.read()
    code = (STUBS + pre + "\n".join(fn(h, n) for n in names).replace("await ", "") + "\n" + scenario).replace("$(", "Q(")  # JXA owns $
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip())


class FakeCam:
    def __init__(self, full):
        self.stage, self.released_full, self._full, self.pressed = 1, False, full, []

    def press(self, stage):
        self.pressed.append(stage)
        self.released_full = self._full
        self.stage = 0


class Page(unittest.TestCase):
    def setUp(self):
        self.html = open(WEB, encoding="utf-8").read()

    def test_switch_gated_and_remembered(self):
        self.assertIn('data-feat="focus_tone"', self.html)
        self.assertIn('id="focusTone"', self.html)
        self.assertIn("'lvlSound','focusTone']", self.html)  # saved with the other switches
        self.assertIn('"lv.focusTone": "Focus tone"', self.html)
        self.assertIn('"lv.focusToneHint"', self.html)

    def test_tone_after_tap_focus_only(self):
        self.assertIn("if(f) focusTone(!!hit);", self.html)
        self.assertIn("features.has('focus_tone')", self.html)
        self.assertEqual(self.html.count("focusTone("), 2)  # definition and the one call in setAf

    def test_wifi_only(self):
        self.assertIn("focus_tone", server.WIFI_FEATURES)
        self.assertNotIn("focus_tone", usb_camera.FEATURES)


class HalfPress(unittest.TestCase):
    def setUp(self):
        self.saved = (server.cam, server.conn_type, dict(server.state), server.pull_new)
        self.pulled = []
        server.pull_new = lambda seen: self.pulled.append(seen)
        server.conn_type = "wifi"
        server.state["seen"] = {"a"}
        server.state["resume_live"] = False

    def tearDown(self):
        server.cam, server.conn_type, st, server.pull_new = self.saved
        server.state.clear()
        server.state.update(st)

    def test_half_press_without_shot_does_not_pull(self):
        server.cam = FakeCam(full=False)
        server.Handler._shutter(None, 0)
        self.assertEqual(self.pulled, [])
        self.assertIsNone(server.state["seen"])

    def test_real_shot_pulls(self):
        server.cam = FakeCam(full=True)
        server.Handler._shutter(None, 0)
        self.assertEqual(self.pulled, [{"a"}])

    def test_release_flag_in_camera(self):
        c = camera.Camera.__new__(camera.Camera)
        c.stage, c.released_full = 1, True
        c.shutter = lambda step: None
        c.set_mode = lambda m: None
        c._release()
        self.assertFalse(c.released_full)
        c.stage = 2
        camera.time.sleep, old = lambda s: None, camera.time.sleep
        try:
            c._release()
        finally:
            camera.time.sleep = old
        self.assertTrue(c.released_full)


@unittest.skipUnless(HAVE_JS, "needs osascript (JavaScriptCore)")
class Behaviour(unittest.TestCase):
    """The page functions run with stubbed camera and page; these fail when the code is changed back."""

    def label(self, mobile, usb=False, size="0800x0600"):
        return run_js(
            "MOBILE_LIVE.matches=%s; isUsb=%s; $('#lvAuto').checked=true; autoLvLabel('%s');"
            "JSON.stringify({cls:body.cl.autoLv,sel:$('#lvqty').value,chip:$('#autoLvStatus').hidden})"
            % (str(mobile).lower(), str(usb).lower(), size),
            ["autoLvLabel"],
            "var autoLvEnabled=function(){return (MOBILE_LIVE.matches||$('#lvAuto').checked)&&wzSizingEnabled()},"
            "lvSizeText=function(s){return s};",
        )

    def test_phone_hides_the_size_choice(self):
        r = self.label(True)
        self.assertTrue(r["cls"])  # body.autoLv hides the Size select and the Auto box in CSS
        self.assertEqual(r["sel"], "0800x0600")
        self.assertFalse(r["chip"])

    def test_computer_keeps_the_size_choice(self):
        self.assertFalse(self.label(False)["cls"])

    def test_tap_af_refused_while_halfway_is_held_over_wifi(self):
        r = run_js("st.stage=1; setAf({field:5}); JSON.stringify({calls:calls,msgs:msgs})", ["setAf"])
        self.assertEqual(r["calls"], [])
        self.assertEqual(r["msgs"], [["msg.halfHeld", True]])

    def test_tap_af_goes_through_over_usb_or_without_halfway(self):
        for usb, stage in (("true", 1), ("false", 0)):
            r = run_js("isUsb=%s; st.stage=%d; setAf({field:5}); JSON.stringify({calls:calls,msgs:msgs})" % (usb, stage), ["setAf", "focusTone"])
            self.assertEqual(r["calls"], ["/api/afarea"], (usb, stage))
            self.assertNotIn(["msg.halfHeld", True], r["msgs"])

    def test_tone_high_in_focus_low_without(self):
        r = run_js("focusTone(true); focusTone(false); JSON.stringify(beeps)", ["focusTone"], "$('#focusTone').checked=true;")
        self.assertEqual(r, [1760, 330])

    def test_no_tone_when_switch_off_or_feature_missing(self):
        self.assertEqual(run_js("focusTone(true); JSON.stringify(beeps)", ["focusTone"]), [])
        r = run_js("features={has:function(){return false}}; focusTone(true); JSON.stringify(beeps)", ["focusTone"], "$('#focusTone').checked=true;")
        self.assertEqual(r, [])

    def test_tap_af_plays_the_tone_through_setAf(self):
        r = run_js("setAf({field:5}); JSON.stringify(beeps)", ["setAf", "focusTone"], "$('#focusTone').checked=true;")
        self.assertEqual(r, [1760])


class HalfPaused(unittest.TestCase):
    def setUp(self):
        with open(WEB, encoding="utf-8") as f:
            self.h = f.read()

    @unittest.skipUnless(HAVE_JS, "needs osascript (JavaScriptCore)")
    def test_paused_instead_of_no_signal(self):
        # Take the two statements from tick() and run them for several states
        line = next(l for l in self.h.splitlines() if l.lstrip().startswith("const w=$('#live').naturalWidth, paused="))
        expr = line.split("const w=$('#live').naturalWidth, ", 1)[1].split(";")[0]
        code = STUBS + "var out=[];[[false,1,0],[false,0,9],[false,1,9],[true,1,9],[false,1,2]].forEach(function(c){isUsb=c[0];st.live=true;st.stage=c[1];st.lv_age=c[2];var %s;out.push([paused,stale])});JSON.stringify(out)" % expr
        out = subprocess.run(["osascript", "-l", "JavaScript", "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(
            json.loads(out.stdout.strip()),
            [[True, False], [False, True], [True, False], [False, True], [True, False]],
        )
        self.assertIn("paused?tr('lv.halfPaused')", self.h)  # shown in place of the No signal text


if __name__ == "__main__":
    unittest.main()
