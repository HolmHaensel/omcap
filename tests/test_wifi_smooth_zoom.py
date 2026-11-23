"""Wi-Fi screen zoom (REQ-F55): smooth zoom about the pointer, 1x-4x, overview map, no camera command.

The page code runs in JavaScriptCore (osascript) with a stubbed viewport; no camera, no server."""
import json
import os
import re
import shutil
import subprocess
import unittest

from tests.web_path import HTML_PATH as HTML
HAVE_JS = shutil.which("osascript")

STUBS = """
var calls=[],usbZoom=false,z=1,px=0,py=0,drag=null,intervals=0,
  calm={matches:true},setInterval=function(){intervals++;return 7},clearInterval=function(){},
  el=function(){return {style:{},hidden:false,naturalWidth:0,classList:{_s:{},toggle:function(c,on){this._s[c]=on===undefined?!this._s[c]:!!on},
    contains:function(c){return !!this._s[c]},add:function(c){this._s[c]=true},remove:function(c){delete this._s[c]}}}},
  els={},Q=function(s){return els[s]||(els[s]=el())},document={querySelectorAll:function(){return []},createElement:function(){return {getContext:function(){return {drawImage:function(){}}},toDataURL:function(){return ''}}}},
  vp=Q('vp'),layer=Q('layer'),zMap={getBoundingClientRect:function(){return {left:10,top:410,width:160,height:120}}},
  api=function(p){calls.push(p)},fetch=function(p){calls.push(p)};
vp.getBoundingClientRect=function(){return {width:800,height:600,left:0,top:0}};
var zMeasure=function(){return vp.getBoundingClientRect()},zBox=zMeasure;
"""


STUBS_FULL = """
var AUTO_LV_SLOW_MS=4000,AUTO_LV_SIZES=['0640x0480','0800x0600','1024x0768','1280x0960'],timers=[],picks=0,loupeOn=false,zBlock=false,lvPicked=false,autoLvBusy=false,autoLvLastChange=0,autoLvSlowSince=0,
  st={live:true,lvqty:'0640x0480',job:{}},enabled=true,sizing=true,ideal='0800x0600',labels=[],msgs=[],
  tr=function(k){return k},msg=function(m){msgs.push(m)},
  autoLvEnabled=function(){return enabled},wzSizingEnabled=function(){return sizing},idealMobileLvSize=function(){return ideal},autoLvLabel=function(s){labels.push(s)},
  loupePtrEnd=function(){return false},pickField=function(){picks++},
  setTimeout=function(f,ms){timers.push([f,ms]);return timers.length},clearTimeout=function(){};
Q('#lvStart').onclick=function(){calls.push('start '+Q('#lvqty').value)};
var ev=function(id,x,y){return {pointerId:id,clientX:x,clientY:y,target:{closest:function(){return null}},preventDefault:function(){}}};
vp.setPointerCapture=function(){};vp.addEventListener=function(){};
"""


def page_js(scenario, full=False):
    with open(HTML, encoding="utf-8") as f:
        h = f.read()
    maths = h[h.index("// zoom maths (pure"):h.index("// zoom maths end")]
    wz = h[h.index("// Wi-Fi screen zoom (REQ-F55)"):h.index("function setZoom(")]
    wz += h[h.index("// Wi-Fi: a click or drag in the map"):].split("\n")[1] + "\n"  # wzMapMove
    if full:  # the handlers and the live view size code as well
        wz = h[h.index("// Wi-Fi screen zoom (REQ-F55)"):h.index("/* Zoom AF over USB (REQ-F53")]
        wz += h[h.index("function lvSlowNow"):h.index("async function tick")]
        wz = wz.replace("async function reduceAutoLiveSize", "function reduceAutoLiveSize").replace("await ", "")
    code = "%s\n%s\n%s\n%s\n%s" % (STUBS, STUBS_FULL, maths, wz.replace("$(", "Q("), scenario)
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip())


