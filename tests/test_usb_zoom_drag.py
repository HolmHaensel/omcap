"""USB smooth zoom (REQ-F54): revision stamps, frame headers, click focus, page markup and zoom maths. No camera."""
import io
import json
import os
import re
import shutil
import subprocess
import unittest

from omcap import ptp, server, usb_camera
from omcap.camera import CameraError
from tests.test_usb_loupe import make

HTML = os.path.join(os.path.dirname(__file__), "..", "omcap", "web", "index.html")


class Revision(unittest.TestCase):
    def test_every_successful_write_counts(self):
        cam = make()
        self.assertEqual(cam.loupe_rev, 0)
        cam.loupe(True, 5, 0.5, 0.5)
        cam.loupe(False)
        self.assertEqual(cam.loupe_rev, 2)

    def test_failed_write_does_not_count(self):
        cam = make()
        with self.assertRaises(CameraError):
            cam.loupe(True, 4)
        self.assertEqual(cam.loupe_rev, 0)

    def test_forced_off_counts(self):
        cam = make()
        cam.loupe_on = True
        cam.stop_liveview()
        self.assertEqual(cam.loupe_rev, 1)
        cam.gone, cam.loupe_on = True, True
        cam.stop_liveview()
        self.assertEqual(cam.loupe_rev, 2)

    def test_new_centre_while_on_cycles_d04b(self):
        # 0x9483 only takes effect while d04b goes to 1, so a moved centre needs off then on
        cam = make()
        cam.loupe(True, 5, 0.5, 0.5)
        cam._c.writes.clear()
        cam.loupe(True, 5, 0.25, 0.5)
        self.assertEqual([n for n, _ in cam._c.writes], ["d0cf", "d04b", "opcode", "d04b"])
        self.assertEqual(cam._c.writes[1], ("d04b", "2"))
        self.assertEqual(cam._c.writes[3], ("d04b", "1"))


class AfAreaFixed(unittest.TestCase):
    """The AF area is fixed; d05a/d05b/d071/d072 are the Zoom AF frame limits (measured 2026-11-18), never read for it."""

    def cam(self, values):
        cam = make()
        cam.gone, cam.last_af, calls = False, None, []

        def get_prop_value(code):
            calls.append(code)
            return values[code]
        cam._c.get_prop_value = get_prop_value
        cam._calls = calls
        return cam

    def test_fixed_area_and_live_mode_and_field(self):
        cam = self.cam({0xD00C: 33024, 0xD051: 41})
        a = cam.af_area()
        self.assertEqual({k: a["area"][k] for k in ("x0", "x1", "y0", "y1")}, {"x0": 216, "x1": 1060, "y0": 160, "y1": 796})
        self.assertEqual((a["area"]["w"], a["area"]["h"]), (1280, 960))
        self.assertEqual((a["mode"], a["field"]), (33024, 41))
        self.assertEqual(set(cam._calls), {0xD00C, 0xD051})  # no zoom limits read as the AF area

    def test_same_while_zoom_af_is_on(self):
        cam = self.cam({0xD00C: 33025, 0xD051: 5})
        before = cam.af_area()["area"]
        cam.loupe_on = True
        self.assertEqual(cam.af_area()["area"], before)


class CropPosition(unittest.TestCase):
    """The camera moves the crop 1.135x as far from the centre as sent (measured 2026-11-16): send less x."""

    def sent_point(self, x, y):
        cam = make()
        cam.loupe(True, 5, x, y)
        value = int(cam._c.writes[1][1].split(",")[1], 16)
        return value & 0xFFFF, value >> 16

    def test_centre_is_exact_and_y_unchanged(self):
        self.assertEqual(self.sent_point(0.5, 0.5), (512, 384))
        self.assertEqual(self.sent_point(0.5, 0.25)[1], 192)

    def test_x_is_pulled_towards_the_centre(self):
        sent = self.sent_point(0.30, 0.5)[0] / 1024
        self.assertAlmostEqual(0.5 + (sent - 0.5) * ptp.LOUPE_X_GAIN, 0.30, places=2)  # what the camera makes of it
        self.assertAlmostEqual(self.sent_point(0.70, 0.5)[0] / 1024, 1 - sent, places=2)

    def test_gain_constant(self):
        self.assertEqual(ptp.LOUPE_X_GAIN, 1.135)


