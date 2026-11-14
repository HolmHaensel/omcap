# Changelog

## Unreleased (0.7.1)

- Calendar display: the day of the month and the number of shots looked alike; the day is now large and bold, the number a yellow badge "12 shots".
- HSL colour profile window: it grows with the before/after picture (it was fixed at 420 px, so the two pictures did not line up), and the comparison is a line with a handle in the picture (drag, click or arrow keys) instead of a slider below it. Camera-tested 2026-11-14.
- Live view and the HSL comparison no longer drag a ghost copy of the picture; dragging pans the zoomed live view or moves the before/after line.
- The live view overlay is switched off for now (buttons hidden): a plain guide picture was mistaken for a multiple exposure. It comes back as a real multiple exposure that combines the frames (REQ-F43).

## 0.7.0 – 2026-11-14

Faster USB, closer to Wi-Fi: the app's own PTP layer, USB settings, focus ring, movie and Focus Stacking over USB, and a round of live view and focus fixes found at the camera.

### USB backend and performance
- New USB backend on the app's own PTP layer (`omcap/ptp.py`, ctypes/libusb) with a gphoto2-compatible shim (`omcap/ptp_gphoto.py`), so the USB session logic is unchanged. Option `--usb-backend auto|ptp|gphoto2`: `auto` (default on macOS) uses the PTP layer and falls back to libgphoto2 when it cannot connect; elsewhere the default stays libgphoto2 (Linux). `/api/status` reports `usb_backend` (REQ-F28, camera-tested on macOS 2026-11-13).
- Card index by file handle with a disk cache (`out/cache/ptp_index.json`), read at connect before PC control (10–12 ms per file instead of ~26 ms); a spot check of name, size and date of four files detects another card. Measured with about 2950 files: first connect without cache 44.8 s, later connects 6.9–9.2 s, also right after a shot (libgphoto2: about 9 s plus 51–72 s index in the background). Card list 0.1 s.
- Fix: USB live view with the PTP backend stayed black after the camera was switched off and on ("live view failed 10x"). The live view size d06d is also the camera's live view switch; at 0 the camera answers every frame request with 0 bytes. Like libgphoto2, the PTP layer now sets 1024×768 once per session when d06d is 0; a size chosen in the app stays. "USB session reopened (live view failed 10x: …)" now names the camera's last answer. Camera-tested 2026-11-13 (REQ-F28).
- Fix: USB live view went black for a few seconds now and then: the camera also sends the mode-dial event 0xC003/3 a little after a shot or a written setting (seen 3.1 s after a shot), so the app rebuilt the session. The event now only counts 6 s after a shutter command, written setting or live view start (a real dial turn in that time needs a second turn); the rebuild message names the time since the last command (REQ-F30). Camera-tested 2026-11-13.
- Fix: USB focus reported "In focus" although the camera had not focused, so Take picture then did not release (S-AF releases only in focus). Any event 0xC003 counted as confirmation; mapped on the camera 2026-11-13: Param1 1 = in focus with the position in Param2 (x << 16 | y, 1280×960) and the frame size in Param3, Param1 2 = no focus; 0xC003/3 follows settings and shots. The app now takes the result and the green field from this event (no lag as with d05d/d05e), answers "no focus" at once, and Take picture without focus in S-AF answers after about 1 s instead of 20 s (C-AF releases anyway by default, so it keeps waiting) (REQ-F34).
- Main live view without MJPEG: the page fetches one frame per request (`/live.jpg`), decodes it off screen and shows only frames that decode; a browser could stop showing the MJPEG stream after a hiccup and stay black until it reconnected (seen 2026-11-13 although every frame decoded). Replaces the reconnect logic and the watchdog of the previous fix; the `?view=` windows (webcam, OBS) keep MJPEG. Camera-tested 2026-11-13.
- Live view with the PTP backend: 1024×768 at 19.5–26.4 fps (libgphoto2 14–20.6 fps), 1280×960 at 15.0 fps. 1280×960 no longer needs the self-built libgphoto2 (REQ-F36).
- Focus by tap: 0.4–0.6 s (libgphoto2 1.3–1.5 s). Take picture: 4.5–4.8 s in total, JPG and ORF in the card list at once.
- Idle event check costs 10 ms instead of about 0.3 s: on macOS synchronous interrupt reads shorter than ~150 ms never deliver an event, so the PTP layer keeps one asynchronous read submitted.
- Camera-tested with the PTP backend: BULB, LIVE TIME and LIVECOMP (REQ-F31) and the mode dial (REQ-F30). During a long exposure and its noise reduction the session is never rebuilt (the camera ends the noise reduction with the same event as the mode dial); file events lost in a rebuilt session are taken from the card index.
- Also camera-tested with the PTP backend: interval shooting (3 frames, 5 s), AE bracketing (3 frames, −0.3/0/+0.3 EV per EXIF, compensation restored), partial reads (picture info from the first 128 KB in 0.02 s; a whole 3.8 MB JPG in 0.22 s) and a full session in the browser (tap focus, Take picture, Index display, single-frame view). Not tested: Linux.

