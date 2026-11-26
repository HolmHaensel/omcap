"""Settings changed by another client (MCP) must reach the page: /api/state carries props_rev (counts /api/set)."""
import json
import shutil
import subprocess
import unittest
from unittest import mock

from omcap import server


class PropsRev(unittest.TestCase):
    def test_state_carries_props_rev(self):
        class Stub:
            stage, lvqty = 0, "0320x0240"

            def __getattr__(self, n):
                return None

        class Live:
            running, age = False, 0
        old = (server.cam, server.live, server.conn_type, server.state["props_rev"])
        server.cam, server.live, server.conn_type = Stub(), Live(), "wifi"
        try:
            server.state["props_rev"] = 7
            self.assertEqual(server.public_state()["props_rev"], 7)
        finally:
            server.cam, server.live, server.conn_type, server.state["props_rev"] = old

    def test_page_looks_at_props_rev(self):
        html = open(server.__file__.replace("server.py", "web/index.html"), encoding="utf-8").read()
        self.assertIn("propsRevSeen(st.props_rev)", html)

    @unittest.skipUnless(shutil.which("osascript"), "needs the JavaScript engine of macOS (osascript)")
    def test_page_reloads_settings_on_change(self):
        html = open(server.__file__.replace("server.py", "web/index.html"), encoding="utf-8").read()
        fn = html[html.index("function propsRevSeen("):]
        fn = fn[:fn.index("\n}\n") + 3]
        code = """var propsRev,st={stage:0},ringDrag=false,document={activeElement:null},lastProps=null,loads=0,out=[];
        function setTimeout(f){f()} function props(){loads++;return {then:function(f){f()}}}
        function flashChanged(){} function loadAf(){}
        %s
        function look(rev){var n=loads;propsRevSeen(rev);out.push(loads-n)}
        look(1); look(1); look(2);                    // first look, unchanged, changed while idle
        st.job={running:true}; look(3); st.job=null;  // busy: waits
        st.play=true; look(3); st.play=false;         // Playback: waits
        ringDrag=true; look(3); ringDrag=false;       // ring drag: waits
        document.activeElement={matches:function(){return true}}; look(3); document.activeElement=null;  // list open
        look(3);                                      // idle again: reloads once
        JSON.stringify(out)""" % fn
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout.strip()), [0, 0, 1, 0, 0, 0, 0, 1])

    def test_remote_changes_flash(self):
        html = open(server.__file__.replace("server.py", "web/index.html"), encoding="utf-8").read()
        self.assertIn("props().then(()=>flashChanged(old))", html)
        self.assertIn("#props label.remote", html)

    def test_set_prop_counts_up(self):
        h = server.Handler.__new__(server.Handler)
        old = (server.cam, server.conn_type, server.state["props_rev"])
        server.cam, server.conn_type, server.state["props_rev"] = mock.MagicMock(), "wifi", 0
        try:
            with mock.patch.object(server, "ensure_idle"), mock.patch.object(server, "set_af_area"), \
                    mock.patch.object(server, "af_area", return_value={}):
                h._action("/api/set", {"prop": "isospeedvalue", "value": "200"})
                self.assertEqual(server.state["props_rev"], 1)
                h._action("/api/afarea", {"mode": "single"})  # AF mode / MF also shows in the settings
                self.assertEqual(server.state["props_rev"], 2)
        finally:
            server.cam, server.conn_type, server.state["props_rev"] = old


if __name__ == "__main__":
    unittest.main()
