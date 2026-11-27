"""Design system 1.0 (Quiet Precision V4.0): tokens match Figma, icons resolve, /ds/ route is safe,
and the JS unit tests of the components pass (REQ-D06)."""
import os
import re
import shutil
import subprocess
import unittest

import omcap.server as server

DS = os.path.join(os.path.dirname(server.__file__), "web", "ds")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Theme System V1.0, Figma node 32:482 (read 2026-11-27)
FIGMA = {
    "dark": dict(ground="#141414", surface="#282828", text="#F1EFE8", muted="#BDBDB7",
                 accent="#D4AA62", focus="#7EB89A", recording="#D65C5C"),
    "daylight": dict(ground="#F5F4F0", surface="#E7E5DF", text="#181818", muted="#595959",
                     accent="#87560F", focus="#256847", recording="#AD3434"),
    "astro": dict(ground="#080000", surface="#210606", text="#E45A5A", muted="#D25252",
                  accent="#FF7777", focus="#E45A5A", recording="#FF7777"),
}


def read(name):
    with open(os.path.join(DS, name), encoding="utf-8") as f:
        return f.read()


class Tokens(unittest.TestCase):
    def blocks(self):
        css = read("tokens.css")
        out = {}
        for theme in FIGMA:
            sel = r':root,\s*\[data-qp-theme="dark"\]' if theme == "dark" else rf'\[data-qp-theme="{theme}"\]'
            m = re.search(sel + r"\s*\{(.*?)\n\}", css, re.S)
            self.assertIsNotNone(m, theme)
            out[theme] = dict(re.findall(r"--qp-([a-z-]+):\s*([^;]+);", m.group(1)))
        return out

    def test_three_themes_match_figma(self):
        for theme, block in self.blocks().items():
            for k, v in FIGMA[theme].items():
                self.assertEqual(block.get(k, "").upper(), v, f"{theme} {k}")

    def test_same_token_names_in_every_theme(self):
        b = self.blocks()
        names = {t: {k for k in b[t] if k in FIGMA["dark"] or k.startswith("capture")} for t in b}
        self.assertEqual(names["dark"], names["daylight"])
        self.assertEqual(names["dark"], names["astro"])

    def test_astro_capture_is_outlined(self):
        b = self.blocks()
        self.assertEqual(b["astro"]["capture-fill"], "var(--qp-surface)")
        self.assertEqual(b["dark"]["capture-fill"], "var(--qp-text)")

    def test_components_use_tokens_not_raw_colours(self):
        css = read("components.css")
        raw = [h for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", css) if h.lower() not in ("#000",)]
        self.assertEqual(raw, [])


class Icons(unittest.TestCase):
    def test_gallery_icons_exist_in_sprite(self):
        ids = set(re.findall(r'<symbol id="i-([a-z0-9-]+)"', read("icons.svg")))
        self.assertEqual(len(ids), 47)
        gallery = re.search(r"const ICONS = \[(.*?)\];", read("gallery.html"), re.S).group(1)
        used = set(re.findall(r'"([a-z0-9-]+)"', gallery))
        self.assertEqual(used - ids, set())
        js = set(re.findall(r'icon\("([a-z0-9-]+)"', read("precision.js")))
        self.assertEqual(js - ids, set())

    def test_sprite_uses_current_colour_only(self):
        svg = read("icons.svg")
        self.assertNotIn("#F1EFE8", svg)
        self.assertNotIn("clip-path", svg)


class Route(unittest.TestCase):
    def test_serves_known_files(self):
        for name in ("tokens.css", "components.css", "precision.js", "views.js", "icons.svg", "gallery.html",
                     "fixtures/em1-capabilities-sample.json"):
            self.assertTrue(server.ds_path(name), name)

    def test_refuses_traversal_and_unknown_types(self):
        for bad in ("../server.py", "../../README.md", "/etc/passwd", "../web/index.html", "nope.css", "x.py"):
            self.assertIsNone(server.ds_path(bad), bad)


class Fixture(unittest.TestCase):
    def test_values_are_the_cameras_own(self):
        import json
        import xml.etree.ElementTree as ET
        fx = json.loads(read("fixtures/em1-capabilities-sample.json"))
        xml = os.path.join(ROOT, "camera", "desclist.xml")
        if not os.path.exists(xml):
            self.skipTest("camera/desclist.xml is local only")
        cam = {d.findtext("propname"): (d.findtext("enum") or "").split() for d in ET.parse(xml).getroot().iter("desc")}
        for k, v in fx["props"].items():
            self.assertEqual(v["values"], cam[k], k)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class NodeTests(unittest.TestCase):
    def test_component_logic(self):
        r = subprocess.run(["node", "--test", os.path.join(ROOT, "tests", "ds")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