class Markup(unittest.TestCase):
    def setUp(self):
        with open(HTML, encoding="utf-8") as f:
            self.h = f.read()

    def test_scale_limit_is_one_constant_with_its_reason(self):
        self.assertIn("const WZ_MAX=4", self.h)

    def test_usb_wheel_limit_unchanged(self):
        self.assertIn("const zWheelScale=(s,dy,mode,max=14)=>", self.h)
        self.assertIn("zWheelScale(V.s,e.deltaY,e.deltaMode)", self.h)  # the USB call keeps the default 14

    def test_no_camera_request_in_the_screen_zoom(self):
        a = self.h.index("// Wi-Fi screen zoom (REQ-F55)")
        block = self.h[a:self.h.index("function setZoom(")]
        self.assertNotIn("/api/", block)
        self.assertNotIn("api(", block)

    def test_overlays_stay_with_the_zoom(self):
        self.assertNotIn("classList.toggle('loupe'", self.h[self.h.index("function wzUi("):self.h.index("function setZoom(")])


@unittest.skipUnless(HAVE_JS, "needs the JavaScript engine of macOS (osascript)")
class ScreenZoom(unittest.TestCase):
    def test_wheel_keeps_the_point_under_the_pointer(self):
        r = page_js("""
        var before=zPic(wzView(),200/800,150/600);
        wzAt(200,150,zWheelScale(z,-100,0,WZ_MAX));
        var after=zPic(wzView(),200/800,150/600);
        JSON.stringify({z:z,before:before,after:after})""")
        self.assertGreater(r["z"], 1.2)
        self.assertAlmostEqual(r["before"]["x"], r["after"]["x"], places=6)
        self.assertAlmostEqual(r["before"]["y"], r["after"]["y"], places=6)

    def test_point_stays_over_a_whole_gesture_away_from_the_edge(self):
        r = page_js("""
        wzAt(400,300,2);
        var p=zPic(wzView(),500/800,350/600);
        for(var i=0;i<5;i++) wzAt(500,350,zWheelScale(z,-30,0,WZ_MAX));
        JSON.stringify({p:p,q:zPic(wzView(),500/800,350/600),z:z})""")
        self.assertGreater(r["z"], 2)
        self.assertAlmostEqual(r["p"]["x"], r["q"]["x"], places=6)
        self.assertAlmostEqual(r["p"]["y"], r["q"]["y"], places=6)

    def test_scale_is_clamped_to_1_and_4_and_the_view_stays_in_the_picture(self):
        r = page_js("""
        for(var i=0;i<60;i++) wzAt(800,0,zWheelScale(z,-100,0,WZ_MAX));
        var hi={z:z,px:px,py:py};
        for(var i=0;i<60;i++) wzAt(0,600,zWheelScale(z,100,0,WZ_MAX));
        JSON.stringify({hi:hi,lo:{z:z,px:px,py:py}})""")
        self.assertEqual(r["hi"]["z"], 4)
        self.assertGreaterEqual(r["hi"]["px"], 800 * (1 - 4))
        self.assertLessEqual(r["hi"]["px"], 0)
        self.assertAlmostEqual(r["hi"]["px"], 800 * (1 - 4), places=6)  # pointer at the right edge: the right edge stays there
        self.assertEqual(r["lo"]["z"], 1)
        self.assertAlmostEqual(r["lo"]["px"], 0, places=6)
        self.assertAlmostEqual(r["lo"]["py"], 0, places=6)

    def test_continuous_not_snapped(self):
        r = page_js("wzAt(400,300,zWheelScale(1,-40,0,WZ_MAX)); JSON.stringify(z)")
        self.assertTrue(1.05 < r < 1.5 and abs(r - 1.2) > 0.01 and abs(r - 2) > 0.01, r)

    def test_map_click_centres_the_view_there(self):
        r = page_js("""
        z=3; px=0; py=0;
        wzMapMove({clientX:10+160*.75,clientY:410+120*.25},false);
        var v=wzView(); JSON.stringify({cx:v.cx,cy:v.cy,s:v.s})""")
        self.assertAlmostEqual(r["cx"], 0.75, places=6)
        self.assertAlmostEqual(r["cy"], 0.25, places=6)
        self.assertEqual(r["s"], 3)

    def test_map_click_near_the_corner_is_clamped(self):
        r = page_js("""
        z=2; wzMapMove({clientX:10+160,clientY:410},false);
        var v=wzView(); JSON.stringify({cx:v.cx,cy:v.cy})""")
        self.assertAlmostEqual(r["cx"], 0.75, places=6)
        self.assertAlmostEqual(r["cy"], 0.25, places=6)

    def test_map_rectangle_and_class_follow_the_zoom_and_no_request_goes_out(self):
        r = page_js("""
        wzAt(400,300,2);
        var on=vp.classList.contains('wzoom'),mv=Q('#zoomMap .mv').style;
        var box={w:mv.width,l:mv.left};
        wzSet({s:1,cx:.5,cy:.5});
        JSON.stringify({on:on,box:box,off:vp.classList.contains('wzoom'),calls:calls,iv:intervals})""")
        self.assertTrue(r["on"])
        self.assertEqual(r["box"], {"w": "50%", "l": "25%"})
        self.assertFalse(r["off"])
        self.assertEqual(r["calls"], [])  # never /api/loupe or anything else over Wi-Fi
        self.assertEqual(r["iv"], 1)  # the map refresh runs only while zoomed


