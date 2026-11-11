# E-M1 Capture

A local web app to control an **Olympus OM-D E-M1 (Mark I)** from a computer, over the camera's own
**Wi-Fi** or over **USB**. It runs on your computer and opens in the browser at
`http://127.0.0.1:8765`. Terms follow the camera's instruction manual.

> Unofficial project. Not affiliated with, endorsed by or supported by OM Digital Solutions or
> Olympus. "Olympus", "OM-D" and "OI.Share" are trademarks of their respective owners.
> Use at your own risk.

## Why this project

I love Olympus cameras. The OM-D E-M1 Mark I is a fantastic camera to learn photography with:
you can get one for about 129 € and it has a huge feature set. Sadly its software is no longer
maintained — OI.Share, OM Workspace and OM Capture feel slow, and there was never Wi-Fi tethering
on the computer, although the phone app (OI.Share) has always used it.

Over Wi-Fi you also no longer need the camera's special Olympus USB cable, which is hard to find
and expensive today, and you still get full remote control from the computer.

So I simply tried to build it, with hardly any programming experience. E-M1 Capture is my
contribution to the community, so these great cameras can keep taking pictures for many years.
Maybe OM System finds an idea or two here for their future cameras.

Contributions, tests with other bodies and ideas are very welcome.

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
| Free card space in the header | yes | yes |
| Battery level | – (no command) | yes |
| Read-only settings (Anti-Shock, Silent, Noise Reduct., BULB/TIME Timer, Digital Tele-converter) | yes | – (unknown) |
| Share Order: show, save all, reset | yes (in playback) | – |
| Movie length in single-frame view | yes (in playback) | – |
| Turn off camera | built, untested | – |
| Live view aids: Histogram, Highlight&Shadow, Peaking | yes | yes |
| HSL color profiles for ORF/JPG on the computer (`omcap.hsl`) | independent | independent |
| Webcam (OBS) button next to Second monitor | yes | yes (untested) |
| Save folder and file naming | yes | yes (untested) |
| HSL colour profiles in the app (HSL button, auto-apply, before/after) | yes | yes (untested) |
| Start by double-click, browser opens by itself | yes | yes |