class CycleStamp(unittest.TestCase):
    def test_frames_between_the_cycle_are_stamped_normal(self):
        cam = make()
        cam.loupe(True, 5, 0.5, 0.5)
        seen = []
        orig = cam._opcode
        cam._opcode = lambda *a: (seen.append((cam.loupe_on, cam.loupe_rev)), orig(*a))[1]
        cam.loupe(True, 5, 0.25, 0.5)
        self.assertEqual(seen, [(False, 2)])  # off and one revision later when 0x9483 goes out
        self.assertEqual((cam.loupe_on, cam.loupe_rev), (True, 3))

    def test_failing_point_leaves_a_true_state(self):
        cam = make()
        cam.loupe(True, 5, 0.5, 0.5)

        def boom(*a):
            raise CameraError("0x9483 failed")
        cam._opcode = boom
        with self.assertRaises(CameraError):
            cam.loupe(True, 5, 0.25, 0.5)
        self.assertEqual((cam.loupe_on, cam.loupe_rev), (False, 2))


class FocusInZoom(unittest.TestCase):
    def setUp(self):
        self.cam = make()
        c = self.cam
        c.gone, c.stage, c.last_press, c._event_log = False, 0, 0.0, []
        c._hold_add = lambda n: None
        c._events = lambda *a, **k: False  # the camera sends no AF result in this test
        c.af_mode = usb_camera.AF_SINGLE

    def presses(self):
        return [v for n, v in self.cam._c.writes if n == "opcode"]

    def test_half_press_then_release_without_shot(self):
        self.cam.loupe_on = True
        self.cam.focus()
        self.assertEqual(self.presses(), ["0x9481,0x1", "0x9481,0x5"])

    def test_normal_view_still_releases_with_6(self):
        self.cam.focus()
        self.assertEqual(self.presses(), ["0x9481,0x1", "0x9481,0x6"])


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.saved = (server.cam, server.conn_type, server.ensure_idle, server.live)
        server.ensure_idle = lambda: None
        server.live = type("Live", (), {"running": True})()

    def tearDown(self):
        server.cam, server.conn_type, server.ensure_idle, server.live = self.saved

    def act(self, b):
        return server.Handler._action(server.Handler.__new__(server.Handler), "/api/loupe", b)

    def test_answer_carries_the_revision(self):
        server.cam, server.conn_type = make(), "usb"
        self.assertEqual(self.act({"on": True, "ratio": 3, "x": 0.5, "y": 0.5}), {"loupe": True, "rev": 1})
        self.assertEqual(self.act({"on": False}), {"loupe": False, "rev": 2})

    def test_unknown_body_is_refused_not_switched_off(self):
        server.cam, server.conn_type = make(), "usb"
        self.act({"on": True, "ratio": 3})
        server.cam._c.writes.clear()
        for body in ({"drag": {"dx": 0, "dy": 110}}, {}):  # e.g. a stale page from before the smooth zoom
            with self.assertRaises(CameraError):
                self.act(body)
        self.assertEqual(server.cam._c.writes, [])
        self.assertTrue(server.cam.loupe_on)

    def test_wifi_unchanged(self):
        server.cam, server.conn_type = object(), "wifi"
        with self.assertRaises(CameraError):
            self.act({"on": True})
        self.assertNotIn("loupe", server.WIFI_FEATURES)


