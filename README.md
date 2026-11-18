# E-M1 Capture

**Remote control and tethering for the Olympus OM-D E-M1 (Mark I) – over the camera's own Wi-Fi or over USB.**
A small web app that runs on your computer and opens in the browser at `http://127.0.0.1:8765`.
All names follow the camera's instruction manual.

> Unofficial project. Not affiliated with, endorsed by or supported by OM Digital Solutions or
> Olympus. "Olympus", "OM-D" and "OI.Share" are trademarks of their respective owners.
> Use at your own risk.

![E-M1 Capture over USB: live view with the 9×9 AF grid and the focused field in green, LV super control panel, AF target, movie, shooting options and the shutter buttons](design/screenshots/app-usb-live-view.jpg)

*E-M1 Capture 0.7 with the E-M1 Mark I over USB: live view with AF grid (focused field in green), LV super control panel and Take picture.*

## Highlights

- **Wi-Fi tethering on the computer** – something Olympus never offered (only the phone app OI.Share used Wi-Fi). No special Olympus USB cable needed.
- **USB tethering** with its own fast USB layer: live view at **30 fps**, focus by tap in about half a second.
- **Use the camera as a webcam** (OBS) over Wi-Fi or USB.
- **The LV super control panel** – shooting mode, shutter speed, aperture, ISO, WB, Picture Mode, Art filter and more.
- **Focus Stacking, focus ring and level gauge** from the computer (USB).
- **Playback** with Index and Calendar display, shooting data and saving to the computer.
- **Works on a phone, too** – open the app on your phone in the home network.
- **Safe by default:** never touches the firmware, starts read only, stays on your computer unless you start it with `--lan`.

## Why this project

I love Olympus cameras. The OM-D E-M1 Mark I is a fantastic camera to learn photography with:
you can get one for about 129 € and it has a huge feature set. Sadly its software is no longer
maintained – OI.Share, OM Workspace and OM Capture feel slow, and there was never Wi-Fi tethering
on the computer, although the phone app has always used it.

So I simply tried to build it, with hardly any programming experience. E-M1 Capture is my
contribution to the community, so these great cameras can keep taking pictures for many years.
Maybe OM System finds an idea or two here for their future cameras.

Contributions, tests with other bodies and ideas are very welcome.

