# E-M1 Capture

A local web app to control an **Olympus OM-D E-M1 (Mark I)** from a computer, over the camera's own
**Wi-Fi** or over **USB**. It runs on your computer and opens in the browser at
`http://127.0.0.1:8765`. Terms follow the camera's instruction manual.

> Unofficial project. Not affiliated with, endorsed by or supported by OM Digital Solutions or
> Olympus. "Olympus", "OM-D" and "OI.Share" are trademarks of their respective owners.
> Use at your own risk.

## Features

| Feature | Wi-Fi | USB |
|---|---|---|
| Live view with selectable size, zoom, Displayed Grid, overlay, second monitor | yes | yes (fixed size) |
| Tap the 9×9 AF grid to focus, AF target shown in green | yes | yes |
| AF Area (All, Single, Small, Group Target) | – | yes |
| Shutter button: Take picture, Press halfway (hold focus, then take picture) | yes | yes |
| LV super control panel: Shooting mode, shutter speed, aperture, exposure compensation, ISO, WB, drive, Picture Mode, Art filter | yes | most (mode dial only) |
| Aperture list limited to the attached lens (read from EXIF) | yes | untested |
| Movie: Start/Stop recording, movie shooting mode P/A/S/M | yes | – |
| Time lapse shooting, AE BKT, BULB / LIVE TIME / LIVECOMP | built, partly tested | built, partly tested |
| Playback: Index display, Calendar display, single-frame view, save to computer | yes | yes |
| Save to card only or card and computer | yes | yes |

The interface is in English; all texts are in one translation table (`I18N` in
`omcap/web/index.html`), so more languages can be added.

## Safety

- The app **never writes firmware**.
- It starts **read only**. Taking pictures and changing settings needs `--allow-write`.
- It only listens on `127.0.0.1` and refuses requests from other web pages.

## Requirements

- Python 3.9 or newer (macOS tested; Wi-Fi uses only the standard library)
- Olympus OM-D E-M1 Mark I (tested with firmware 4.6)
- For USB: `pip install gphoto2` (bundles libgphoto2)

## Install and run

```sh
python3 -m venv .venv
.venv/bin/pip install .          # Wi-Fi only
.venv/bin/pip install ".[usb]"   # with USB
.venv/bin/em1-capture --allow-write
```

Or straight from the source folder:

```sh
python3 -m omcap.server --allow-write
```

Then open <http://127.0.0.1:8765/> and pick the connection on the start screen.

Options: `--host` (camera IP, default `192.168.0.10`), `--port` (default `8765`),
`--data-dir` (where `captures/` and the preview cache `out/cache/` go; default: current folder).

### Wi-Fi

1. On the camera, start **Connection to Smartphone** (Playback Menu) with connection type **Private**.
2. Join the camera's Wi-Fi with your computer.
3. Start the app and choose **Wi-Fi connection**.

Opening Playback switches the camera to playback mode for faster medium-size previews; closing it
returns to shooting mode and restarts live view.

### USB (macOS)

1. Quit the Photos app.
2. Connect the camera; in its USB menu choose the third entry (computer + camera icon).
3. Start the app and choose **USB connection**. The app stops `ptpcamerad`, which otherwise
   holds the camera.

## Tests

```sh
python3 -m unittest discover -s tests
```

The tests use simulated camera answers and need no camera.

## License

GPL-3.0-or-later, see [LICENSE](LICENSE).
