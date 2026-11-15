# Changelog

## Unreleased

- Wi-Fi dropped and back: the camera answered again but had ended the live view, and the app waited forever. Now the app notices the stalled live view, shows *Camera not found. Is the computer in the camera's Wi-Fi?* while the camera does not answer, and restarts the live view by itself once it does (next try after 5, 10 … 60 s, reset only by real new frames); not during a shot, movie, job, half press or Playback. Camera-tested: the message during a 10 s drop; the restart itself not yet seen on the camera (REQ-Q14).
- Live view status line: next to the size it shows how many frames per second the browser really displays (last 3 s), and "libgphoto2" when USB fell back to the slower libgphoto2 layer; seen over Wi-Fi, USB not yet looked at (REQ-F51).
- Playback, Index display, Select: new Erase button deletes the selected pictures from the card over USB (PTP DeleteObject; JPG and ORF together, confirm first, needs `--allow-write`, protected pictures are reported); not available over Wi-Fi (no command). Camera-tested 2026-11-15 with the own USB layer (libgphoto2 not tested): JPG and JPG+ORF erased, a protected picture refused by the camera and kept. Before each delete the app checks on the camera that the file is still the one in the list and never a folder (REQ-F50).
- README rewritten for easier reading: highlights, quick start, features grouped by topic with ✅ / 🟡 / – for Wi-Fi and USB, one speed table, an options table.
- Main live view: the next frame is requested while the current one decodes, so the view keeps up with the camera – USB 1024×768 now 29.9 fps instead of 26.5 fps in the browser, Wi-Fi 640×480 29.8 instead of 28.8 fps (measured 2026-11-15, REQ-Q13).
- Webcam (OBS) and second-monitor windows: same frame-by-frame live view as the main window instead of MJPEG. With MJPEG the picture went black for good after one bad frame (seen over Wi-Fi at 1280×960 and after a size change); now a bad frame is skipped, and the window picks the live view up again by itself after a reconnect (REQ-Q13).
- Server log: a page that went away (reload, closed window, cancelled live frame request) no longer prints a Broken pipe traceback (REQ-Q13).
- README Wi-Fi table re-measured 2026-11-15 with single-frame live view: 640×480 30 fps, 800×600 about 21 fps, 1024×768 about 12 fps, 1280×960 about 8 fps, no frames lost.
- README: speed tables brought up to the latest measurements (Wi-Fi 640×480 27–30 fps and 800×600 about 20 fps since single-frame live view; USB connect 5–9 s, 5.2 s with 0.7.7); values not re-measured are marked.
- USB live view measured 2026-11-15 with the own PTP layer: 30 fps at 640×480, 800×600 and 1024×768 (the camera's own rate, so the webcam view gets 30 fps), 15 fps at 1280×960.

## 0.7.7 – 2026-11-15

A steadier USB connection and a cleaner phone view.

- USB (own PTP layer): connecting writes one log line with the time of each step. Measured 2026-11-15: USB open 0.0 s, session 0.3–0.7 s, card index 0.1 s, PC control about 5 s – the camera itself takes that long to confirm computer control (REQ-Q12).
- Two connect requests at once (start screen auto-connect and a click, or two tabs) make one connection; before, the second disconnected the first and one of them failed. A Disconnect during a slow connect waits for it (REQ-Q12). Camera-tested over USB 2026-11-15; Wi-Fi uses the same server code, not tried.
- Level gauge right after connecting: no failed request and no false "Level ✓" before the first reading (REQ-F23). Tried on the camera 2026-11-15.
- USB: when the camera disappears (cable pulled, camera switched off) the app no longer rebuilds the session in a loop – that stopped the macOS camera service each time and blocked other apps. It waits quietly, shows "Camera not found. Is the cable plugged in?" and reconnects by itself once the camera is back; a failed rebuild waits 5, 10 … 60 s. The dead session is released at once – a handle left on the vanished device made libusb crash (segmentation fault) when the camera came back – and a returning camera must stay 3 s, because it appears and vanishes while its USB menu is open (REQ-Q11). Camera-tested 2026-11-15: no rebuild while the cable was out, one rebuild and live view back about 9 s after plugging in.
- Phone view, upright or turned (REQ-F49): no live view size choice – the app picks the size itself (Wi-Fi: adaptive, now also with the phone turned; USB: always 1024×768) – and no second-monitor or webcam (OBS) windows, which make no sense on a phone. Tried on an iPhone 2026-11-15.

## 0.7.6 – 2026-11-14

Playback on a phone: pinch to zoom, swipe between pictures, pinch for the Index display size.

- Single-frame view on a phone (in the fitted view; "Fit" 1:1 keeps scrolling): pinch with two fingers zooms the picture (up to 6×), one finger moves the zoomed picture, a double tap switches between 1× and 2.5×; the mouse wheel zooms on the computer. Before, a pinch zoomed the whole page. At 1× a sideways swipe shows the next or previous picture: one finger or a mouse drag (past 60 px), or a sideways wheel – Magic Mouse, trackpad, Shift + wheel (past 80 px, one picture per gesture; a new swipe during the momentum of the last one counts, no click needed); the picture follows and slides out, and gives only a little at the first and last picture. The ‹ › buttons stay in the bar. Swipe tried 2026-11-14. (REQ-F48)
- Index display on a phone (touch only): pinch changes the grid like a photo library – the grid scales smoothly with the fingers and settles on the nearest size (S 5×5, M 3×3, L 2×2) when they lift; one finger still scrolls. Tried on an iPhone 2026-11-14. (REQ-F48)
- Calendar display on a phone (width up to 700 px, redrawn when the phone turns): the badge shows only the number of shots ("12"; the full "12 shots" stays as a tooltip and is read by screen readers) and the day and badge are smaller, so the day stays visible. (REQ-F48)
- The **Phone** button (with `--lan`) is also on the start screen, so the QR code can be shown before a camera is connected (REQ-F47).
- Turning the phone: a page zoom left from before is reset, the font is no longer enlarged by the phone, and the level gauge is redrawn; the layout switches between portrait and landscape as before. Phone gestures tried on a phone 2026-11-14; the rotation fix is not confirmed yet (REQ-F48).

## 0.7.5 – 2026-11-14

The app on a phone, a start screen that connects by itself, and a live view size that follows the phone.

- Wi-Fi on phone width: the live view size follows the screen and the signal. It starts with the size that fits the screen and steps down one size when frames come too slowly (under 12 fps or more than 18 % lost over 4 s) or stall for more than 1.5 s – and only when that lasts 4 s, so a short dip right after connecting does not count – at most every 8 s and never during a shot, job, movie or card read; a chip "Auto · 800×600" shows the size. `/api/state` reports the live view rate and lost frames (`lvperf`). Desktop and USB keep the manual size. Built in the redesign, moved to `main` (REQ-F45). Camera-tested over Wi-Fi at phone width 2026-11-14 (800×600 → 640×480, then 27–30 fps; that test stepped down on a short dip after connecting, which the 4 s wait now ignores – the 4 s wait itself is not camera-tested yet). USB and read-only keep the manual size at every width. With the app also open on a phone (--lan), the phone's automatic step changes the live view for the computer too.
- Start screen connects by itself: when the connection used last time (USB or Wi-Fi) finds the camera again, the app connects after a 2 s countdown ("Connecting to Olympus E-M1 over Wi-Fi in 2 s …") that "Stay here" stops. Not again right after "Disconnect" in the same window, and only once per page load. The Mac itself still has to be in the camera's Wi-Fi. Camera-tested over Wi-Fi 2026-11-14 (connected 2.3 s after loading); USB reconnect not tested yet (REQ-F46).
- Open the app on a phone (start with `--lan`): the computer shows a QR code behind the new **Phone** button; the phone scans it and gets a key that is new at every start (kept as a cookie for 12 hours). Other devices without the key see only a note; the QR link is only shown on the computer. The QR code is made by the app itself (no extra package). A phone with the key can do everything the computer can (also Quit, Open in OM Workspace on the computer); the key stays in the phone's browser history. Without a home network address `--lan` stays on the computer. Tried with a phone 2026-11-14 while the computer was connected over Wi-Fi (REQ-F47).

## 0.7.4 – 2026-11-14

Level gauge feedback and a held angle (USB).

- Level gauge feedback and a held angle (USB): within 0.3° of level the line and dot turn green and thicker and a chip says "Level ✓"; an optional short sound (switch "Sound", off by default) plays when the camera gets there. "Hold angle" keeps the current horizon and tilt as the target, shown as a dashed line and a mark; the gauge then shows the deviation ("Δ Horizon … · Δ Tilt … to the held angle") and "Angle matched ✓" – for repeat shots and product series from the same angle. The target is remembered until "Clear angle". Tried by the user 2026-11-14 (REQ-F44).

## 0.7.3 – 2026-11-14

The level gauge over USB.

- USB level gauge: the live view shows the camera's tilt (horizon line, tilt dot, values next to the switch), read live with GetDevicePropValue (d053/d055) under PC control; the descriptor the app read before stays at the session-start value. Polled every 0.15 s while it is shown (about 35–70 ms per read, live view unchanged at 30 fps); in between the line and the dot glide to the newest value, so the gauge moves smoothly. Own PTP layer only (macOS default); hidden with libgphoto2 and over Wi-Fi (no tilt in the Wi-Fi data). The values read "Horizon" and "Tilt" as in the manual (p.37). The gauge stands still during a shot, a movie recording or a card read. Switched on and off with "Level gauge" in the live view tools: off by default, the choice is remembered like the other live view aids; while it is off the camera is not asked. Camera-tested 2026-11-14 (REQ-F23).

## 0.7.2 – 2026-11-14

Small additions found while using 0.7.1.

- AF frame on tap without the grid: with "Show AF targets" off, a tap still shows the chosen AF frame for about 4 s – white while focusing, green in focus, red without focus (REQ-F41). Camera-tested over Wi-Fi 2026-11-14; over USB tried by the user in the redesign build (same code) on 2026-11-14.
- Wi-Fi smoke test of the 0.7 page 2026-11-14: live view from single frames at 19 fps without gaps, tap focus with In focus / No focus, shutter blackout and Take picture with the last-shot picture.
- ISO AUTO over Wi-Fi: the ISO the camera picks right now shows small and grey under AUTO in the ISO tile ("now 800") and next to ISO AUTO in the value strip (not in Movie mode); from the live view data (REQ-F29). Not over USB (no live value). Camera-tested over Wi-Fi 2026-11-14.

## 0.7.1 – 2026-11-14

Fixes in the browser page found while using 0.7.0.

- Calendar display: the day of the month and the number of shots looked alike; the day is now large and bold, the number a yellow badge "12 shots".
- HSL colour profile window: it grows with the before/after picture (it was fixed at 420 px, so the two pictures did not line up), and the comparison is a line with a handle in the picture (drag, click or arrow keys) instead of a slider below it. Camera-tested 2026-11-14.
- Live view and the HSL comparison no longer drag a ghost copy of the picture; dragging pans the zoomed live view or moves the before/after line.
- Single-frame view: the INFO button shows the details (Overall display) on the first click, then Simplified display, then Image only; the button is highlighted only while the details are open.
- Live view off: the picture area turns dark instead of keeping the last frame (single-frame live view keeps the last picture).
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