### Shooting and settings
- The last-shot picture fades out 6 s after a shot (the card strip keeps it). A red "No focus" chip shows for 4 s when AF fails after a tap, Halfway or Take picture, like "In focus" (REQ-F34). Over Wi-Fi the chip shows after a tap only.
- Shutter blackout: Take picture shows a short black frame (~0.18 s) over the live view, like the viewfinder of an older camera; USB and Wi-Fi. It shows on the click, also when the camera then does not release (REQ-F39).
- Fix: clicking the last-shot picture opened no single-frame view but answered "Outside the AF Area" (the live image captured the pointer for AF and panning); camera-tested 2026-11-13.
- USB Focus Stacking (FW 4.x; this camera runs a modified firmware with Focus Stacking enabled): On/Off in the LV super control panel, P/A/S/M only (manual p.82, 174). It sets Bracketing to Focus BKT (d020 = 3) and Focus Stacking (d0cb = 1; libgphoto2's d065 does not change on the E-M1) and keeps the earlier bracketing kind; the camera switches by itself to Silent Sequential H, electronic shutter and flash off. Take picture waits for the merged picture. Camera-tested 2026-11-13: 16 frames (JPG+ORF) plus the merged JPG, 17.7 s; switching takes about 10 s (session rebuilt). Focus BKT without stacking not built (number of shots not mapped). Not over Wi-Fi: no command (REQ-F38). Follow-up: with Focus Stacking on, the app hides Drive, Flash mode, AE bracketing and long exposures (fixed by the camera, p.174); Focus Stacking cannot be switched on at BULB / LIVE TIME / LIVECOMP; a body or firmware without d0cb hides the setting instead of failing the whole panel; Off restores the bracketing kind only if it is still Focus BKT; live view pauses while switching.
- USB movie recording: Start/Stop recording presses the camera's REC button (movie button, PTP 0x948C), so it records in every shooting mode (E-M1 manual, p.26), not only in Movie mode; hidden during BULB / LIVE TIME / LIVECOMP and with sequential shooting (p.27). PHOTO STORY and some SCN modes read as P over USB: there the camera does not record although the button is shown. Live view keeps running while recording, the MOV file goes to the card list, a recording is ended when the app disconnects or quits. Camera-tested 2026-11-13 in S and in Movie mode. Movie settings (frame rate, quality, audio) not over USB yet (REQ-F37).
- USB Focus ring (MF): Near 3/2/1 and Far 1/2/3 in the AF section move the focus like the focus ring (PTP 0x9487, step sizes as libgphoto2). Shown only with AF mode MF or S-AF+MF and write enabled; the camera ignores it in S-AF. Camera-tested 2026-11-13: about 0.1 s per step, three clearly different step sizes. Not over Wi-Fi: no command (REQ-F28, basis for the Star AF aid REQ-F24).
- USB LV super control panel: AF mode, Metering mode, Flash mode, Record mode, Aspect ratio, Image stabilizer and Face priority, with values mapped on the camera (`out/research/usb_value_mapping.md`). Only in P/A/S/M as on the camera (manual p.24). Read and write tested 2026-11-13. Not over Wi-Fi: no command (REQ-F10).
- USB: shutter speeds that libgphoto2 lists as fractions (3.2 s = 32/10, 1/1.3 s = 10/13 …) are offered and named like on the camera; ISO AUTO/LOW are named by value, not by position; the read-only flag of each setting comes from the camera; the aperture list is limited by the lens limits the camera reports (d07f/d080) (REQ-F10).
- USB Take picture focuses on the tapped AF field (camera-tested at 140 mm, REQ-F34).
- USB: the idle event wait after releasing the focus tap is removed (about 0.3 s per tap).
- Research endpoint `/api/usbprops` reads single USB properties and their choices (for the value mapping, REQ-F10).

### App and docs
- CI: the Python 3.9 job runs on `ubuntu-24.04`; GitHub's `ubuntu-latest` moved to 26.04, which has no Python 3.9 for setup-python, so CI on `main` was red since 0.6.0 (REQ-Q08).
- The app releases the camera when it is stopped with Ctrl+C or `kill` (leaves PC control and closes the session); before, the camera could stop answering until it was switched off.
- README: USB on Linux works over libgphoto2 (not tested yet: camera mounting by the desktop, udev access); libgphoto2 stays the USB backend there.
- 182 offline tests pass (2026-11-14); CI green on Ubuntu 24.04 (Python 3.9, 3.12) and macOS (3.12).
- README: other cameras – a user runs E-M1 Capture with a PEN-F and with a PEN-F colour emulation (user-tested); the camera report template asks for the Wi-Fi settings list (REQ-G08).

### Not in 0.7 (moved to 0.7.x / 0.8)
- Camera changes without rebuilding the USB session, `getrecview` over Wi-Fi, capture target (card / computer) over USB, flash compensation, movie settings over USB, Focus BKT without stacking.

### Known issues
- Wi-Fi: the main live view now loads single frames (`/live.jpg`) on both connections; tested over USB, **not yet over Wi-Fi**.
- Focus Stacking: hiding Drive, Flash and AE BKT while it is on, and refusing it at BULB / LIVE TIME / LIVECOMP, are not camera-tested yet.
- A touch AF target set on the camera monitor overrides the AF field chosen in the app (remove it on the camera).
- USB movie: the app does not check that the camera really started recording (PHOTO STORY, some SCN modes, a full card); then it shows a recording that does not run until Stop recording is clicked.
- LIVECOMP: a stop press shortly after the start (4–8 s) is ignored by the camera and the exposure keeps running; a later press ends it (probably after the first composite frame, Composite Settings). The app does not show that the exposure still runs.
- Mode dial over USB: the new mode arrives only when PC control is switched on again, so each turn rebuilds the session (8–10 s); quick turns in a row show only the last position.
- Wi-Fi drops out on the Mac (it leaves the camera network). Once, an app started from the launcher got "No route to host" while the shell reached the camera (macOS Local Network permission suspected).
- USB with the libgphoto2 backend (fallback, Linux): live view pauses up to ~70 s after connecting while the card list is read (not with the PTP backend on macOS).
- USB, All Targets + Halfway: the green AF field may not match where the camera focused.
- A lens change is only noticed with the next photo (USB and Wi-Fi).

## 0.6.0 – 2026-11-13

- Wi-Fi Take picture uses `exec_takemotion com=starttake` with the tapped AF point in shooting mode instead of switching to the shutter mode: focuses on the tapped point, the live view keeps running, and the shot takes 1.2–1.5 s instead of about 7 s (camera-tested). Only for normal shots: long exposures (slower than 1/4 s, BULB / LIVE TIME / LIVECOMP), the self-timer and Movie mode keep the shutter-button route, which is also the fallback when the camera refuses (REQ-F34).
- USB: LIVE TIME is recognised when libgphoto2 reports it as a raw fraction (65535/65533); "Off" in the M-mode quick select falls back to 1/60 s when no earlier speed is known (REQ-F31, camera-tested over USB).
- Single-frame view: "Open in OM Workspace" (only when OM Workspace is installed); saves the shot to the computer first if needed and opens the ORF, otherwise the JPG (REQ-F17).
- Playback: the thumbnails in the Playback section open the single-frame view (click or Enter), like the tiles in Index display; Playback and the single-frame view now lie above the shutter bar in narrow windows (REQ-F27).
- USB live view size can be chosen like over Wi-Fi (up to 1280×960) when libgphoto2 keeps the size (development version 2.5.34.1 or later; with 2.5.34 it stays 1024×768 and the choice is hidden). Measured 1280×960 at 13.8 fps (REQ-F36).
- CI on GitHub: offline tests on every push to `main`/`release-*` and on pull requests (Ubuntu with Python 3.9 and 3.12, macOS with 3.12) (REQ-Q08).
- "Quit E-M1 Capture" button (header and start screen, second click confirms): closes the camera connection, stops the app and shows a notice (REQ-Q10).
- Second start while the app is already running: the message now says the window can be closed and how to stop the running app (Ctrl+C in its own window or `pkill -f 'omcap\.server|bin/em1-capture'`); error messages: USB connect failure says what to check (Photos, USB menu, restart after re-plugging), missing gphoto2 says how to install it, the level gauge message no longer claims USB support; README has a "Stop" section and current parity rows (lens aperture over USB, webcam view over USB (button untested), time lapse/AE BKT untested, what the E-M1 cannot do).
- USB live view: fixed a stall after connecting (the pause counter is now thread-safe); the mode dial check runs every 3 s and ignores the event the camera sends when live view starts. Measured: 14.3 fps, Take picture 4.7–5.3 s, picture shown 0.35 s later.
- Controls appear only in the shooting modes where the camera lets you select them (manual logic, design principle 7): movie section only in Movie mode, self-timer and drive not in Movie mode, in Movie mode aperture / shutter speed / exposure compensation / ISO / WB follow the movie exposure mode P/A/S/M (E-M1 manual, p.71).
- USB: turning the mode dial is detected (event 0xC003, param 3); the app rebuilds the USB session by itself and reloads the values, no "reload" needed (during live view). P, A, S, M and Movie are shown; iAUTO, ART, SCN and PHOTO STORY read as P over USB and are shown as P; after a shot iAUTO is shown from the picture's EXIF (REQ-F30).
- M mode: quick select BULB / LIVE TIME / LIVECOMP and Off (back to the last shutter speed) in the shooting options. Built for Wi-Fi and USB, camera-tested on both (REQ-F31).
- The "not running" hint names the command that works in every installation (`.venv/bin/python -m omcap.server --allow-write`) and the Windows launcher.

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
