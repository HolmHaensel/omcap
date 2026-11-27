# Changelog

## Unreleased

- Design system V4.0 (Quiet Precision) as isolated code on the design side: tokens for Dark, Daylight and Astro Red, 47 Figma icons, Precision Scale (Center Lock, Fixed Range), QCP, SCP, colour instruments, view model (Full/Clean/Panel, Fit/Fill, resizable split) and a component gallery at `/ds/gallery.html`; the page itself is not migrated yet (REQ-D06). Browser-tested without camera, 25 new tests.
- Design system: Precision Instrument Library V2.0 (every tick one real camera value, main values per parameter, AUTO/LOW/BULB as semantic values; Selector, Axis and Relative control; QCP and SCP share one value source; WB presets and Custom WB from the body's lists) and Color Controls V9.1 for Dark, Daylight and Astro Red (REQ-D06). Browser-tested without camera; 674 + 23 tests.
- Design system: Precision Detent Feedback (Instrument Library V2.1): one detent engine for drag, wheel, keyboard, touch and crown, one click/haptic pulse per detent and none at the limits, sound and haptic switchable, at most one camera command in flight with the newest wish winning, crown routing per context (REQ-D06). Browser-tested without camera.
- Design system: Typography Refinement V1.1 (optical spacing for the aperture sign, display and label tracking, real minus and one EV sign rule, smaller Kelvin unit, camera words as words, Color Controls value 70 px); tabular figures now really active; values fit their slots from 600 px down to watch width (REQ-D06). Browser-tested without camera.
- Star AF by ear: **HFR tone** (smaller star = higher tone, two beeps at the best value) and the words Sharper / Softer – turn back / At best while you turn the focus ring (USB and Wi-Fi, REQ-F24). USB camera-tested 2026-11-26, Wi-Fi not tested.

## 0.8.1 – 2026-11-26

- Tests tidied: duplicates dropped, USB/Wi-Fi flag table, 6 source-text checks now run the code; suite 15.5 → 13.9 s (REQ-F24, REQ-F35, REQ-F53, REQ-Q10). No behaviour change.
- Partial Color: press and drag around the colour ring, the camera follows live (Wi-Fi about 0.1 s per colour, measured 2026-11-24); only the newest colour is sent (REQ-F42). Browser-tested without camera.
- MCP actions show on the page: the control the MCP used looks pressed for a moment and the value changes, as if an invisible user worked the app; a message "MCP: …" and a list of the last 10 actions, failures in red (REQ-F35). Offline- and browser-tested, not camera-tested.
- Wi-Fi zoom stays sharp while focusing: with Auto the sharp live view size (1024/1280) falls back only when the picture nearly stands (under 4 fps), not at the usual 8–15 fps of 1280×960 (REQ-F55). Offline-tested.
- Settings changed by the MCP server look tapped on the page for 1.5 s, so you see what changed (REQ-F35). Wi-Fi camera-tested (ISO and exposure compensation).
- MCP `camera_settings`: in P, A and other modes where the camera picks the time, `shutspeedvalue` carries `shutter_live` (time in use from the Wi-Fi live view) and a note; without a fresh live view (USB, live view off) `shutter_live` is null with a note (REQ-F35). Offline-tested.
- Settings changed by the MCP server (or another page) appear on the open page within about 2 s: `/api/state` carries `props_rev`; not while busy or a setting list is open (REQ-F35). Wi-Fi camera-tested.
- Wi-Fi: outer AF grid fields focus where tapped instead of 1–2 fields further in; the camera accepts points outside its touch area (REQ-F04). Wi-Fi camera-tested (corners at 800×600 and 1280×960, Take picture at an outer field).
- HSL over USB tested: HSL button (JPG 2.1 s, ORF + 16-bit TIFF 2.6 s) and the automatic copy on save (REQ-I01, I04).

## 0.8.0 – 2026-11-24

- MCP full control (REQ-F35): with `--allow-write`, `--allow-shutter`, `--allow-erase` an assistant can focus, run live view, Playback, connect, shoot, record and erase; every camera change is a dry-run first and needs `confirm=true`. USB- and Wi-Fi-tested; time lapse, AE BKT, long exposure and erase offline-tested.
- MCP: any wish in words (scene, look, problem) becomes a settings plan from what the camera offers now (`camera_settings choices=true`, body-only steps), pro M-mode thinking, a verdict on the attached lens and which lens fits better; WB in kelvin also over Wi-Fi (REQ-F35) USB-tested.
- README easier to read: grouped highlights, short feature table; all details moved to FEATURES.md.
- Star AF (REQ-F24): live star-size (HFR) focus aid and hyperfocal readout in photo modes (USB and Wi-Fi), plus USB Auto Star AF (auto-switches to MF, tap-on-star focuses and auto-locks focus) and Live View Boost (Others, P/A/S). 9×9 grid and AF Area hidden while Star AF is on and in MF; "★AF" shown in the live view value strip. Camera-tested over USB 2026-11-23.
- MCP Photo Coach server (`em1-capture-mcp`): read-only tools and coach prompts; `--allow-write` adds a dry-run `camera_configure` (REQ-F35). USB- and Wi-Fi-tested.
- MCP cross-review fixes: WB in USB Movie, movie exposure by name, Focus stacking "ON" and Off first, 0.8 s wait after a Wi-Fi mode change (REQ-F35).
- USB mode dial shows in under 1 s: change poll 0x9489/0x9486 as OM Capture, no session rebuild; rebuild stays the fallback (REQ-F30). USB-tested.
- USB Focus Stacking sets itself up: Bracketing (d0a6), Focus BKT, stacking; no d020; waits while the camera merges; Off retries while busy; one-frame note (REQ-F69). USB-tested.
- Quit and Open in OM Workspace only from the computer itself, hidden on a phone (REQ-Q10).
- Disconnect during a request answers "Not connected" instead of an error; status poll no longer piles up.
- HSL copy in float32 (half the memory); `develop.py` moved to `tools/`.
- Test suite 42 s → 15 s.

## 0.7.9 – 2026-11-22

- Save to: click the Folder field for the folder dialog; one "Copy to computer" switch; short path; HSL hint (REQ-F62). USB-tested.
- USB without a card: pictures go straight to the computer; Focus Stacking and REC hidden (REQ-F61). USB-tested.
- USB: card change detected after reconnect (REQ-F61). USB-tested.
- USB: camera JPEG shown right after the shot (REQ-F60). USB-tested once.
- AF 9×9 grid in its real size, read from the camera; Wi-Fi outer fields focus at the touch-frame edge (REQ-F04). Tested.
- USB: Press halfway shows the real focus point (REQ-F34). Tested.
- Wi-Fi: focus tone for tap focus (REQ-F59). Tested.
- Wi-Fi zoom: sharp size on focus, Auto size on the computer too (REQ-F55). Tested.
- Wi-Fi: clear messages while Press halfway is held (REQ-F55). Tested.
- USB connect: waits for a busy camera instead of falling back (REQ-F61).

## 0.7.8 – 2026-11-21

Smooth zoom: over USB the camera's own Zoom AF (×3–×14) with drag, wheel and pinch, over Wi-Fi a smooth screen zoom; peaking that follows the focus ring; Erase over USB; Partial Color ring; Focus Stacking flag over USB.

- Wi-Fi smooth zoom (REQ-F55): wheel, trackpad and pinch zoom 1×–4× about the pointer, drag pans, an overview map shows the view; on a phone the live view gets sharper while zoomed. No camera command.
- USB smooth zoom (REQ-F54): zoom control 1× and ×3/×5/×7/×10/×14 (the camera's Zoom AF); drag, wheel and pinch move the crop, a click focuses (click focus not camera-tested; no AF with Four Thirds lenses while zoomed, manual p.56). Not offered while the camera is busy. Several open pages no longer fight over the zoom. Crop geometry measured on the camera.
- USB AF grid and tapped AF target were wrong after Zoom AF; both are right now (REQ-F54).
- Peaking reacts to the focus ring again (REQ-F52). Over Wi-Fi it needs a live view size of 640×480 or more.
- USB battery shows a rough level ("high" / "half or less") instead of a misleading percentage. It is the body battery: with an HLD-7 battery grip in use its charge is not reported over USB. Wi-Fi shows none, its value was not the battery (REQ-F19).
- USB Focus Stacking also sets the camera's stacking flag; camera-tested 2026-11-16, 8 frames plus the merged JPG (REQ-F38).
- Partial Color as a colour ring in the super control panel, Wi-Fi only; camera-checked (REQ-F42).
- After a Wi-Fi drop the app shows "Camera not found" and restarts the live view by itself; message camera-tested; the restart was seen working once on 2026-11-15, but only after 47 s (wait to be shortened) (REQ-Q14).
- Phone over Wi-Fi starts the live view at 800×600 at most (about 21 fps) (REQ-F45).
- Live view status line shows the displayed fps and "libgphoto2" on the slower USB fallback (REQ-F51).
- Playback: Erase deletes selected pictures over USB (JPG and ORF, confirm first, needs `--allow-write`); camera-tested 2026-11-15 with the own USB layer (libgphoto2 fallback untested). Not available over Wi-Fi (REQ-F50).
- Playback on a phone: pinch out of 5×5 opens Calendar display and back (REQ-F48).
- Faster, steadier live view: the next frame is requested while one decodes (USB 1024×768 29.9 fps, Wi-Fi 640×480 29.8 fps); webcam and second-monitor windows use the same loop and recover after a bad frame or reconnect; no "Broken pipe" log noise (REQ-Q13).
- README rewritten for easier reading; speed tables updated with the 2026-11-15 measurements (USB 30 fps up to 1024×768; Wi-Fi 640×480 30 fps, 800×600 about 21, 1024×768 about 12, 1280×960 about 8).

## 0.7.7 – 2026-11-15

A steadier USB connection and a cleaner phone view.

- USB: the connect log line gives the time of each step; measured 2026-11-15: session 0.3–0.7 s, card index 0.1 s, PC control about 5 s (the camera's own time) (REQ-Q12).
- Two connect requests at once (auto-connect plus a click, or two tabs) make one connection; Disconnect during a slow connect waits for it. Camera-tested over USB 2026-11-15; Wi-Fi not tried (REQ-Q12).
- Level gauge right after connecting: no failed request and no false "Level ✓". Camera-tested 2026-11-15 (REQ-F23).
- USB: a vanished camera (cable pulled, switched off) no longer makes the app rebuild the session in a loop, which blocked other apps. It shows "Camera not found. Is the cable plugged in?" and reconnects by itself, retrying after 5, 10 … 60 s. Camera-tested 2026-11-15: live view back about 9 s after plugging in (REQ-Q11).
- Phone view (REQ-F49): the app picks the live view size itself (Wi-Fi adaptive, USB 1024×768) and hides the second-monitor and webcam windows. Tried on an iPhone 2026-11-15.

## 0.7.6 – 2026-11-14

Playback on a phone: pinch to zoom, swipe between pictures, pinch for the Index display size.

- Single-frame view: pinch zooms up to 6×, one finger pans, double tap toggles 1× / 2.5×, a sideways swipe or wheel shows the next or previous picture. Swipe tried 2026-11-14 (REQ-F48).
- Index display on a phone: pinch changes the grid (S 5×5, M 3×3, L 2×2). Tried on an iPhone 2026-11-14 (REQ-F48).
- Calendar display on a phone: the badge shows only the number of shots, so the day stays visible (REQ-F48).
- The **Phone** button (with `--lan`) is also on the start screen (REQ-F47).
- Turning the phone resets a leftover page zoom and redraws the level gauge; the rotation fix is not confirmed yet (REQ-F48).

## 0.7.5 – 2026-11-14

The app on a phone, a start screen that connects by itself, and a live view size that follows the phone.

- Wi-Fi on phone width: the live view size starts to fit the screen and steps down one size when frames come too slowly (under 12 fps or over 18 % lost for 4 s); a chip "Auto · 800×600" shows it. Camera-tested at phone width 2026-11-14 (800×600 → 640×480, 27–30 fps); the 4 s wait is not camera-tested yet. Desktop and USB keep the manual size (REQ-F45).
- Start screen connects by itself to the connection used last time after a 2 s countdown ("Stay here" stops it). Camera-tested over Wi-Fi 2026-11-14; USB not tested (REQ-F46).
- Open the app on a phone (start with `--lan`): the **Phone** button shows a QR code; the phone gets a key that is new at every start (cookie, 12 hours), other devices see only a note. Tried with a phone 2026-11-14 over Wi-Fi (REQ-F47).

## 0.7.4 – 2026-11-14

- Level gauge feedback (USB): within 0.3° of level the line turns green and a chip says "Level ✓"; an optional sound (off by default). "Hold angle" keeps the current horizon and tilt as target for repeat shots and shows the deviation until "Clear angle". Tried by the user 2026-11-14 (REQ-F44).

## 0.7.3 – 2026-11-14

- USB level gauge: the live view shows the camera's tilt ("Horizon" and "Tilt" as in the manual, p.37), read live under PC control and polled every 0.15 s while shown; live view stays at 30 fps. Own PTP layer only, not over Wi-Fi (no tilt in its data). Off by default, switch "Level gauge". Camera-tested 2026-11-14 (REQ-F23).

## 0.7.2 – 2026-11-14

- AF frame on tap without the grid: with "Show AF targets" off a tap still shows the chosen frame for about 4 s (white focusing, green in focus, red no focus). Camera-tested over Wi-Fi 2026-11-14, tried over USB the same day (REQ-F41).
- ISO AUTO over Wi-Fi: the ISO the camera picks now shows small under AUTO ("now 800"), not in Movie mode. Not over USB (no live value). Camera-tested over Wi-Fi 2026-11-14 (REQ-F29).
- Wi-Fi smoke test of the 0.7 page 2026-11-14: live view 19 fps without gaps, tap focus, shutter blackout, Take picture with the last-shot picture.

## 0.7.1 – 2026-11-14

Fixes in the browser page found while using 0.7.0.

- Calendar display: the day is large and bold, the number of shots a yellow badge.
- HSL window grows with the before/after picture; the comparison is a line with a handle in the picture. Camera-tested 2026-11-14.
- No ghost copy of the picture when dragging in the live view or the HSL comparison.
- INFO button in the single-frame view cycles Overall display, Simplified display, Image only.
- Live view off: the picture area turns dark instead of keeping the last frame.
- The live view overlay is switched off for now (a guide picture was mistaken for a multiple exposure); it returns as a real multiple exposure (REQ-F43).

## 0.7.0 – 2026-11-14

Faster USB, closer to Wi-Fi: the app's own PTP layer, USB settings, focus ring, movie and Focus Stacking over USB, and live view and focus fixes found at the camera.

### USB backend and performance
- New USB backend on the app's own PTP layer (`omcap/ptp.py`) with a gphoto2-compatible shim. Option `--usb-backend auto|ptp|gphoto2`: `auto` (default on macOS) uses the PTP layer and falls back to libgphoto2; elsewhere libgphoto2 stays the default. Camera-tested on macOS 2026-11-13 (REQ-F28).
- Card index with a disk cache: about 2950 files take 44.8 s on the first connect and 6.9–9.2 s later (libgphoto2: about 9 s plus a 51–72 s index in the background).
- Measured: live view 1024×768 at 19.5–26.4 fps (libgphoto2 14–20.6), 1280×960 at 15 fps without the self-built libgphoto2 (REQ-F36); tap focus 0.4–0.6 s (libgphoto2 1.3–1.5 s); Take picture 4.5–4.8 s.
- Fix: USB live view stayed black after the camera was switched off and on; the PTP layer now sets 1024×768 when the live view size is 0. Camera-tested 2026-11-13 (REQ-F28).
- Fix: USB live view went black for seconds after a shot or a written setting because the camera's mode-dial event came late; the event now counts only 6 s after a command. Camera-tested 2026-11-13 (REQ-F30).
- Fix: USB focus said "In focus" when the camera had not focused. The app now reads the camera's own focus result, answers "no focus" at once and Take picture in S-AF answers after about 1 s instead of 20 s (REQ-F34).
- Main live view fetches one frame per request instead of MJPEG, which could stay black after a hiccup; the `?view=` windows (webcam, OBS) keep MJPEG. Camera-tested over USB 2026-11-13, not yet over Wi-Fi.
- Camera-tested with the PTP backend: BULB, LIVE TIME, LIVECOMP (REQ-F31), mode dial (REQ-F30), interval shooting, AE bracketing and a full browser session. Not tested: Linux.

### Shooting and settings
- The last-shot picture fades out after 6 s; a red "No focus" chip shows for 4 s when AF fails (Wi-Fi after a tap only) (REQ-F34).
- Shutter blackout: Take picture shows a short black frame (about 0.18 s) over the live view, USB and Wi-Fi (REQ-F39).
- Fix: clicking the last-shot picture opened no single-frame view. Camera-tested 2026-11-13.
- USB Focus Stacking: On/Off in the LV super control panel, P/A/S/M only (manual p.82, 174); the camera switches by itself to Silent Sequential H, electronic shutter and flash off, and Take picture waits for the merged picture. Camera-tested 2026-11-13: 16 frames plus the merged JPG in 17.7 s. Drive, Flash and AE bracketing are hidden while it is on (not camera-tested). Not over Wi-Fi (REQ-F38).
- USB movie recording: Start/Stop presses the camera's REC button, so it records in every shooting mode (manual p.26), not only Movie mode. PHOTO STORY and some SCN modes read as P, so the camera does not record there although the button shows. Camera-tested 2026-11-13. Movie settings over USB not yet (REQ-F37).
- USB focus ring (MF): Near 3/2/1 and Far 1/2/3 in the AF section, shown with AF mode MF or S-AF+MF. Camera-tested 2026-11-13, about 0.1 s per step. Not over Wi-Fi (REQ-F28).
- USB LV super control panel: AF mode, Metering mode, Flash mode, Record mode, Aspect ratio, Image stabilizer, Face priority, only in P/A/S/M (manual p.24). Read and write tested 2026-11-13. Not over Wi-Fi (REQ-F10).
- USB: fractional shutter speeds, ISO AUTO/LOW, read-only flags and the lens-limited aperture list are named like on the camera (REQ-F10); Take picture focuses on the tapped AF field (REQ-F34).

### App and docs
- CI: the Python 3.9 job runs on `ubuntu-24.04`; `main` was red since 0.6.0 (REQ-Q08).
- The app releases the camera when stopped with Ctrl+C or `kill`.
- README: USB on Linux works over libgphoto2 (not tested); a user runs the app with a PEN-F (REQ-G08).
- 182 offline tests pass (2026-11-14); CI green on Ubuntu 24.04 (Python 3.9, 3.12) and macOS (3.12).

### Not in 0.7 (moved to 0.7.x / 0.8)
- Camera changes without rebuilding the USB session, `getrecview` over Wi-Fi, capture target over USB, flash compensation, movie settings over USB, Focus BKT without stacking.

### Known issues
- Single-frame live view not yet tested over Wi-Fi.
- Focus Stacking: hiding Drive, Flash and AE BKT, and refusing it at BULB / LIVE TIME / LIVECOMP, not camera-tested.
- A touch AF target set on the camera monitor overrides the app's AF field.
- USB movie: the app does not check that the camera really records.
- LIVECOMP: a stop press 4–8 s after the start is ignored by the camera; the app does not show that the exposure still runs.
- Mode dial over USB: each turn rebuilds the session (8–10 s).
- Wi-Fi drops out on the Mac now and then; once "No route to host" from the launcher (Local Network permission suspected).
- USB with libgphoto2 (Linux): live view pauses up to about 70 s while the card list is read.
- USB, All Targets + Halfway: the green AF field may not match the camera's focus.
- A lens change is only noticed with the next photo.

## 0.6.0 – 2026-11-13

- Wi-Fi Take picture uses `exec_takemotion` with the tapped AF point: the live view keeps running and a shot takes 1.2–1.5 s instead of about 7 s. Long exposures, self-timer and Movie mode keep the old route (REQ-F34). Camera-tested.
- USB: LIVE TIME is recognised when libgphoto2 reports a raw fraction; "Off" in the M-mode quick select falls back to 1/60 s. Camera-tested over USB (REQ-F31).
- Single-frame view: "Open in OM Workspace" (only when installed) opens the ORF, otherwise the JPG (REQ-F17).
- Playback thumbnails open the single-frame view; Playback lies above the shutter bar in narrow windows (REQ-F27).
- USB live view size choice up to 1280×960 with libgphoto2 2.5.34.1 or later; measured 13.8 fps (REQ-F36).
- CI on GitHub: offline tests on every push and pull request (Ubuntu with Python 3.9 and 3.12, macOS 3.12) (REQ-Q08).
- "Quit E-M1 Capture" button (second click confirms) (REQ-Q10).
- Clearer messages: second start says how to stop the running app, USB connect failure says what to check, missing gphoto2 says how to install it; README has a "Stop" section.
- USB live view: fixed a stall after connecting; the mode-dial check runs every 3 s. Measured 14.3 fps, Take picture 4.7–5.3 s.
- Controls appear only in the shooting modes where the camera allows them (manual logic); in Movie mode the exposure controls follow the movie exposure mode (manual p.71).
- USB: turning the mode dial is detected and the app rebuilds the session by itself; iAUTO, ART, SCN and PHOTO STORY show as P (REQ-F30).
- M mode: quick select BULB / LIVE TIME / LIVECOMP and Off. Camera-tested on Wi-Fi and USB (REQ-F31).
- The "not running" hint names the command that works in every installation.

## 0.5.0 – 2026-11-12

- Wi-Fi live view reads the camera's RTP extension data (`GET /api/lvext`): free shots, AF result, shutter speed, aperture, exposure compensation, ISO and focal length; no level gauge or face frames (REQ-F29).
- Faster start: the card list is saved on the computer and shown at once, the camera's list follows. Wi-Fi measured: live view after 1.7 s instead of 10 s (REQ-F27).
- Turn off camera and Reset Share Order ask for a second click on the page, because embedded browsers suppress browser dialogs.
- Wi-Fi after Take picture: only the newest folder is read, and the next picture is asked by its DCF name. Measured: picture in the index 8.4 s after the click instead of 24 s (REQ-F16, REQ-F27).
- USB: the saved card list shows while the camera reads its index (about 1 min) and the camera list loads by itself (REQ-F27).
- `--timing` prints every request with its duration.
- Wi-Fi: live view start retries on a 520 right after switching to shooting mode; the header shows battery, free shots and focal length, and the value strip the ISO and exposure the camera uses in auto modes (REQ-F29).

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