**Other cameras (PEN-F):** the app is built and tested on the E-M1 Mark I. A user reports running it
successfully with an **Olympus PEN-F**, also with PEN-F style COLOR profiles (the app has its own
[HSL color profiles](#hsl-color-profiles)). This is tested by users, not by the maintainer; some controls may
differ on the PEN-F. Please tell us what works on your body in [Discussions](https://github.com/HolmHaensel/omcap/discussions).

## Quick start

```sh
git clone https://github.com/HolmHaensel/omcap.git
cd omcap
python3 -m venv .venv
.venv/bin/pip install ".[usb]"     # Wi-Fi and USB (Wi-Fi only: .venv/bin/pip install .)
```

1. Connect the camera: [over Wi-Fi](#using-wi-fi) or [over USB](#using-usb).
2. **Double-click** `E-M1 Capture.command` (macOS). The browser opens and the start screen shows which connection found the camera.
3. Click **Connect** – or just wait: the app connects by itself to the camera used last time.

More in [Start and stop](#start-and-stop).

## Features

✅ works (tested on the camera) · 🟡 built, not tested on the camera yet · – not possible or not built (reason in the note)

### Live view

| Feature | Wi-Fi | USB | Note |
|---|---|---|---|
| Live view with zoom, Displayed Grid and overlay | ✅ | ✅ | |
| Zoom (USB): 1× and ×3–×14 are the camera's own Zoom AF and replace the screen zoom; click = focus, drag = move, wheel/pinch = smooth zoom that snaps to the camera's ratios at rest and turns sharp (Wi-Fi keeps the 1×/2×/4× screen zoom) | – | 🟡 | no Wi-Fi command (`exec_takemisc ctrlzoom` is the lens power zoom); AF in the zoomed view uses the screen centre, and the camera has no AF with Four Thirds lenses while zoomed (manual p.56, untested); USB both layers; camera-checked by hand 2026-11-16 (on/off, ratios, arrows); smooth zoom (drag, wheel and overview map) tried in the browser with the camera 2026-11-18, pinch on touch not yet tried; click focus (half press 1, release 5) not camera-tested (REQ-F54) |
| Live view size (up to 1280×960) | ✅ | ✅ | USB: with the app's own USB layer (macOS default); with libgphoto2 see [Larger USB live view](#larger-usb-live-view-libgphoto2) |
| Histogram, Highlight&Shadow, Peaking | ✅ | ✅ | Peaking follows the focus best at a live view size of 640×480 or more |
| Frames per second shown next to the live view size (and "libgphoto2" when USB uses the slower fallback) | ✅ | 🟡 | same page code; not yet looked at over USB |
| Level gauge (horizon line and tilt dot, "Level ✓", optional sound, "Hold angle") | – | ✅ | the camera sends no tilt over Wi-Fi; USB: own USB layer only, not with libgphoto2 |
| Free card space in the header | ✅ | ✅ | |
| Battery level in the header | – | 🟡 | USB: only a rough level (the camera reports coarse steps, 100 or 50); Wi-Fi: the value the camera sends is not the battery level, so it is not shown |
| Current focal length; ISO with ISO Auto ("now 800"); shutter speed and aperture the camera uses in auto modes | ✅ | – | sent with the Wi-Fi live view; no live USB value found |

### Focus

| Feature | Wi-Fi | USB | Note |
|---|---|---|---|
| Tap the 9×9 AF grid to focus, AF target in green | ✅ | ✅ | |
| AF frame on tap (white focusing, green in focus, red no focus) | ✅ | ✅ | |
| "In focus" / "No focus" chip | ✅ | ✅ | Wi-Fi after a tap; USB also after Press halfway and Take picture. With S-AF the camera only releases in focus |
| AF Area (All Targets, Single Target, Small Target, Group Target) | – | ✅ | no Wi-Fi command |
| Focus ring (MF): Near/Far in three step sizes | – | ✅ | AF mode MF or S-AF+MF; no Wi-Fi command |
| Focus Stacking On/Off (8 frames, merged in the camera, P/A/S/M) | – | ✅ | no Wi-Fi command |

### Shooting

| Feature | Wi-Fi | USB | Note |
|---|---|---|---|
| Take picture, Press halfway (hold focus, then take picture) | ✅ | ✅ | focuses on the tapped AF point; Wi-Fi: long exposures and Movie use the shutter button route; USB: the Press halfway button not re-tested since its redesign |
| Shutter blackout: short black frame over the live view on Take picture | ✅ | ✅ | |
| Self-timer (Off, 2 s, 12 s, cancel while it runs) | ✅ | ✅ | |
| New picture in the corner and in the Index display right after the shot | ✅ | ✅ | Wi-Fi about 8 s (7 s of it is the camera's shot), USB 5–6 s after the click |
| The corner picture fades out after 6 s | 🟡 | 🟡 | |
| M mode quick select: BULB, LIVE TIME, LIVECOMP | ✅ | ✅ | |
| Movie: Start/Stop recording, movie shooting mode P/A/S/M | ✅ | ✅ | Wi-Fi switches to Movie mode (movie record mode cannot be changed over Wi-Fi); USB works like the REC button (not in PHOTO STORY and some SCN modes); movie settings over USB not built |
| Time lapse, AE BKT | 🟡 | ✅ | |
| Save to card only, or to card and computer; save folder and file names | ✅ | 🟡 | not tested over USB |

### Camera settings

| Feature | Wi-Fi | USB | Note |
|---|---|---|---|
| LV super control panel: shutter speed, aperture, exposure compensation, ISO, WB, drive, Picture Mode | ✅ | ✅ | |
| Art filter | ✅ | 🟡 | USB: not tested in ART mode |
| Partial Color colour ring (ART and Picture Mode Partial Color; 18 colours, laid out like the camera's ring) | ✅ | – | USB: the camera offers no value for the colour, only selecting Partial Color |
| Shooting mode | ✅ | – | USB: set by the mode dial; the app follows the dial and reloads the values (tested; iAUTO, ART, SCN, PHOTO STORY show as P) |
| AF mode, Metering, Flash mode, Record mode, Aspect ratio, Image stabilizer, Face priority | – | ✅ | no Wi-Fi command |
| Aperture list limited to the attached lens | ✅ | ✅ | USB after the first picture of the session |
| Read-only values: Anti-Shock, Silent, Noise Reduct., BULB/TIME Timer, Digital Tele-converter | ✅ | – | no USB property known |
| Turn off camera (click twice) | ✅ | – | Wi-Fi only |

### Playback

| Feature | Wi-Fi | USB | Note |
|---|---|---|---|
| Index display, Calendar display, single-frame view, save to computer | ✅ | ✅ | |
| Card list saved on the computer, shown at once when you connect | ✅ | ✅ | |
| Shooting data (Overall display), line on thumbnails | ✅ | ✅ | |
| Pinch zoom and swipe between pictures (phone, trackpad, Magic Mouse, Shift + wheel) | ✅ | 🟡 | same page code; not tried separately over USB |
| Open in OM Workspace (macOS, if installed) | 🟡 | ✅ | |
| HSL color profiles (HSL button, before/after) | ✅ | 🟡 | |
| Share Order: show, save all, reset | ✅ | – | no USB counterpart known |
| Erase selected pictures from the card (Select → Erase, JPG and ORF together, asks first) | – | ✅ | no Wi-Fi command; protected pictures are refused by the camera and kept; tested with the own USB layer, libgphoto2 not tested |
| Movie length in the single-frame view | ✅ | – | not built for USB |

### Phone, second monitor and webcam

| Feature | Wi-Fi | USB | Note |
|---|---|---|---|
| Open the app on a phone in the home network (QR code behind **Phone**) | ✅ | 🟡 | start with `--lan`, see [On a phone](#on-a-phone) |
| Phone view: live view size picked by itself, no computer-only windows | ✅ | 🟡 | Wi-Fi follows the screen and the signal; USB always 1024×768 at 30 fps |
| Second monitor (live view or last picture in its own window) | ✅ | ✅ | live view window tested 2026-11-15 |
| Webcam (OBS) | ✅ | ✅ | webcam view tested; the **Webcam (OBS)** button itself not tested; see [Use as webcam](#use-as-webcam-obs) |

### Connection

| Feature | Wi-Fi | USB | Note |
|---|---|---|---|
| Start by double-click, browser opens by itself | ✅ | ✅ | |
| Start screen connects by itself to the camera used last time (**Stay here** stops it) | ✅ | 🟡 | |
| Camera lost and back (cable pulled, camera off, Wi-Fi dropped): waits quietly and goes on by itself | 🟡 | ✅ | Wi-Fi: the live view restarts once the camera answers again (restart not yet seen on the camera) |
| Two connect requests at once make one connection (two tabs, a phone) | 🟡 | ✅ | |
| Quit E-M1 Capture button | ✅ | 🟡 | USB tested from the start screen, not while connected |

**Not possible with the E-M1 Mark I:** the level gauge over Wi-Fi (no tilt data); AF Area, the movie record mode, Focus Stacking and the
focus ring over Wi-Fi; setting the shooting mode over USB – the camera offers no command for it.

**Planned:** Mac app with a menu bar icon, Windows over Wi-Fi, movie settings and Focus BKT over USB,
subject detection in the live view on the computer (face/eye, later animals and birds) with "Focus on subject",
film looks, and later a Star AF focus aid. Ideas and wishes are welcome in [Discussions](https://github.com/HolmHaensel/omcap/discussions).

The interface is in English; all texts are in one translation table (`I18N` in `omcap/web/index.html`),
so more languages can be added.

## Speed

Measured with the E-M1 Mark I (firmware 4.6), a Mac and about 2950 pictures on the card, 2026-11-12 to 2026-11-15.

| | Wi-Fi | USB (own USB layer, macOS) |
|---|---|---|
| Connect | about 1 s (card list follows in the background) | about 5 s (later connects); about 45 s the very first time, because the card index is read once |
| Live view 640×480 | 30 fps | 30 fps |
| Live view 800×600 (Wi-Fi default) | about 21 fps | 30 fps |
| Live view 1024×768 (USB default) | about 12 fps | 30 fps |
| Live view 1280×960 | about 8 fps | 15 fps |
| Focus by tap | about 0.4 s | 0.4–0.6 s |
| Take picture | 1.2–1.5 s | about 4.5 s, new files in the list at once |

- 30 fps is the camera's own live view rate; at 1280×960 it sends half of that.
- Of the 5 s for a USB connect, about 4.7 s is the camera itself switching to computer control.
- With the libgphoto2 fallback USB is slower: 14–21 fps at 1024×768, focus 1.3–1.5 s, connect about 9 s
  (card index 51–72 s in the background).

## Safety

- The app **never writes firmware**.
- It starts **read only**. Taking pictures and changing settings needs `--allow-write`
  (the double-click launchers start with it; remove it there for a read-only start).
- It only listens on `127.0.0.1` (with `--lan` also in the home network, with a key) and refuses requests from other web pages.
- It works **offline** and loads nothing from the internet (internet is needed once for the installation).

## Requirements

| | Wi-Fi | USB |
|---|---|---|
| Camera | OM-D E-M1 Mark I (tested: firmware 4.6) | same |
| Computer | macOS (tested), Python 3.9 or newer; Linux and Windows should work (not tested) | macOS (tested); Linux over libgphoto2 (not tested); not Windows |
| Extra software | none (Python standard library only) | `pip install ".[usb]"` (gphoto2 package with libgphoto2 and libusb) |
| Connection | the camera's own Wi-Fi | USB cable |

## Start and stop

**Start:** double-click `E-M1 Capture.command` (macOS) or `E-M1 Capture.bat` (Windows, Wi-Fi only, not tested).
Or in the Terminal (Linux too):

```sh
cd omcap
.venv/bin/em1-capture --allow-write     # without --allow-write: read only
```

- Keep the window open while you use the app.
- Starting a second time just opens the browser again (*E-M1 Capture is already running*). To switch between
  read only and `--allow-write`, stop the running app first.
- As long as the app runs, <http://127.0.0.1:8765/> keeps working, also after closing the browser tab.

**Stop:** click **Quit E-M1 Capture** (top right, also on the start screen) twice – the camera connection is closed and the page
says you can close the tab. Or press **Ctrl+C** in the app's window, or close it (Windows: close the window of
`E-M1 Capture.bat`). Without a window (started in the background):

```sh
pkill -f 'omcap\.server|bin/em1-capture'
```

**Options**

| Option | What it does |
|---|---|
| `--allow-write` | allow taking pictures and changing settings |
| `--lan` | let a phone in the home network open the app ([On a phone](#on-a-phone)) |
| `--usb-backend auto\|ptp\|gphoto2` | USB layer: `auto` (macOS default: own layer, libgphoto2 if it cannot connect), `ptp` (own layer only), `gphoto2` (libgphoto2 only, Linux default); `GET /api/status` shows the one in use |
| `--data-dir DIR` | where pictures saved to the computer go (default `captures/` in the current folder) |
| `--no-browser` | start without opening the browser |
| `--timing` | print how long each request takes |

## Using Wi-Fi

1. Camera: **Setup Menu → Wi-Fi Settings → Wi-Fi Connect Settings → Private** (once).
   Remote control only works with Private, not One-Time.
2. Camera: **Playback Menu → Connection to Smartphone**. The monitor shows SSID and password.
3. Computer: join that Wi-Fi network (it connects by itself next time).
4. Start the app and choose **Wi-Fi connection**.

**Tips**

- **Live view size:** 640×480 is the smoothest, 800×600 (default) the best balance, 1024×768 and 1280×960 for checking details and focus (see [Speed](#speed)). On a phone the app picks the size itself and steps down when frames come slowly ("Auto · 800×600").
- Keep the camera within a few metres and do not cover the grip – the Wi-Fi antenna is inside it (manual p. 124).
  Microwaves and cordless phones nearby slow the connection down.
- Wi-Fi drains the battery faster; start with a full battery or use the AC adapter.
- On the Mac, in the details of the camera's network (System Settings → Wi-Fi): **Private Wi-Fi address: Off** and
  **Limit IP address tracking: Off**. Keep other background network features to a minimum.
- The camera network has no internet. Turn off **Auto-Join** for other known networks so the computer does not switch
  away while you shoot. A cable network can stay connected for internet at the same time.
- Live view arrives as UDP on port 5555. If the macOS firewall is on, allow incoming connections for Python when
  asked; otherwise the live view shows "no signal".
- Opening Playback switches the camera to playback mode (live view pauses) for fast medium-size previews; previews are cached.

## Using USB

**macOS**

1. Quit the **Photos** app (it grabs the camera).
2. Camera: **Custom Menu → USB Mode → Auto** (or the computer + camera setting).
3. Connect the cable; in the camera's USB menu choose the **third entry (computer + camera icon)**.
4. Start the app and choose **USB connection**. The app stops the macOS service `ptpcamerad`, which would otherwise hold the camera.

**Good to know**

- The first connect reads the camera's card index once (about 45 s; the card list saved on the computer is shown
  meanwhile). Later connects take about 5 s.
- The shooting mode follows the mode dial during live view; each turn reconnects the camera (8–10 s), so quick
  turns in a row show only the last position. Other settings changed on the camera itself come in with **reload**
  in the LV super control panel (about 9 s with libgphoto2).
- Cable pulled while connected? The live view shows *Camera not found. Is the cable plugged in?* Plug it in and choose
  the computer + camera entry again – the app reconnects by itself after a few seconds. Only if that fails, stop the
  app and start it again.

**Linux (possible, not tested yet)**

USB runs over libgphoto2; the `gphoto2` Python package ships it for Linux (x86_64, aarch64). Install with `".[usb]"`, then:

- File managers (GVFS/KDE) may mount the camera first: unmount it or stop the mounting service
  (e.g. `gvfs-gphoto2-volume-monitor`).
- Your user needs access to the USB device: libgphoto2's udev rules (package `libgphoto2` / `libgphoto2-6`) do this,
  or a udev rule for vendor `07b4`, product `0130`.
- Steps 2 and 3 above apply; step 1 and `ptpcamerad` are macOS only.

Reports from Linux users are welcome (open an issue with distribution, camera firmware and what worked).

### Larger USB live view (libgphoto2)

Only needed for the libgphoto2 fallback – on macOS the app's own USB layer already offers sizes up to 1280×960.
libgphoto2 2.5.34 (bundled with the `gphoto2` package) fixes the USB live view at 1024×768; the development
version (2.5.34.1 or later) keeps a chosen size. Until a release contains it, build it yourself (macOS, Homebrew):

```sh
brew install autoconf automake libtool gettext pkgconf libusb libexif
git clone https://github.com/gphoto/libgphoto2.git ~/src/libgphoto2 && cd ~/src/libgphoto2
autoreconf -is && ./configure --prefix="$HOME/.local/libgphoto2-dev" && make -j4 && make install
```

Then, in your `omcap` folder:

```sh
PKG_CONFIG_PATH="$HOME/.local/libgphoto2-dev/lib/pkgconfig" .venv/bin/pip install --force-reinstall --no-cache-dir --no-binary gphoto2 gphoto2
.venv/bin/python -c "import gphoto2 as gp; print(gp.gp_library_version(gp.GP_VERSION_SHORT)[0])"   # 2.5.34.1 or later
```

## On a phone

Start the app with `--lan` (for example `.venv/bin/em1-capture --allow-write --lan`). On the computer click **Phone**
(start screen or header) and scan the QR code with the phone's camera.

- The computer stays connected to the camera (Wi-Fi or USB); the phone stays in the home Wi-Fi.
- The phone gets a key that is new at every start and lasts 12 hours; other devices only see a note to scan the code.
  Without `--lan` the app answers only on the computer.
- In Playback: pinch zooms a picture (double tap: 1× / 2.5×), a sideways swipe shows the next or previous picture,
  pinch changes the Index display size. Turning the phone switches between portrait and landscape layout.

## Use as webcam (OBS)

Works over Wi-Fi and USB. Start the app, connect and press **Start live view** (the live view must keep running). Then:

1. Press **Webcam (OBS)** next to **Second monitor**. It opens the webcam view and copies its link. In OBS add a
   **Browser Source** with `http://127.0.0.1:8765/?view=webcam` (optional letterbox size:
   `?view=webcam&w=1280&h=720`, with the same width and height in the source).
2. In OBS press **Start Virtual Camera**; Zoom, Teams and browsers then list "OBS Virtual Camera".
3. Sound is not part of the camera picture: add a microphone as an audio source in OBS.

Over USB at 1024×768 the webcam gets the full 30 fps.

## HSL color profiles

Modelled on the PEN-F front-dial COLOR mode (12 sectors, hue/saturation/lightness −7…+7, three profile slots),
applied on the computer to ORF or JPG files. In the app: **HSL** button in the single-frame view of Playback. On the command line
(needs `pip install ".[film]"`):

```sh
python -m omcap.hsl IMG.ORF --profile "Teal & orange" --out out/hsl --sheet
python -m omcap.hsl IMG.JPG --profile my_profile.json
```

ORF gives a 16-bit TIFF, JPG a JPEG, always in `--out` (default `out/hsl/`). `--sheet` adds a before/after sheet and
a colour wheel chart. Presets: `omcap/data/hsl_presets.json`. Sector angles and gains are approximations, not the
camera's values.

## Tests

```sh
.venv/bin/python -B -m unittest discover -s tests
```

The tests use simulated camera answers and need no camera.

## Contributing

Camera test reports, bug reports, ideas, translations and code are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md); questions go to [Discussions](https://github.com/HolmHaensel/omcap/discussions).

## License

GPL-3.0-or-later, see [LICENSE](LICENSE).