class FrameHeaders(unittest.TestCase):
    """/live.jpg stamps each frame with the zoom state valid when it was fetched."""

    def frame(self, live):
        saved = server.live
        server.live = live
        sent = []
        h = server.Handler.__new__(server.Handler)
        h.send_response = lambda code: sent.append(("code", code))
        h.send_header = lambda k, v: sent.append((k, v))
        h.end_headers = lambda: None
        h.wfile = io.BytesIO()
        try:
            h._live_frame(0)
        finally:
            server.live = saved
        return dict(sent)

    def test_usb_frame_has_stamp(self):
        live = usb_camera.UsbLive.__new__(usb_camera.UsbLive)
        import threading
        live.cond, live.seq, live.frame, live.stamp = threading.Condition(), 4, b"\xff\xd8x\xff\xd9", (7, 1)
        hdr = self.frame(live)
        self.assertEqual((hdr["X-Seq"], hdr["X-Loupe"], hdr["X-Loupe-Rev"]), ("4", "1", "7"))

    def test_wifi_frame_is_zero(self):
        live = type("L", (), {"wait_frame": lambda self, s: (2, b"\xff\xd8x\xff\xd9", (0, 0))})()
        hdr = self.frame(live)
        self.assertEqual((hdr["X-Loupe"], hdr["X-Loupe-Rev"]), ("0", "0"))

    def test_stamp_is_taken_before_the_fetch(self):
        class Cam:
            loupe_rev, loupe_on, hold = 3, True, False

            def dial_turned(self):
                return False

            def preview_frame(self):  # a zoom write lands during the fetch: the stamp must stay the older one
                Cam.loupe_rev, Cam.loupe_on = 4, False
                live._run = False
                return b"frame"

        live = usb_camera.UsbLive(Cam())
        live._run = True
        live._loop()
        self.assertEqual(live.stamp, (3, 1))


class Page(unittest.TestCase):
    def setUp(self):
        with open(HTML, encoding="utf-8") as f:
            self.html = f.read()

    def test_markup(self):
        h = self.html
        for z in (1, 2, 4):
            self.assertIn('data-z="%d"' % z, h)
        for z in (1, 3, 5, 7, 10, 14):
            self.assertIn('data-lz="%d"' % z, h)
        self.assertIn("const LOUPE_STEPS=[1,3,5,7,10,14]", h)
        self.assertIn('id="liveBack"', h)  # backdrop behind the moved camera crop
        self.assertIn("LOUPE_LAG_FRAMES=6", h)
        for name in ("loupeReconcile", "loupeCommit", "loupeHold", "loupeOnFrame", "zRender"):
            self.assertIn("function %s(" % name, h)
        for name in ("zSnap", "zClamp", "zClampCam", "zCrop", "zSigDiff", "zSwapDue", "zMatch", "zRubber", "zWheelScale", "zZoomAt", "zMatchLimit"):
            self.assertIn("const %s=" % name, h)
        self.assertIn("X-Loupe-Rev", h)
        self.assertIn("const zCovers=", h)
        self.assertIn('id="zoomMap"', h)  # overview map, shown only while .loupe
        self.assertNotIn("loupeBtn", h)

    def test_idle_server_does_not_block_the_zoom(self):
        """zBlock hides the zoom control while the camera is busy: every state key it reads is falsy when idle
        ("play" is a boolean in /api/state, so `!=null` would always block)."""
        m = re.search(r"zBlock=([^;]*);", self.html)
        self.assertNotIn("st.play!=null", m.group(1))
        saved = (server.cam, server.live)
        server.cam = make()
        server.live = type("Live", (), {"running": True, "age": 0.0})()
        try:
            st = server.public_state()
        finally:
            server.cam, server.live = saved
        for key in set(re.findall(r"st\.(\w+)", m.group(1))) - {"job"}:
            self.assertFalse(st[key], key)
        self.assertFalse(st["job"]["running"])

    def test_title_describes_the_new_gestures(self):
        m = re.search(r'"lv.loupeTitle": "([^"]*)"', self.html)
        self.assertIn("wheel or pinch = zoom smoothly", m.group(1))
        self.assertIn("snaps", m.group(1))


