"""The user follows on the page what the MCP server does: its POSTs are marked and listed in /api/state."""
import unittest

from omcap import mcp_server, server


class McpActivity(unittest.TestCase):
    def setUp(self):
        saved = (server.state["mcp_n"], list(server.state["mcp_log"]))
        self.addCleanup(lambda: server.state.update(mcp_n=saved[0], mcp_log=saved[1]))
        server.state.update(mcp_n=0, mcp_log=[])

    def test_note_keeps_last_ten_with_small_scalar_body(self):
        for i in range(12):
            server.note_mcp("/api/set?x=1", {"prop": "isospeedvalue", "value": str(i), "blob": "x" * 99, "d": {}})
        log = server.state["mcp_log"]
        self.assertEqual(server.state["mcp_n"], 12)
        self.assertEqual([e["n"] for e in log], list(range(3, 13)))
        self.assertEqual(log[-1]["path"], "/api/set")
        self.assertEqual(log[-1]["body"], {"prop": "isospeedvalue", "value": "11"})

    def test_error_is_kept_short(self):
        server.note_mcp("/api/afarea", {"field": 37}, "x" * 300)
        self.assertEqual(len(server.state["mcp_log"][0]["error"]), 120)

    def test_mcp_client_marks_its_posts(self):
        seen = {}

        class Opener:
            def open(self, req, timeout=None):
                seen.update(req.header_items())
                raise OSError("stop here")
        c = mcp_server.HttpClient(allow_write=True)
        c._opener = Opener()
        with self.assertRaises(Exception):
            c.post_json("/api/set", {"prop": "isospeedvalue", "value": "400"})
        self.assertEqual(seen.get("X-client"), "mcp")

    def test_page_shows_and_taps(self):
        html = open(server.__file__.replace("server.py", "web/index.html"), encoding="utf-8").read()
        for needle in ("mcpSeen(st.mcp_n,st.mcp_log)", 'id="mcpBox"', "function ghostTap(e)", "b.dataset.mode=o"):
            self.assertIn(needle, html)


if __name__ == "__main__":
    unittest.main()
