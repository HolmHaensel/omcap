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

| | Wi-Fi | USB |
|---|---|---|
| Camera | OM-D E-M1 Mark I (tested: firmware 4.6) | same |
| Computer | macOS (tested), Python 3.9 or newer | same |
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

Start (read only without `--allow-write`):

```sh
.venv/bin/em1-capture --allow-write
```

Open <http://127.0.0.1:8765/>; the start screen shows which connection found the camera.
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

## Tests

```sh
python3 -m unittest discover -s tests
```

The tests use simulated camera answers and need no camera.

## License

GPL-3.0-or-later, see [LICENSE](LICENSE).
