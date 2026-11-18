"""Wi-Fi screen zoom (REQ-F55): smooth zoom about the pointer, 1x-4x, overview map, no camera command.

The page code runs in JavaScriptCore (osascript) with a stubbed viewport; no camera, no server."""
import json
import os
import re
import shutil
import subprocess
import unittest

HTML = os.path.join(os.path.dirname(__file__), "..", "omcap", "web", "index.html")
HAVE_JS = shutil.which("osascript")

STUBS = """
var calls=[],usbZoom=false,z=1,px=0,py=0,drag=null,intervals=0,
  calm={matches:true},setInterval=function(){intervals++;return 7},clearInterval=function(){},
  el=function(){return {style:{},hidden:false,naturalWidth:0,classList:{_s:{},toggle:function(c,on){this._s[c]=on===undefined?!this._s[c]:!!on},
    contains:function(c){return !!this._s[c]},add:function(c){this._s[c]=true},remove:function(c){delete this._s[c]}}}},
  els={},Q=function(s){return els[s]||(els[s]=el())},document={querySelectorAll:function(){return []}},
  vp=Q('vp'),layer=Q('layer'),zMap={getBoundingClientRect:function(){return {left:10,top:410,width:160,height:120}}},
  api=function(p){calls.push(p)},fetch=function(p){calls.push(p)};
vp.getBoundingClientRect=function(){return {width:800,height:600,left:0,top:0}};
var zMeasure=function(){return vp.getBoundingClientRect()},zBox=zMeasure;
"""


def page_js(scenario):
    with open(HTML, encoding="utf-8") as f:
        h = f.read()
    maths = h[h.index("// zoom maths (pure"):h.index("// zoom maths end")]
    wz = h[h.index("// Wi-Fi screen zoom (REQ-F55)"):h.index("function setZoom(")]
    wz += h[h.index("// Wi-Fi: a click or drag in the map"):].split("\n")[1] + "\n"  # wzMapMove
    code = "%s\n%s\n%s\n%s" % (STUBS, maths, wz.replace("$(", "Q("), scenario)
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip())


class Markup(unittest.TestCase):
    def setUp(self):
        with open(HTML, encoding="utf-8") as f:
            self.h = f.read()

    def test_scale_limit_is_one_constant_with_its_reason(self):
        self.assertIn("const WZ_MAX=4", self.h)
        self.assertIn("beyond 4x it only gets blurrier", self.h)
        self.assertNotIn("Math.min(8,Math.max(1,z*", self.h)  # the old 8x wheel steps are gone

    def test_usb_wheel_limit_unchanged(self):
        self.assertIn("const zWheelScale=(s,dy,mode,max=14)=>", self.h)
        self.assertIn("zWheelScale(V.s,e.deltaY,e.deltaMode)", self.h)  # the USB call keeps the default 14

    def test_buttons_stay(self):
        for n in (1, 2, 4):
            self.assertIn('<button data-z="%d">' % n, self.h)

    def test_map_reuses_the_aria_label(self):
        self.assertEqual(len(re.findall(r'id="zoomMap"[^>]*data-i18n-aria="lv.zoomMap"', self.h)), 1)

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


if __name__ == "__main__":
    unittest.main()