@unittest.skipUnless(shutil.which("osascript"), "needs the JavaScript engine of macOS (osascript)")
class ZoomMaths(unittest.TestCase):
    """Runs the page's pure zoom functions (between the 'zoom maths' markers) in JavaScriptCore."""

    def run_js(self, expr):
        with open(HTML, encoding="utf-8") as f:
            h = f.read()
        steps = re.search(r"const LOUPE_STEPS=\[[^\]]*\];", h).group(0)
        maths = h[h.index("// zoom maths (pure"):h.index("// zoom maths end")]
        code = "%s\n%s\nJSON.stringify(%s)" % (steps, maths, expr)
        out = subprocess.run(["osascript", "-l", "JavaScript", "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip())

    def test_clamp_keeps_the_view_in_the_picture(self):
        self.assertEqual(self.run_js("[zClamp(0.1,5),zClamp(0.95,5),zClamp(0.4,1),zClamp(0.5,14)]"), [0.1, 0.9, 0.5, 0.5])

    def test_camera_limits_are_the_middle_80_percent(self):
        r = self.run_js("[zClampCam(0,5),zClampCam(1,5),zClampCam(.3,5),zClampCam(0,10),zClampCam(1,10),zClampCam(.9,1),zClampCam(0,3)]")
        self.assertEqual([round(v, 4) for v in r], [0.2, 0.8, 0.3, 0.15, 0.85, 0.5, 0.2667])

    def test_signature_comparison(self):
        grey = self.run_js("zGrey([255,255,255,255, 0,0,0,255])")
        self.assertEqual([round(v) for v in grey], [255, 0])
        r = self.run_js("[zSigDiff([10,20,30],[12,18,30]),zSigDiff([0,0],[100,100]),zSigDiff(null,[1]),zSigDiff([1],[1,2])]")
        self.assertEqual(r, [4 / 3, 100, 0, 0])

    def test_swap_on_a_clear_difference_or_after_the_lag(self):
        r = self.run_js("[zSwapDue(2,1),zSwapDue(9.9,3),zSwapDue(10,1),zSwapDue(55,1),zSwapDue(0,6),zSwapDue(0,7)]")
        self.assertEqual(r, [False, False, True, True, False, True])

    PATTERN = "i=>(i*7919%251)+((i*31)%17)*5"  # a busy but non-repeating test picture

    def test_match_finds_a_shifted_crop(self):
        # a 78x58 picture, the 64x48 'sharp frame' cut out at offset (10, 3): shift from the centred (7, 5) = (3, -2)
        r = self.run_js("(P=>{const bw=78,bh=58,big=[];for(let i=0;i<bw*bh;i++)big.push(P(i));"
                        "const sm=[];for(let y=0;y<48;y++)for(let x=0;x<64;x++)sm.push(big[(y+3)*bw+x+10]);"
                        "return zMatch(big,bw,bh,sm,64,48)})(%s)" % self.PATTERN)
        self.assertEqual((r["dx"], r["dy"]), (3, -2))
        self.assertAlmostEqual(r["score"], 1.0)

    def test_match_gives_up_on_flat_or_unrelated(self):
        flat = self.run_js("(()=>{const big=new Array(78*58).fill(120),sm=new Array(64*48).fill(120);return zMatch(big,78,58,sm,64,48)})()")
        self.assertIsNone(flat)
        weak = self.run_js("(P=>{const big=[];for(let i=0;i<78*58;i++)big.push(P(i));"
                           "const sm=[];for(let i=0;i<64*48;i++)sm.push((i*i*13+i*7)%256);return zMatch(big,78,58,sm,64,48)})(" + self.PATTERN + ")")
        self.assertIsNone(weak)

    def test_match_refuses_a_large_correction(self):
        src = ("(P=>{const bw=78,bh=58,big=[];for(let i=0;i<bw*bh;i++)big.push(P(i));"
               "const sm=[];for(let y=0;y<48;y++)for(let x=0;x<64;x++)sm.push(big[(y+3)*bw+x+10]);"
               "return [zMatch(big,bw,bh,sm,64,48,3,2),zMatch(big,bw,bh,sm,64,48,2.9,2),zMatch(big,bw,bh,sm,64,48,3,1.9)]})(")
        r = self.run_js(src + self.PATTERN + ")")
        self.assertEqual((r[0]["dx"], r[0]["dy"]), (3, -2))
        self.assertEqual(r[1:], [None, None])  # shift (3, -2) beyond the limit in x or y

    def test_match_limit_is_relative_to_the_crop(self):
        r = self.run_js("[zMatchLimit(3),zMatchLimit(14)]")
        self.assertAlmostEqual(r[0]["pic"], 0.05)
        self.assertAlmostEqual(r[1]["pic"], 0.15 / 14)  # at x14 a correction is at most 15 % of the crop = of the viewport
        self.assertEqual((r[0]["x"], r[0]["y"]), (r[1]["x"], r[1]["y"]))  # the same in crop pixels

    def test_match_refuses_an_ambiguous_repeating_picture(self):
        r = self.run_js("(()=>{const bw=78,bh=58,big=[];for(let y=0;y<bh;y++)for(let x=0;x<bw;x++)big.push((x%8<4?30:220)+(y%2));"
                        "const sm=[];for(let y=0;y<48;y++)for(let x=0;x<64;x++)sm.push(big[(y+5)*bw+x+7]);return zMatch(big,bw,bh,sm,64,48,9,9)})()")
        self.assertIsNone(r)  # the same score every 8 px: no clear peak

    def test_coverage_of_the_viewport(self):
        r = self.run_js("[zCovers({k:1,x:0,y:0},800,600),zCovers({k:1,x:-30,y:-5},800,600),zCovers({k:1,x:12,y:0},800,600),"
                        "zCovers({k:1,x:0,y:-6},800,600),zCovers({k:2,x:-400,y:-300},800,600),zCovers({k:.9,x:0,y:0},800,600)]")
        self.assertEqual(r, [True, False, False, False, True, False])  # x -30 leaves 30 px open at the right, y -6 six px at the bottom, y +0 is fine

    def test_wheel_step_is_about_one_ratio_step_and_capped(self):
        r = self.run_js("[zWheelScale(3,-100,0),zWheelScale(3,100,0),zWheelScale(3,-5,0),zWheelScale(3,-3000,0),zWheelScale(10,-100,0),zWheelScale(1,100,0),zWheelScale(3,-3,1)]")
        self.assertAlmostEqual(r[0], 3 * 1.4918, places=2)  # one notch: e^0.4
        self.assertAlmostEqual(r[1], 3 / 1.4918, places=2)
        self.assertAlmostEqual(r[2], 3 * 1.0202, places=2)  # a trackpad pixel trickle is gentle
        self.assertAlmostEqual(r[3], 3 * 1.6487, places=2)  # a flick is capped at e^0.5 per event
        self.assertEqual((r[4], r[5]), (14, 1))
        self.assertAlmostEqual(r[6], 3 * 1.2, places=1)  # line mode: 16 px per line

    def test_pointer_point_stays_through_zoom_and_snap(self):
        # the point under the pointer at (.7, .4) stays there for every wheel step and for the snap at rest
        r = self.run_js("(()=>{let v={s:1,cx:.5,cy:.5};const p=zPic(v,.7,.4);const at=[];"
                        "for(const s of [1.5,2.2,3.3,4.4,4.6]){v=Object.assign({},v,zZoomAt(p,s,.7,.4));const q=zPic(v,.7,.4);at.push([q.x,q.y])}"
                        "v=Object.assign({},v,zZoomAt(p,zSnap(v.s),.7,.4));const q=zPic(v,.7,.4);at.push([q.x,q.y]);return {at,p,s:v.s}})()")
        for x, y in r["at"]:
            self.assertAlmostEqual(x, r["p"]["x"])
            self.assertAlmostEqual(y, r["p"]["y"])
        self.assertEqual(r["s"], 5)

    def test_zoom_at_the_edge_clamps_to_the_picture(self):
        # a point at the picture's edge cannot reach the view centre: the view stops at the camera-independent picture limit
        r = self.run_js("(()=>{const v=zZoomAt({x:.99,y:.99},5,.5,.5);return [v.cx,v.cy,v.s]})()")
        self.assertAlmostEqual(r[0], 0.9)
        self.assertAlmostEqual(r[1], 0.9)
        self.assertEqual(r[2], 5)

    def test_rubber_band_damps_beyond_the_camera_limits(self):
        r = self.run_js("[zRubber(.5,5,.3),zRubber(.1,5,.3),zRubber(.9,5,.3),zRubber(-1,5,.3),zRubber(.3,1,.3)]")
        self.assertEqual([round(v, 4) for v in r], [0.5, 0.17, 0.83, 0.1, 0.5])  # 0.2 - 0.1*0.3 ..., whole-picture clamp at 0.1

    def test_snap_on_a_log_scale(self):
        # 6 is nearer to 7 than to 5 on a log scale (1.17 vs 1.2), though 1 away from both
        self.assertEqual(self.run_js("[1,1.4,1.8,2,4,6,8,8.5,12,13.9,20].map(zSnap)"), [1, 1, 3, 3, 5, 7, 7, 10, 14, 14, 14])

    def test_shift_centres_the_view(self):
        t = self.run_js("[zShift({s:1,cx:.5,cy:.5},800,600),zShift({s:2,cx:.25,cy:.25},800,600),zShift({s:2,cx:.75,cy:.75},800,600)]")
        self.assertEqual(t[0], {"x": 0, "y": 0})
        self.assertEqual(t[1], {"x": 0, "y": 0})  # clamped corner: picture top left at the viewport corner
        self.assertEqual(t[2], {"x": -800, "y": -600})

    def test_zoom_about_a_point_keeps_it_in_place(self):
        r = self.run_js("(()=>{const v={s:1,cx:.5,cy:.5},p=zPic(v,.8,.3),c=zCentre(p,3,.8,.3);"
                        "const q=zPic({s:3,cx:c.cx,cy:c.cy},.8,.3);return [p,q]})()")
        self.assertAlmostEqual(r[0]["x"], r[1]["x"])
        self.assertAlmostEqual(r[0]["y"], r[1]["y"])

    def test_crop_of_the_view_itself_sits_at_the_origin(self):
        c = self.run_js("zCrop({s:5,cx:.3,cy:.6},{s:5,cx:.3,cy:.6},1024,768)")
        self.assertEqual((c["k"], c["x"], c["y"]), (1, 0, 0))

    def test_crop_follows_a_dragged_view(self):
        # view centre moved right by 0.01 of the picture at x5: the crop moves left by 0.01*W*5 px
        c = self.run_js("zCrop({s:5,cx:.31,cy:.6},{s:5,cx:.3,cy:.6},1000,750)")
        self.assertAlmostEqual(c["x"], -50)
        self.assertAlmostEqual(c["y"], 0)

    def test_crop_scales_with_the_view(self):
        c = self.run_js("zCrop({s:10,cx:.5,cy:.5},{s:5,cx:.5,cy:.5},1000,750)")
        self.assertEqual((c["k"], c["x"], c["y"]), (2, -500, -375))


@unittest.skipUnless(shutil.which("osascript"), "needs the JavaScript engine of macOS (osascript)")
class CommandPath(unittest.TestCase):
    """Runs the page's real zoom state code (loupeCommit, loupeHold, loupeReconcile, loupeSync) with a stubbed api."""

    STUBS = """
    var lPtr={size:0},calls=[],msgs=[],mode='ok',rev=0,z,px,py,usbZoom=true,loupeOn,tr=function(){return ''},performance={now:function(){return 0}};
    var el=function(){return {style:{},hidden:false,textContent:'',classList:{toggle:function(){},add:function(){},remove:function(){}},setAttribute:function(){},querySelector:function(){return el()}}};
    var vp=el(),layer=el(),Q=function(){return el()},document={querySelectorAll:function(){return []}},calm={matches:true};
    vp.getBoundingClientRect=function(){return {width:800,height:600}};
    function applyZoom(){} function msg(t,e){msgs.push([t,!!e])}
    function setTimeout(){return 1} function clearTimeout(){}
    function api(p,b){calls.push([p,b]);
      if((mode==='err'||mode==='dead')&&p==='/api/loupe') return {__err:'boom'};
      if(p==='/api/state') return mode==='dead'?{__err:'gone'}:{loupe:false,live:true,loupe_ratio:5};
      return {loupe:!!b.on,rev:++rev}}
    function __drive(g){var r=g.next();while(!r.done){var v=r.value;r=(v&&v.__err)?g.throw(new Error(v.__err)):g.next(v)}return r.value}
    """

    def run_js(self, scenario):
        with open(HTML, encoding="utf-8") as f:
            h = f.read()
        a, b = h.index("let loupeOn=false,usbZoom=false"), h.index("function loupeZoom(")
        region = h[a:b].replace("let loupeOn=false,usbZoom=false,", "var ")  # the stubs declare loupeOn and usbZoom
        region = region.replace("async function loupeReconcile(", "function* __rec(").replace("async function loupeRecover(", "function* __recv(")
        region = region.replace("await ", "yield ")
        region = region.replace("$(", "Q(")  # $ is the ObjC bridge in this engine
        region += "\nfunction loupeReconcile(){return __drive(__rec())}\nfunction loupeRecover(){return __drive(__recv())}\n"
        code = "%s\n%s\n%s" % (self.STUBS, region, scenario)
        out = subprocess.run(["osascript", "-l", "JavaScript", "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip())

    def test_commit_sends_one_on_request_and_stops(self):
        r = self.run_js("Object.assign(V,{s:4.4,cx:.3,cy:.6});loupeCommit();"
                        "JSON.stringify({calls:calls,sent:zSent,pend:zPend,busy:recBusy})")
        self.assertEqual(r["calls"], [["/api/loupe", {"on": True, "ratio": 5, "x": 0.3, "y": 0.6}]])
        self.assertTrue(r["sent"]["on"])
        self.assertEqual((r["pend"]["rev"], r["pend"]["on"]), (1, True))
        self.assertFalse(r["busy"])

    ZOOMED = "zSent={on:true,ratio:5,x:.5,y:.5};zWant={...zSent};zCamShows=true;zCam={s:5,cx:.5,cy:.5};Object.assign(V,{s:5,cx:.5,cy:.5});"

    def test_gesture_sends_no_command_while_the_camera_zoom_is_on(self):
        r = self.run_js(self.ZOOMED + "loupeHold();Object.assign(V,{s:9,cx:.4,cy:.45});loupeHold();"
                        "JSON.stringify({calls:calls,want:zWant,shows:zCamShows})")
        self.assertEqual(r["calls"], [])
        self.assertTrue(r["want"]["on"])
        self.assertTrue(r["shows"])  # the sharp crop stays on screen

    def test_one_request_at_rest(self):
        r = self.run_js(self.ZOOMED + "loupeHold();Object.assign(V,{s:9.5,cx:.4,cy:.45});loupeCommit();"
                        "JSON.stringify({calls:calls,shows:zCamShows})")
        self.assertEqual(r["calls"], [["/api/loupe", {"on": True, "ratio": 10, "x": 0.4, "y": 0.45}]])
        self.assertTrue(r["shows"])  # still the old crop until the new one arrives

    def test_old_crop_is_held_during_the_cycle(self):
        # command sent at rev 4; frames: old crop (on, rev 4) drawn; normal (off) or newer (rev 5, 6) held
        r = self.run_js(self.ZOOMED + "zLastRev=4;Object.assign(V,{s:10,cx:.4,cy:.45});loupeCommit();"
                        "var f=(rev,on)=>loupeOnFrame({rev:rev,on:on},null,null);"
                        "JSON.stringify({old:f(4,true),normal:f(5,false),lag1:f(6,true),pend:zPend})")
        self.assertEqual((r["old"], r["normal"], r["lag1"]), (True, False, False))
        self.assertEqual(r["pend"]["rev"], 1)  # the stub server answers rev 1

    def test_new_crop_shows_after_the_lag_frames(self):
        r = self.run_js(self.ZOOMED + "zLastRev=0;zRevAtSend=0;Object.assign(V,{s:10,cx:.4,cy:.45});loupeCommit();"
                        "var out=[];for(var i=0;i<8;i++)out.push(loupeOnFrame({rev:1,on:true},null,null));"
                        "JSON.stringify({out:out,cam:zCam,pend:zPend})")
        self.assertEqual(r["out"], [False] * 6 + [True, True])  # held for LOUPE_LAG_FRAMES frames, then the new crop
        self.assertEqual(r["cam"]["s"], 10)
        self.assertIsNone(r["pend"])

    def test_view_follows_the_camera_crop_after_the_swap(self):
        r = self.run_js(self.ZOOMED + "zLastRev=0;zRevAtSend=0;Object.assign(V,{s:10,cx:.43,cy:.47});loupeCommit();zCam={s:5,cx:.9,cy:.9};"
                        "for(var i=0;i<8;i++)loupeOnFrame({rev:1,on:true},null,null);"
                        "JSON.stringify({V:V,cam:zCam,cov:zCovers(zCrop(V,zCam,800,600),800,600)})")
        self.assertAlmostEqual(r["V"]["cx"], r["cam"]["cx"])
        self.assertAlmostEqual(r["V"]["cy"], r["cam"]["cy"])
        self.assertEqual((r["V"]["s"], r["cam"]["s"]), (10, 10))
        self.assertTrue(r["cov"])

    def test_view_stays_with_the_user_while_a_gesture_runs(self):
        r = self.run_js(self.ZOOMED + "zLastRev=0;zRevAtSend=0;Object.assign(V,{s:10,cx:.43,cy:.47});loupeCommit();"
                        "restT=1;Object.assign(V,{cx:.6});for(var i=0;i<8;i++)loupeOnFrame({rev:1,on:true},null,null);JSON.stringify(V)")
        self.assertEqual(r["cx"], 0.6)

    def test_click_is_not_a_command(self):
        r = self.run_js(self.ZOOMED + "loupeHold();JSON.stringify(calls)")  # loupeHold is all a pointer down does
        self.assertEqual(r, [])

    def test_nothing_sent_when_nothing_changed(self):
        r = self.run_js("loupeCommit();JSON.stringify(calls)")  # 1x and off already
        self.assertEqual(r, [])

    def test_error_ends_in_sync_without_throwing(self):
        r = self.run_js("mode='err';Object.assign(V,{s:5,cx:.4,cy:.4});loupeCommit();"
                        "JSON.stringify({calls:calls,msgs:msgs,V:V,want:zWant,busy:recBusy,shows:zCamShows})")
        self.assertEqual([c[0] for c in r["calls"]], ["/api/loupe", "/api/state"])  # no flood: one try, one state read
        self.assertEqual(r["msgs"], [["boom", True]])
        self.assertEqual((r["V"]["s"], r["want"]["on"], r["busy"], r["shows"]), (1, False, False, False))

    def test_error_and_dead_server_still_ends_soft_free(self):
        r = self.run_js("mode='dead';Object.assign(V,{s:5,cx:.4,cy:.4});zWant={on:true,ratio:5,x:.4,y:.4};loupeReconcile();"
                        "JSON.stringify({V:V,busy:recBusy})")
        self.assertEqual((r["V"]["s"], r["busy"]), (1, False))


if __name__ == "__main__":
    unittest.main()
