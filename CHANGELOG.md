# Changelog

## Unreleased

- Docs: README notes that USB works on Linux over libgphoto2 (not tested yet: camera mounting by the desktop, udev access); libgphoto2 stays the USB backend there.
- USB: shutter speeds that libgphoto2 lists as fractions (3.2 s = 32/10, 1/1.3 s = 10/13 …) are offered and named like on the camera; ISO AUTO/LOW are named by value, not by position; the read-only flag of each setting comes from the camera; the aperture list is limited by the lens limits the camera reports (d07f/d080) (REQ-F10, from the maintainer's gphoto2 dump).

### Shooting and focus
- M mode quick select: BULB, LIVE TIME, LIVECOMP and Off (back to the last shutter speed) in the shooting options, for Wi-Fi and USB; tested on both 2026-11-13. USB: LIVE TIME is recognised when libgphoto2 reports it as a raw fraction (65535/65533); Off falls back to 1/60 s when no earlier speed is known (REQ-F31).
- Wi-Fi Take picture uses `exec_takemotion com=starttake` with the tapped AF point in shooting mode instead of switching to shutter mode. It focuses on the tapped point, live view keeps running, and the shot takes 1.2–1.5 s instead of about 7 s (camera-tested). Long exposures (slower than 1/4 s), BULB, LIVE TIME, LIVECOMP, self-timer and Movie keep the shutter-button route; no second shot after a timeout (REQ-F34).
- USB Take picture focuses on the tapped AF field (camera-tested at 140 mm, REQ-F34).
- USB: the idle event wait after releasing the focus tap is removed (about 0.3 s per tap; not measured).
- USB: the mode dial is followed in live view. Turning it is detected (event 0xC003, param 3) and the session rebuilds by itself; P, A, S, M and Movie are shown; iAUTO, ART, SCN and PHOTO STORY read as P, and iAUTO comes from the EXIF of the newest shot (REQ-F30, tested with all nine dial positions).
- Controls appear only in the shooting modes where the camera lets you select them (design principle 7, E-M1 manual): movie section only in Movie mode (p.71); self-timer and drive not in Movie mode; exposure controls in Movie mode follow the movie mode P/A/S/M.
- USB LV super control panel: AF mode, Metering mode, Flash mode, Record mode, Aspect ratio, Image stabilizer and Face priority, with values mapped on the camera (`out/research/usb_value_mapping.md`). Only in P/A/S/M as on the camera (manual p.24). Reading tested; setting not tested. Not over Wi-Fi: no command (REQ-F10, branch `usb-foundation`).

### Live view and USB
- USB live view size can be chosen (up to 1280×960) when libgphoto2 keeps the size, i.e. development version 2.5.34.1 or later. With 2.5.34 the size stays 1024×768 and the choice is hidden. Tested 1280×960 at 13.8 fps (REQ-F36).
- USB live view stall after connecting fixed: the pause counter is thread-safe. The mode dial check runs every 3 s and ignores the event the camera sends when live view starts. Measured 14.3 fps and 17.8 fps at 1024×768, Take picture 4.7–5.3 s, picture shown 0.35 s later.
- Research endpoint `/api/usbprops` reads single USB properties and their choices (for the value mapping, REQ-F10).
- Own PTP layer `omcap/ptp.py` (ctypes/libusb), not used by the app yet. Read-only camera test passed 2026-11-13: open 0.31 s, 2936 handles 0.013 s, object info ~10 ms, thumbnail 12 ms, 64 KB partial read 8 ms (REQ-F28).

### Playback and files
- Open in OM Workspace in the single-frame view (macOS, only when OM Workspace is installed): saves the missing files of the shot to the computer first (ORF when only the JPG was saved), then opens it. USB tested 2026-11-13; Wi-Fi untested (REQ-F17).
- Playback: the thumbnails in the Playback section open the single-frame view (click or Enter), like the tiles in Index display. Playback and the single-frame view lie above the shutter bar in narrow windows (REQ-F27).

### App start and quit
- "Quit E-M1 Capture" button in the header and on the start screen; a second click confirms. Closes the camera connection, stops the app and shows a notice (REQ-Q10). Tested while connected over Wi-Fi (2026-11-13).
- Second start while the app is already running: the message says the window can be closed and how to stop the running app (Ctrl+C in its window, or `pkill -f 'omcap\.server|bin/em1-capture'`).
- Clearer error messages: USB connect failure says what to check (Photos, USB menu, restart after re-plugging); missing gphoto2 says how to install it; the level gauge message no longer claims USB support; the "not running" hint names a command that works in every installation, and the Windows launcher.

### Quality and docs
- CI on GitHub: offline tests on every push to `main` and `release-*` and on pull requests (Ubuntu with Python 3.9 and 3.12, macOS with 3.12) (REQ-Q08).
- 141 offline tests pass on `usb-ptp` (2026-11-13).
- README: "Stop" section, feature table and parity rows.

### Known issues
- Wi-Fi drops out on the Mac (it leaves the camera network). Once, an app started from the launcher got "No route to host" while the shell reached the camera (macOS Local Network permission suspected).
- USB: live view pauses up to ~70 s after connecting while the card list is read. The PTP card index should fix this.
- USB, All Targets + Halfway: the green AF field may not match where the camera focused.
- A lens change is only noticed with the next photo (USB and Wi-Fi).

## 0.5.0 – 2026-11-12

- Wi-Fi live view: the RTP extension data (OPC protocol) is read instead of skipped; `GET /api/lvext` shows what the camera sends. The E-M1 Mark I sends free shots, AF result, shutter speed, aperture, exposure compensation, ISO (also with ISO Auto) and focal length; no level gauge or face frames (REQ-F29).
- Faster start (REQ-F27): the card list is saved on the computer (`out/cache/cardlist_wifi.json`, `_usb.json`) and shown at once; the camera's list follows in the background after the live view has started. Wi-Fi measured: header after 1 s, live view after 1.7 s (before: card space after 7 s, live view after 10 s, card list 17 s).
- Turn off camera and Reset Share Order ask for a second click on the page instead of a browser dialog, which embedded browsers (e.g. the Claude app's browser) suppress; before, the button did nothing there.
- Wi-Fi after Take picture: only the newest card folder is read and merged into the saved list, once for the gallery and the last shot together (before: whole card plus newest folder, up to three times). Measured: picture in the index and last-shot corner 15 s after the click instead of 24 s; a second shot no longer waits up to 23 s (REQ-F16, REQ-F27).
- Wi-Fi after Take picture: the next picture is asked directly by its DCF name (`GET /api/newshot`, PB122211 → PB122212; other color space prefix and today's date as fallback) and shown in the last-shot corner and the index at once; the folder is read afterwards to complete the list. Measured: 8.4 s from the click (7.2 s of it the camera's shot) instead of 15 s (REQ-F16).
- USB: the saved card list shows at once while the camera reads its card index (~1 min), and the camera list loads by itself when the index is ready (before: "Press Reload to read"); the model name is kept, so reloading the page no longer waits for the index (REQ-F27).
- `--timing` prints every request with its duration (performance checks).
- Wi-Fi: live view start retries when the camera answers 520 right after switching to shooting mode.
- Wi-Fi: during live view the header shows the battery level (ID 7, same value as USB), free shots and the current focal length, and the value strip shows the ISO in use with ISO Auto and the shutter speed and aperture the camera uses in auto modes (REQ-F29).

## 0.4.0 – 2026-11-11

- New design (REQ-D01, REQ-D03): dark theme with tokens from `design/tokens.css`, header chips, live view with value strip, focus status chip and histogram, toolbar with toggle chips under the image, LV super control panel with mode control and value tiles, shutter block with self-timer control; functions a connection cannot do are hidden; disabled with a reason only in read-only mode (REQ-G02); phone layouts and 44 px touch targets.
- Playback (REQ-F27): Index display grouped by day (S/M/L, multi-select to save), Calendar display, optional shooting data line on thumbnails.
- Picture information (REQ-F26): single-frame view with the INFO cycle (Image only / Simplified display / Overall display with histogram and shooting data, Fit / 100 %); new `GET /api/exif` (codes, translated in the page); over USB each JPG is read from the card only once and the info starts on Image only.
- Back to the start screen when the session is gone (409).
- USB: `/store_…/DCIM` path check on file access (REQ-F26).
- iAUTO detected from EXIF program 5; no "0.0 MB" size shown.
- Live view and Take picture are always visible together (REQ-D02).
- USB: shooting data on thumbnails and in Index display, read from the first bytes of each JPG (REQ-F26).

## 0.3.0 – 2026-11-11

- Webcam (OBS) button next to Second monitor: opens the webcam view and copies its link to the clipboard (REQ-D05).
- Save to: choose the folder on the computer and the file naming (original / date_time_original / prefix + original); stored in `omcap-settings.json` in the data folder; never overwrites (REQ-F17).
- HSL in the web app (USB and Wi-Fi): HSL button per computer file and in the single-frame view, preset dialog with before/after slider, results in `out/hsl/`, optional auto-apply when saving to the computer (REQ-I01, REQ-I04).
- Wi-Fi: the last shot appears reliably; the app waits up to a minute for the camera's card list (REQ-F16).
- Tested with the camera over Wi-Fi (webcam link, save folder and naming, HSL).

## 0.2.1 – 2026-11-10

- Easy start: double-click `E-M1 Capture.command` (macOS) or `E-M1 Capture.bat` (Windows, Wi-Fi only, untested); the browser opens by itself (`--no-browser` to skip).
- Starting a second time no longer fails with "Address already in use": it opens the browser and says the app is already running; another program on the port gets a hint to use `--port`.
- Clear message with the start command instead of "Failed to fetch" when the app is not running, also under the USB/Wi-Fi choice when `index.html` was opened as a file.
- The tapped AF field is marked at once while the camera focuses (Wi-Fi and USB).
- README: everyday start and stop, offline use.

## 0.2.0 – 2026-11-09

- Header shows free card space (Wi-Fi and USB) and battery level (USB); read-only camera settings Anti-Shock, Silent, Noise Reduct., BULB/TIME Timer and Digital Tele-converter under the LV super control panel (Wi-Fi).
- Playback over Wi-Fi: Share Order filter with count, Save all to computer and Reset Share Order; movie length in the single-frame view.
- Wi-Fi: Turn off camera button in the header (`exec_pwoff`, with confirmation); returns to the start screen.
- Live view aids computed in the browser: Histogram (luma, optional RGB), Highlight&Shadow warning and Peaking with color choice.
- Software HSL colour profiles modelled on the PEN-F COLOR dial (`omcap.hsl`: 12 sectors, H/S/L −7…+7, 3 slots, CLI for ORF/JPG).
- Self-timer (Off / 2 s / 12 s) next to Take picture with a countdown over the live view; click again to cancel.
- Last shot thumbnail in the live view corner after Take picture (click opens the single-frame view; Wi-Fi and USB).
- Webcam view `/?view=webcam` (live image only, black background, optional `&w=&h=`) for an OBS Browser Source; README section "Use as webcam (OBS)".

- USB: card index read after connecting (first picture fast), AF grid and focus position in the right grid, lens name, picture list loads automatically, "P Program / iAUTO" (the camera reports both as P), live view no longer drops during AF.
- Code comments in English for contributors; read-only USB property listener `tools/usb_props.py`.

### Known issues
- USB, All Targets + Press halfway: the green AF field may not match where the camera focused.

## 0.1.0 – first release

First public version of E-M1 Capture for the Olympus OM-D E-M1 Mark I (firmware 4.6).

- Wi-Fi (OI.Share protocol 2.60) and USB (libgphoto2) from one start screen; shows the detected camera.
- Live view with size choice (Wi-Fi), zoom, Displayed Grid, overlay and a second monitor window.
- 9×9 AF grid: click to focus; Wi-Fi reports the AF target from `assignafframe`.
- Shutter button: Take picture and Press halfway (take a picture with the held focus).
- LV super control panel from the camera's settings list; aperture limited to the attached lens (EXIF).
- Movie over Wi-Fi: Start/Stop recording, Recording time, movie shooting mode P/A/S/M, Record mode shown.
- Playback with Index display, Calendar display and single-frame view; previews load in two stages
  (thumbnail, then medium size in playback mode), with disk and browser cache.
- Save to card only or card and computer; previews use the JPG of a shot when there is one.
- English interface with a translation table for further languages.