**Planned:** Star AF focus aid (star sharpness while you turn the focus ring), subject detection in
live view (face/eye, later animals and birds) with "Focus on subject", film looks and a look lab on the
computer. Ideas and wishes are welcome in [Discussions](https://github.com/HolmHaensel/omcap/discussions).

The interface is in English; all texts are in one translation table (`I18N` in
`omcap/web/index.html`), so more languages can be added.

## Safety

- The app **never writes firmware**.
- It starts **read only**. Taking pictures and changing settings needs `--allow-write`.
- It only listens on `127.0.0.1` and refuses requests from other web pages.

## Requirements

| | Wi-Fi | USB |
|---|---|---|
| Camera | OM-D E-M1 Mark I (tested: firmware 4.6) | same |
| Computer | macOS (tested), Python 3.9 or newer; Windows probably works (not tested) | macOS only (libgphoto2 is not available on Windows) |
| Extra software | none (standard library only) | `gphoto2` Python package (includes libgphoto2) |
| Cable / network | the camera's own Wi-Fi | USB cable |

## Installation

```sh
git clone https://github.com/HolmHaensel/omcap.git
cd omcap
python3 -m venv .venv
.venv/bin/pip install .          # Wi-Fi
.venv/bin/pip install ".[usb]"   # Wi-Fi and USB
```

### Start

**Double-click** `E-M1 Capture.command` (macOS) in the `omcap` folder. The app starts and opens
the browser at <http://127.0.0.1:8765/>; the start screen shows which connection found the camera.
On Windows use `E-M1 Capture.bat` (Wi-Fi only, not tested yet).

Or in the Terminal (read only without `--allow-write`):

```sh
cd omcap
.venv/bin/em1-capture --allow-write
```

- Keep the window open while you use the app; stop it with **Ctrl+C** or close the window.
- Starting a second time just opens the browser again; the app tells you it is already running.
- `--no-browser` starts without opening the browser.
- The launcher files start with `--allow-write`; remove it there for a read-only start.
- The app works **offline**. It runs only on your computer and loads nothing from the internet;
  internet is needed once for the installation.

Pictures saved to the computer go to `captures/` in the current folder (change with `--data-dir`).

## Using Wi-Fi

1. Camera: **Setup Menu → Wi-Fi Settings → Wi-Fi Connect Settings → Private** (once).
   Remote control only works with Private, not One-Time.
2. Camera: **Playback Menu → Connection to Smartphone**. The monitor shows SSID and password.
3. Computer: join that Wi-Fi network (the password is saved; next time it connects by itself).
4. Start the app and choose **Wi-Fi connection**.

### Best Wi-Fi settings

Measured with the E-M1 Mark I:

| Live view size | Frame rate | Use |
|---|---|---|
| 640×480 | about 22 fps | smoothest picture |
| **800×600** (default) | about 18 fps | best balance |
| 1024×768 | about 9 fps | checking details |
| 1280×960 | about 7 fps, about 11 % frames dropped | checking focus only |

- Keep the camera within a few metres and do not cover the grip: the Wi-Fi antenna is inside
  it (manual p. 124). Microwaves and cordless phones nearby slow the connection down.
- Wi-Fi drains the battery faster; start with a full battery or use the AC adapter.
- Mac settings for the camera network (System Settings → Wi-Fi → Details of the camera's network):
  **Private Wi-Fi address: Off** (no rotating address) and **Limit IP address tracking: Off**.
  Keep other background network features to a minimum; then the connection is fast and steady.
- The camera network has no internet. Turn off **Auto-Join** for other known networks
  (System Settings → Wi-Fi) so the computer does not switch away while you shoot. A cable
  network can stay connected for internet at the same time.
- Live view arrives as UDP on port 5555. If the macOS firewall is on, allow incoming
  connections for Python when asked; otherwise live view shows "no signal".
- Opening Playback switches the camera to playback mode (live view pauses) for fast
  medium-size previews; previews are cached, so a second look is instant.
- Over Wi-Fi the AF Area mode and the movie record mode cannot be changed (no command for it).

## Using USB (macOS)

1. Quit the **Photos** app (it grabs the camera).
2. Camera: **Custom Menu → USB Mode → Auto** (or the computer + camera setting).
3. Connect the cable; in the camera's USB menu choose the **third entry (computer + camera icon)**.
4. Start the app and choose **USB connection**. The app stops the macOS service
   `ptpcamerad`, which would otherwise hold the camera.

Notes: live view runs at about 15 fps with a fixed size. The shooting mode follows the mode
dial. Settings changed on the camera itself are picked up with **reload** in the LV super
control panel (rebuilds the USB session, about 9 s).

## HSL color profiles (software)

Modelled on the PEN-F front-dial COLOR mode (12 sectors, hue/saturation/lightness −7…+7,
three profile slots), applied on the computer to ORF or JPG files. Needs `pip install ".[film]"`.

```sh
python -m omcap.hsl IMG.ORF --profile "Teal & orange" --out out/hsl --sheet
python -m omcap.hsl IMG.JPG --profile my_profile.json
```

ORF gives a 16-bit TIFF, JPG a JPEG, always in `--out` (default `out/hsl/`). `--sheet` adds a
before/after sheet and a colour wheel chart. Presets: `omcap/data/hsl_presets.json`. Sector
angles and per-step gains are approximations, not the camera's values.

## Use as webcam (OBS)

Works with Wi-Fi and USB. Start the app, connect, and press **Start live view**; the
live view must keep running. Then:

1. Press **Webcam (OBS)** next to **Second monitor**: it opens the webcam view in a new window and
   copies the full link to the clipboard. In OBS add a **Browser Source** with the URL `http://127.0.0.1:8765/?view=webcam`
   (optional letterbox size: `http://127.0.0.1:8765/?view=webcam&w=1280&h=720`; set the same
   width and height in the source). The page shows only the live image on black, scaled to fit.
2. In OBS press **Start Virtual Camera**; video apps (Zoom, Teams, browsers) then list
   "OBS Virtual Camera".
3. Audio is not part of the camera stream: add a microphone as a separate audio source in OBS.

## Tests

```sh
python3 -m unittest discover -s tests
```

The tests use simulated camera answers and need no camera.

## Contributing

Camera test reports, bug reports, ideas, translations and code are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md); questions go to
[Discussions](https://github.com/HolmHaensel/omcap/discussions).

## License

GPL-3.0-or-later, see [LICENSE](LICENSE).
