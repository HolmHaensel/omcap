"""Settings changed by another client (MCP) must reach the page: /api/state carries props_rev (counts /api/set)."""
import unittest

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

    def test_page_reloads_settings_on_change(self):
        html = open(server.__file__.replace("server.py", "web/index.html"), encoding="utf-8").read()
        self.assertIn("propsRevSeen(st.props_rev)", html)
        self.assertIn("rev!==propsRev&&!busy&&!editing", html)
        self.assertIn("(st.job&&st.job.running)||st.play", html)

    def test_remote_changes_flash(self):
        html = open(server.__file__.replace("server.py", "web/index.html"), encoding="utf-8").read()
        self.assertIn("props().then(()=>flashChanged(old))", html)
        self.assertIn("#props label.remote", html)

    def test_set_prop_counts_up(self):
        src = open(server.__file__, encoding="utf-8").read()
        i = src.index('elif path == "/api/set":')
        self.assertIn('state["props_rev"] += 1', src[i:i + 400])
        j = src.index('if path == "/api/afarea":')
        self.assertIn('state["props_rev"] += 1', src[j:j + 400])


if __name__ == "__main__":
    unittest.main()
