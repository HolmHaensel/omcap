"""Partial Color ring: press and drag changes the colour live; only the newest colour is sent, one request at a time."""
import unittest

from omcap import server


class RingDrag(unittest.TestCase):
    def setUp(self):
        self.html = open(server.__file__.replace("server.py", "web/index.html"), encoding="utf-8").read()
        i = self.html.index("function colorRing(")
        self.ring = self.html[i:self.html.index("function renderProps(", i)]

    def test_drag_sends_the_newest_colour_one_at_a_time(self):
        for needle in ("pointerdown", "pointermove", "setPointerCapture", "while(want!==null&&want!==sent)",
                       "touchAction='none'", "lostpointercapture", "e.button!==0", "e.detail===0"):
            self.assertIn(needle, self.ring)

    def test_no_rebuild_while_dragging(self):
        self.assertIn("const editing=ringDrag||", self.html)


if __name__ == "__main__":
    unittest.main()
