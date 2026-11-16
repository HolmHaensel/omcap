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
        self.assertIn("const LOUPE_LAG_FRAMES=2", h)
        for name in ("loupeReconcile", "loupeCommit", "loupeHold", "loupeOnFrame", "zRender"):
            self.assertIn("function %s(" % name, h)
        for name in ("zSnap", "zClamp", "zCrop"):
            self.assertIn("const %s=" % name, h)
        self.assertIn("X-Loupe-Rev", h)
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
    var calls=[],msgs=[],mode='ok',rev=0,z,px,py,usbZoom=true,loupeOn,tr=function(){return ''},performance={now:function(){return 0}};
    var el=function(){return {style:{},hidden:false,textContent:'',classList:{toggle:function(){},add:function(){},remove:function(){}},setAttribute:function(){}}};
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
        region = region.replace("async function loupeReconcile(", "function* __rec(").replace("await ", "yield ")
        region = region.replace("$(", "Q(")  # $ is the ObjC bridge in this engine
        region += "\nfunction loupeReconcile(){return __drive(__rec())}\n"
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

    def test_hold_sends_one_off_request(self):
        r = self.run_js("Object.assign(V,{s:5,cx:.5,cy:.5});loupeCommit();calls.length=0;loupeHold();loupeHold();"
                        "JSON.stringify({calls:calls,sent:zSent})")
        self.assertEqual(r["calls"], [["/api/loupe", {"on": False}]])  # the second hold has nothing left to turn off
        self.assertFalse(r["sent"]["on"])

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
