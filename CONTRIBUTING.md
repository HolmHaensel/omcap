# Contributing to E-M1 Capture

Thank you for helping keep old Olympus cameras in use! Contributions of every size are welcome:
testing with your camera, bug reports, ideas, translations, documentation and code.
No programming experience is needed to report a camera test or an idea.

## Ways to help

| What | How |
|---|---|
| **Test with your camera** | Open an issue with the *Camera test report* template: model, firmware, Wi-Fi/USB, what worked. Other bodies (E-M5 II, E-M10, PEN-F, E-M1 II …) are especially welcome. |
| **Report a bug** | *Bug report* template. Copy the Terminal output of the app. |
| **Suggest a feature** | *Feature request* template. Name the function as in your camera's manual and the page. |
| **Questions, show your setup** | GitHub Discussions. |
| **Code, docs, translations** | Pull request (see below). Look for issues labelled `good first issue` or `help wanted`. |

## Safety rules (please read)

E-M1 Capture talks to real cameras. These rules are not negotiable:

1. **Never write firmware.** No code in this project flashes or modifies camera firmware.
2. **Read only by default.** Anything that changes a camera setting, writes to the card or releases
   the shutter must only run when the user started the app with `--allow-write`
   (`WriteBlocked` in `omcap/camera.py`).
3. **No personal data in the repository:** no camera serial numbers, no photos of people, no
   home paths or e-mail addresses in logs, tests or screenshots. Test images must be synthetic.
4. Tests run **without a camera**. Camera tests are done by hand and described in the PR.

## Development setup

```sh
git clone https://github.com/HolmHaensel/omcap.git
cd omcap
python3 -m venv .venv
.venv/bin/pip install -e ".[usb,film]"
.venv/bin/python -B -m unittest discover -s tests     # all tests, no camera needed
.venv/bin/python -B -m omcap.server --allow-write    # http://127.0.0.1:8765
```

Code map:

| Path | Content |
|---|---|
| `omcap/server.py` | local HTTP server, API endpoints, connection handling |
| `omcap/camera.py` | Wi-Fi client (OI.Share protocol: `get_*`, `set_camprop`, `exec_*`) |
| `omcap/usb_camera.py` | USB client (PTP via libgphoto2) |
| `omcap/liveview.py` | Wi-Fi live view (RTP/UDP JPEG) |
| `omcap/web/index.html` | the whole user interface (one page, translation table `I18N`) |
| `omcap/exif.py`, `omcap/hsl.py` | EXIF reading, software HSL colour profiles |
| `design/` | design principles, tokens and the term list |
| `tests/` | offline tests |

## Conventions

- **Terms exactly as in the camera manual** (e.g. "LV super control panel", "AF target",
  "Sequential shooting/self-timer"). The list is in `design/DESIGN.md`.
- **All visible text** goes through the translation table (`I18N.en`, `tr()`, `data-i18n`).
  New languages are welcome: add a block next to `en`.
- **USB and Wi-Fi alike:** every feature states whether it works over USB and over Wi-Fi.
  If only one connection can do it, say why (no command / no PTP property) and update the
  feature table in `README.md`.
- **Code comments and docstrings in English.** Python 3.9+, standard library for Wi-Fi;
  optional extras (`gphoto2`, `numpy`, `rawpy`, `imageio`) only where needed.
- Small, focused pull requests; one topic each. Add or update tests.
- Commit messages: short imperative summary; mention the requirement ID if there is one
  (`REQ-F26: …`, see `REQUIREMENTS.md`).

## Pull request checklist

The PR template asks for: what changed, USB/Wi-Fi status, how you tested (offline tests,
which camera and connection), screenshots for UI changes, and that no personal data is included.

## Licence

By contributing you agree that your work is published under the project's licence,
[GPL-3.0-or-later](LICENSE).

"Olympus", "OM SYSTEM" and "OM-D" are trademarks of their owners; this project is not affiliated
with OM Digital Solutions.
