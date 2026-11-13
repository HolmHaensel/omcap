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
| Live view with selectable size, zoom, Displayed Grid, overlay, second monitor | yes | yes (size choice up to 1280×960 with the PTP backend on macOS; with libgphoto2 it needs 2.5.34.1 or later, see below) |
| USB backend (`--usb-backend`) | – | yes: `auto` (default on macOS) uses the app's own PTP layer and falls back to libgphoto2 (tested on macOS); Linux: libgphoto2, not tested |
| Tap the 9×9 AF grid to focus, AF target shown in green | yes | yes |
| AF Area (All Targets, Single Target, Small Target, Group Target) | – (no command over Wi-Fi) | yes |
| Focus ring (MF): Near/Far in three step sizes, AF mode MF or S-AF+MF | – (no command over Wi-Fi) | yes (tested 2026-11-13) |
| Shutter button: Take picture, Press halfway (hold focus, then take picture) | yes (Take picture focuses on the tapped AF point and takes 1.2–1.5 s; long exposures and Movie use the shutter button route) | yes (Take picture focuses on the tapped AF field) |
| Self-timer (Off, 2 s, 12 s; the button becomes Cancel self-timer while it runs) | yes | yes |
| New picture in the last-shot corner and Index display right after Take picture | yes (8.4 s after the click, of which 7.2 s is the camera's shot) | yes (5–6 s after the click; the camera reports new files) |
| LV super control panel: Shooting mode, shutter speed, aperture, exposure compensation, ISO, WB, drive, Picture Mode, Art filter | yes | most (mode dial only) |
| Shooting mode follows the mode dial, values reload by themselves (during live view) | not needed (the app sets the mode) | yes, tested: P, A, S, M, Movie read correctly; iAUTO, ART, SCN, PHOTO STORY show as P; after a shot iAUTO is shown from the picture's EXIF |
| M mode quick select: BULB, LIVE TIME, LIVECOMP, Off | yes (tested 2026-11-13) | yes (tested 2026-11-13) |
| AF mode, Metering mode, Flash mode, Record mode, Aspect ratio, Image stabilizer, Face priority in the LV super control panel | – (no command) | yes (tested) |
| Aperture list limited to the attached lens (read from EXIF) | yes | yes (after the first picture of the session; before that only the focal length) |
| Movie: Start/Stop recording, movie shooting mode P/A/S/M | yes (switches to Movie mode while recording) | Start/Stop recording: yes, in every shooting mode like the movie button (tested 2026-11-13); movie settings not built |
| Time lapse shooting, AE BKT | built, untested | yes, tested with the PTP backend (3 frames, 2026-11-13) |
| Quit E-M1 Capture button | yes (tested while connected and from the start screen) | yes (tested from the start screen; while connected not yet) |
| Playback: Index display, Calendar display, single-frame view, save to computer | yes | yes |
| Card list saved on the computer, shown at once when you connect (the camera's list follows) | yes | yes |
| Playback: shooting data (Overall display), line on thumbnails | yes | yes |
| Open in OM Workspace from the single-frame view (macOS, only when OM Workspace is installed) | yes (not tested yet) | yes (tested 2026-11-13) |
| Save to card only or card and computer | yes | yes |
| Free card space in the header | yes (free shots, live from the live view) | yes |
| Current focal length in the header, ISO with ISO Auto, shutter speed and aperture the camera uses in auto modes | yes (sent with the live view) | – (no live USB property found) |
| Battery level | yes (during live view, sent with the picture) | yes |
| Read-only settings (Anti-Shock, Silent, Noise Reduct., BULB/TIME Timer, Digital Tele-converter) | yes | – (no PTP property known) |
| Share Order: show, save all, reset | yes (in playback) | – (no PTP counterpart known) |
| Movie length in single-frame view | yes (in playback) | – (not built) |
| Turn off camera (click twice to confirm) | yes | – (Wi-Fi only) |
| Live view aids: Histogram, Highlight&Shadow, Peaking | yes | yes |
| HSL color profiles for ORF/JPG on the computer (`omcap.hsl`) | independent | independent |
| Webcam (OBS) button next to Second monitor | yes | yes (webcam view tested, button untested) |
| Save folder and file naming | yes | yes (untested) |
| HSL colour profiles in the app (HSL button, auto-apply, before/after) | yes | yes (untested) |
| Start by double-click, browser opens by itself | yes | yes |

**Not possible with the E-M1 Mark I:** a live level gauge (the camera sends no tilt over Wi-Fi; over
USB the tilt is only updated when the session starts), changing AF Area over Wi-Fi and the shooting mode
over USB (the camera offers no command for it).

**Planned (next releases):** Mac app with a menu bar icon, Windows over Wi-Fi, movie and focus stacking over USB (0.7), Star AF focus aid (star
sharpness while you turn the focus ring), subject detection in live view on the computer (face/eye,
later animals and birds; the E-M1 itself sends no face frames) with "Focus on subject", film looks and
a look lab on the computer. Ideas and wishes are welcome in [Discussions](https://github.com/HolmHaensel/omcap/discussions).

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
| Computer | macOS (tested), Python 3.9 or newer; Linux and Windows should work (not tested) | macOS (tested); Linux possible over libgphoto2 (not tested); not Windows (no libgphoto2) |
| Extra software | none (standard library only) | `gphoto2` Python package via `".[usb]"` (includes libgphoto2 for the fallback and Linux, and the libusb the own PTP backend uses on macOS, else Homebrew libusb) |
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

**Double-click** `E-M1 Capture.command` (macOS) in the project folder. The app starts and opens
the browser at <http://127.0.0.1:8765/>; the start screen shows which connection found the camera.
On Windows use `E-M1 Capture.bat` (Wi-Fi only, not tested yet). On Linux start it in the terminal (below).

Or in the Terminal (read only without `--allow-write`):

```sh
cd omcap
.venv/bin/em1-capture --allow-write
```

- Keep the window open while you use the app (see **Stop** below).
- Starting a second time just opens the browser again: the new window says *E-M1 Capture is already
  running* and ends (Terminal shows *Process completed*). That is normal, the app keeps running in the
  first window. To change between read only and `--allow-write`, stop the running app first.

### Stop

- Click **Quit E-M1 Capture** (top right, also on the start screen) and click it again to confirm. The camera connection is closed and the app ends; the page says you can close the tab.
- Or press **Ctrl+C** in the window where the app runs, or close that window.
- No such window (for example the app was started in the background)? Stop it in the Terminal:

  ```sh
  pkill -f 'omcap\.server|bin/em1-capture'
  ```

  On Windows close the window of `E-M1 Capture.bat`.
- As long as the app runs, <http://127.0.0.1:8765/> keeps working in the browser, also after
  closing the browser tab.
- `--no-browser` starts without opening the browser; `--timing` prints how long each request takes.
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

USB backend: `--usb-backend auto` (default on macOS: PTP layer, libgphoto2 if it cannot connect),
`ptp` (PTP layer only) or `gphoto2` (libgphoto2 only; default on Linux). `GET /api/status` reports the backend in use.

Notes: the first connect reads the camera's card index once (about 40 s with the PTP backend, the
card list saved on the computer is shown meanwhile); later connects take 7–9 s, because the index is
saved on the computer. Measured on macOS with about 2950 files and the PTP backend:

| | PTP backend (macOS default) | libgphoto2 (fallback) |
|---|---|---|
| Connect | 7–9 s (44.8 s without saved index) | about 9 s, card index 51–72 s in the background |
| Live view 1024×768 | 19.5–26.4 fps | 14–20.6 fps |
| Live view 1280×960 | 15.0 fps | 13.8–15 fps (needs the newer libgphoto2, see below) |
| Focus by tap | 0.4–0.6 s | 1.3–1.5 s |
| Take picture | 4.5–4.8 s; files in the list at once | 4.7–5.3 s |

The shooting mode follows the mode dial during live view (both backends, tested); each turn rebuilds the
USB session (8–10 s), so quick turns in a row show only the last position. Other settings changed on the camera itself are picked up with **reload** in
the LV super control panel (rebuilds the USB session, about 9 s with libgphoto2). After unplugging and plugging the
cable in again while the app runs, connecting may fail with *Could not claim the USB device*:
stop the app and start it again.

### Using USB on Linux (possible, not tested yet)

The USB connection runs over libgphoto2, which is native on Linux; the `gphoto2` Python package ships
wheels with libgphoto2 for Linux (x86_64, aarch64). Install as above with `".[usb]"`, then:

- Desktop file managers (GVFS/KDE) may mount the camera first: unmount it, or stop the mounting service
  (e.g. `gvfs-gphoto2-volume-monitor`) before you start the app.
- Your user needs access to the USB device: libgphoto2's udev rules (package `libgphoto2` / `libgphoto2-6`) do
  this; otherwise run the app with the right group or a udev rule for vendor `07b4`, product `0130`.
- Steps 2 and 3 above apply as on macOS; step 1 and `ptpcamerad` are macOS only.

Reports from Linux users are welcome (open an issue with distribution, camera firmware and what worked).

### Larger USB live view (optional)

On macOS the default PTP backend already offers **Size** over USB up to 1280×960; no extra build is needed.
Only the libgphoto2 fallback needs the steps below: libgphoto2 2.5.34 (bundled with the `gphoto2` Python
package) fixes the USB live view at 1024×768. The development version of libgphoto2 (2.5.34.1 or later)
keeps a chosen size (13.8 fps measured at 1280×960). Until a release contains it, build it yourself (macOS, Homebrew):

```sh
brew install autoconf automake libtool gettext pkgconf libusb libexif
git clone https://github.com/gphoto/libgphoto2.git ~/src/libgphoto2 && cd ~/src/libgphoto2
autoreconf -is && ./configure --prefix="$HOME/.local/libgphoto2-dev" && make -j4 && make install
```

Then, in your `omcap` folder (the one from the installation above):

```sh
PKG_CONFIG_PATH="$HOME/.local/libgphoto2-dev/lib/pkgconfig" .venv/bin/pip install --force-reinstall --no-cache-dir --no-binary gphoto2 gphoto2
.venv/bin/python -c "import gphoto2 as gp; print(gp.gp_library_version(gp.GP_VERSION_SHORT)[0])"   # 2.5.34.1 or later
```

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
.venv/bin/python -B -m unittest discover -s tests
```

The tests use simulated camera answers and need no camera.

## Contributing

Camera test reports, bug reports, ideas, translations and code are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md); questions go to
[Discussions](https://github.com/HolmHaensel/omcap/discussions).

## License

GPL-3.0-or-later, see [LICENSE](LICENSE).