@unittest.skipUnless(HAVE_JS, "needs the JavaScript engine of macOS (osascript)")
class SharpSizeAndPointers(unittest.TestCase):
    def run_js(self, scenario):
        return page_js(scenario, full=True)

    def test_rest_at_3x_asks_for_1280_and_at_2x_for_1024_once(self):
        r = self.run_js("""
        z=3; wzSizeCheck(); var a=calls.slice(); autoLvBusy=false; wzSizeCheck(); var again=calls.slice();
        z=2; st.lvqty='0640x0480'; autoLvLastChange=0; autoLvBusy=false; calls.length=0; wzSizeCheck();
        JSON.stringify({a:a,again:again,b:calls,on:wzSharpOn})""")
        self.assertEqual(r["a"], ["start 1280x0960"])
        self.assertEqual(r["again"], ["start 1280x0960"])  # within 3 s: no second change
        self.assertEqual(r["b"], ["start 1024x0768"])
        self.assertTrue(r["on"])

    def test_nothing_at_1_5x_or_below_and_nothing_when_the_size_fits(self):
        r = self.run_js("""
        z=1.5; wzSizeCheck(); var a=calls.length; z=3; st.lvqty='1280x0960'; wzSizeCheck();
        JSON.stringify({a:a,b:calls.length})""")
        self.assertEqual((r["a"], r["b"]), (0, 0))

    def test_no_change_during_a_gesture_or_a_shot(self):
        r = self.run_js("""
        z=3; wzPtr.set(1,{x:0,y:0}); wzSizeCheck(); var a=calls.length,t=timers.length;
        wzPtr.clear(); st.stage=1; wzSizeCheck(); var b=calls.length;
        st.stage=0; st.job={running:true}; wzSizeCheck(); var c=calls.length;
        st.job={}; st.movie=1; wzSizeCheck(); var d=calls.length;
        JSON.stringify({a:a,b:b,c:c,d:d,retry:t>0})""")
        self.assertEqual((r["a"], r["b"], r["c"], r["d"]), (0, 0, 0, 0))
        self.assertTrue(r["retry"])  # it looks again later

    def test_back_at_1x_returns_to_the_adaptive_size(self):
        r = self.run_js("""
        z=3; wzSizeCheck(); autoLvBusy=false; autoLvLastChange=0; st.lvqty='1280x0960';
        z=1; calls.length=0; wzSizeCheck();
        JSON.stringify({calls:calls,on:wzSharpOn})""")
        self.assertEqual(r["calls"], ["start 0640x0480"])  # the size from before the zoom
        self.assertFalse(r["on"])
        r = self.run_js("z=1; st.lvqty='0640x0480'; wzSizeCheck(); JSON.stringify(calls)")
        self.assertEqual(r, [])  # never zoomed: the adaptive logic is left alone

    SLOW = "st.lvperf={sample_seconds:5,fps:5};st.lv_age=0;"

    def test_slow_sharp_size_falls_back_and_sets_focus_mode(self):
        r = self.run_js("""
        z=3; wzSizeCheck(); var a=calls.slice(); st.lvqty='1280x0960'; autoLvBusy=false; autoLvLastChange=0;
        """ + self.SLOW + """
        reduceAutoLiveSize(); var first=wzFocusOnly; autoLvSlowSince=Date.now()-5000; reduceAutoLiveSize();
        var focus=wzFocusOnly, t=timers.length; calls.length=0; autoLvLastChange=0; autoLvBusy=false; wzSizeCheck();
        JSON.stringify({a:a,first:first,focus:focus,calls:calls,on:wzSharpOn,label:labels.at(-1)})""")
        self.assertEqual(r["a"], ["start 1280x0960"])
        self.assertFalse(r["first"])  # slowness must last 4 s
        self.assertTrue(r["focus"])
        self.assertEqual(r["calls"], ["start 0640x0480"])  # the adaptive size from before
        self.assertFalse(r["on"])

    def test_focus_mode_stays_normal_at_rest_and_goes_sharp_on_focus_once(self):
        r = self.run_js("""
        z=3; st.lvqty='0640x0480'; wzFocusOnly=true; wzBase='0640x0480'; wzSizeCheck(); var idle=calls.length;
        wzFocusAction(); var queued=timers.at(-1)[1]; wzSizeCheck(); var a=calls.slice();
        st.lvqty='1280x0960'; autoLvBusy=false; wzFocusAction(); wzSizeCheck(); var again=calls.length;
        wzFocusUntil=Date.now()-1; autoLvLastChange=0; autoLvBusy=false; wzSizeCheck();
        JSON.stringify({idle:idle,queued:queued,a:a,again:again,calls:calls,focus:wzFocusOnly})""")
        self.assertEqual(r["idle"], 0)
        self.assertEqual(r["queued"], 0)  # from a timer: the focus request is already out
        self.assertEqual(r["a"], ["start 1280x0960"])
        self.assertEqual(r["again"], 1)  # already sharp: no second change
        self.assertEqual(r["calls"], ["start 1280x0960", "start 0640x0480"])  # back after the hold
        self.assertTrue(r["focus"])  # stays until 1x

    def test_focus_action_changes_nothing_in_a_gesture(self):
        r = self.run_js("z=3; st.lvqty='1024x0768'; wzPtr.set(1,{x:0,y:0}); wzFocusAction(); wzSizeCheck(); JSON.stringify({c:calls.length})")
        self.assertEqual(r["c"], 0)

    def test_focus_in_the_middle_range_brings_the_highest_size_then_back(self):
        r = self.run_js("""
        z=2; st.lvqty='1024x0768'; wzSharpOn=true; wzBase='0800x0600'; wzFocusAction(); wzSizeCheck(); var a=calls.slice();
        st.lvqty='1280x0960'; autoLvBusy=false; autoLvLastChange=0; wzFocusUntil=Date.now()-1; wzSizeCheck();
        JSON.stringify({a:a,calls:calls,fn:wzSizeFor(2)})""")
        self.assertEqual(r["a"], ["start 1280x0960"])
        self.assertEqual(r["calls"], ["start 1280x0960", "start 1024x0768"])  # the size that belongs to 2x
        self.assertEqual(r["fn"], "1024x0768")

    def test_focus_at_or_below_1_5x_changes_nothing(self):
        self.assertEqual(self.run_js("z=1.5; st.lvqty='0800x0600'; wzFocusAction(); wzSizeCheck(); JSON.stringify(calls)"), [])

    def test_no_size_change_while_half_pressed_even_inside_the_hold(self):
        r = self.run_js("""
        z=3; st.lvqty='0640x0480'; wzFocusOnly=true; wzBase='0640x0480'; wzFocusAction(); st.stage=1; wzSizeCheck();
        var held=calls.length, retry=timers.at(-1)[1]; st.stage=0; autoLvLastChange=0; wzSizeCheck();
        JSON.stringify({held:held,retry:retry,after:calls})""")
        self.assertEqual(r["held"], 0)
        self.assertEqual(r["retry"], 1000)
        self.assertEqual(r["after"], ["start 1280x0960"])

    def test_half_press_does_not_change_the_size(self):
        # Wi-Fi test 2026-11-22: a size change right after the Halfway release raced with the release's own live
        # view restart (mode shutter -> rec) and exec_takemotion answered 520: only a tap AF brings the sharp size
        with open(HTML, encoding="utf-8") as f:
            h = f.read()
        body = h[h.index("$('#half').onclick="):h.index("$('#reset').onclick=")]
        self.assertNotIn("wzFocusAction()", body)

    def test_focus_mode_ends_at_1x(self):
        r = self.run_js("z=1; wzFocusOnly=true; wzSizeCheck(); JSON.stringify({f:wzFocusOnly,c:calls.length})")
        self.assertEqual((r["f"], r["c"]), (False, 0))

    def test_usb_or_read_only_is_left_alone(self):
        self.assertEqual(self.run_js("enabled=false; sizing=false; z=4; wzSizeCheck(); JSON.stringify(calls)"), [])
        self.assertEqual(self.run_js("enabled=true; sizing=false; z=2; wzFocusAction(); wzSizeCheck(); JSON.stringify(calls)"), [])

    def test_explicit_size_goes_sharp_in_the_zoom_and_back_at_1x(self):
        # user 2026-11-22: 800x600 picked by hand, then 4x stayed at 800x600
        r = self.run_js("""
        enabled=false; st.lvqty='0800x0600'; z=4; wzSizeCheck(); var a=calls.slice();
        st.lvqty='1280x0960'; autoLvBusy=false; autoLvLastChange=0; z=1; calls.length=0; wzSizeCheck();
        JSON.stringify({a:a,b:calls,base:wzBase,on:wzSharpOn})""")
        self.assertEqual(r["a"], ["start 1280x0960"])
        self.assertEqual(r["b"], ["start 0800x0600"])  # the explicit size
        self.assertFalse(r["on"])

    def test_explicit_size_is_not_replaced_by_the_adaptive_one(self):
        r = self.run_js("""
        enabled=false; ideal='0640x0480'; st.lvqty='1024x0768'; z=4; wzSizeCheck();
        st.lvqty='1280x0960'; autoLvBusy=false; autoLvLastChange=0; z=1; calls.length=0; wzSizeCheck();
        JSON.stringify(calls)""")
        self.assertEqual(r, ["start 1024x0768"])

    def test_size_picked_while_zoomed_is_the_one_to_return_to(self):
        # the pick runs before st.lvqty shows it: the stale camera size must not become the 1x size
        with open(HTML, encoding="utf-8") as f:
            line = next(l for l in f.read().splitlines() if l.startswith("$('#lvqty').onchange="))
        r = self.run_js("""
        enabled=false; st.lvqty='0640x0480'; z=3;
        Q('#lvStart').click=function(){}; 
        %s
        Q('#lvqty').value='1024x0768'; Q('#lvqty').onchange(); wzSizeCheck(); var a=calls.slice();
        st.lvqty='1280x0960'; autoLvBusy=false; autoLvLastChange=0; z=1; calls.length=0; wzSizeCheck();
        JSON.stringify({a:a,b:calls,base:wzBase})""" % line.replace("$(", "Q("))
        self.assertEqual(r["a"], ["start 1280x0960"])
        self.assertEqual(r["b"], ["start 1024x0768"])

    def test_explicit_size_focus_action_at_2x_then_back(self):
        r = self.run_js("""
        enabled=false; z=2; st.lvqty='0800x0600'; wzFocusAction(); wzSizeCheck(); var a=calls.slice();
        st.lvqty='1280x0960'; autoLvBusy=false; autoLvLastChange=0; wzFocusUntil=Date.now()-1; wzSizeCheck();
        JSON.stringify({a:a,calls:calls})""")
        self.assertEqual(r["a"], ["start 1280x0960"])
        self.assertEqual(r["calls"], ["start 1280x0960", "start 1024x0768"])  # the middle size that belongs to 2x

    def test_explicit_size_is_never_stepped_down_at_1x_but_the_sharp_size_falls_back(self):
        slow = "st.lvperf={sample_seconds:5,fps:5};st.lv_age=0;autoLvLastChange=0;enabled=false;"
        r = self.run_js(slow + "st.lvqty='1024x0768'; z=1; reduceAutoLiveSize(); JSON.stringify({s:autoLvSlowSince,c:calls.length})")
        self.assertEqual((r["s"], r["c"]), (0, 0))
        r = self.run_js(slow + """z=3; wzSizeCheck(); st.lvqty='1280x0960'; autoLvBusy=false; autoLvLastChange=0;
        reduceAutoLiveSize(); autoLvSlowSince=Date.now()-5000; reduceAutoLiveSize(); calls.length=0; autoLvLastChange=0; wzSizeCheck();
        JSON.stringify({f:wzFocusOnly,c:calls,l:labels.at(-1)})""")
        self.assertTrue(r["f"])
        self.assertEqual(r["c"], ["start 0640x0480"])  # the size from before

    def test_no_step_down_for_slowness_while_zoomed(self):
        slow = "st.lvperf={sample_seconds:5,fps:5};st.lvqty='1280x0960';st.lv_age=0;"
        r = self.run_js(slow + "z=3; reduceAutoLiveSize(); JSON.stringify({s:autoLvSlowSince,c:calls.length})")
        self.assertEqual((r["s"], r["c"]), (0, 0))
        r = self.run_js(slow + "z=1; reduceAutoLiveSize(); JSON.stringify({s:autoLvSlowSince>0})")
        self.assertTrue(r["s"])  # the same slowness counts at 1x

    def test_drag_is_no_tap_and_a_plain_click_is(self):
        r = self.run_js("""
        z=2; vp.onpointerdown(ev(1,100,100)); vp.onpointermove(ev(1,120,100)); vp.onpointerup(ev(1,120,100)); var a=picks;
        vp.onpointerdown(ev(1,100,100)); vp.onpointerup(ev(1,100,100));
        JSON.stringify({a:a,b:picks})""")
        self.assertEqual((r["a"], r["b"]), (0, 1))

    def test_pinch_gives_no_tap_and_the_left_finger_keeps_panning(self):
        r = self.run_js("""
        vp.onpointerdown(ev(1,300,300)); vp.onpointerdown(ev(2,400,300));
        vp.onpointermove(ev(2,500,300)); var zz=z;
        vp.onpointerup(ev(2,500,300)); var p0=px;
        vp.onpointermove(ev(1,250,300)); var moved=px!==p0;
        vp.onpointerup(ev(1,250,300));
        JSON.stringify({picks:picks,zoomed:zz>1.5,moved:moved})""")
        self.assertEqual(r["picks"], 0)
        self.assertTrue(r["zoomed"])
        self.assertTrue(r["moved"])


@unittest.skipUnless(HAVE_JS, "needs the JavaScript engine of macOS (osascript)")
class AutoSizeOnTheComputer(unittest.TestCase):
    """The sharp size also works on the computer, but only while the size choice is Auto (REQ-F55)."""

    def setUp(self):
        with open(HTML, encoding="utf-8") as f:
            self.h = f.read()

    def enabled(self, mobile, auto, usb=False, write=True):
        line = re.search(r"const wzSizingEnabled=[^\n]*\n", self.h).group(0) + re.search(r"const autoLvEnabled=[^\n]*\n", self.h).group(0)
        code = ("var MOBILE_LIVE={matches:%s},isUsb=%s,canWrite=%s,features=new Set(['lvsize']),"
                "Q=function(){return {checked:%s}};%s JSON.stringify(autoLvEnabled())"
                % (str(mobile).lower(), str(usb).lower(), str(write).lower(), str(auto).lower(), line.replace("$(", "Q(")))
        out = subprocess.run(["osascript", "-l", "JavaScript", "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip())

    def test_computer_with_auto_ticked_is_enabled_and_a_picked_size_is_not(self):
        self.assertTrue(self.enabled(False, True))
        self.assertFalse(self.enabled(False, False))  # a size picked by hand: no adaptive size at 1x
        self.assertTrue(self.enabled(True, False))  # the phone is always automatic
        self.assertFalse(self.enabled(False, True, usb=True))  # USB: camera Zoom AF, manual size
        self.assertFalse(self.enabled(False, True, write=False))

    def test_markup_and_handlers(self):
        self.assertIn('id="lvAuto" checked', self.h)
        self.assertIn('data-i18n="lv.autoSize"', self.h)
        self.assertIn("$('#lvAuto').checked=false", self.h)  # picking a size ends Auto
        self.assertIn("$('#lvAutoLab').hidden=isUsb", self.h)  # Wi-Fi only
        self.assertIn("on&&MOBILE_LIVE.matches", self.h)  # the size choice hides on the phone only


if __name__ == "__main__":
    unittest.main()
