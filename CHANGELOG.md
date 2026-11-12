# Changelog

## Unreleased

- Wi-Fi live view: the RTP extension data (OPC protocol) is read instead of skipped; `GET /api/lvext` shows what the camera sends. The E-M1 Mark I sends free shots, AF result, shutter speed, aperture, exposure compensation, ISO (also with ISO Auto) and focal length; no level gauge or face frames (REQ-F29).
- Faster start (REQ-F27): the card list is saved on the computer (`out/cache/cardlist_wifi.json`, `_usb.json`) and shown at once; the camera's list follows in the background after the live view has started. Wi-Fi measured: header after 1 s, live view after 1.7 s (before: card space after 7 s, live view after 10 s, card list 17 s).
- Turn off camera and Reset Share Order ask for a second click on the page instead of a browser dialog, which embedded browsers (e.g. the Claude app's browser) suppress; before, the button did nothing there.
- Wi-Fi after Take picture: only the newest card folder is read and merged into the saved list, once for the gallery and the last shot together (before: whole card plus newest folder, up to three times). Measured: picture in the index and last-shot corner 15 s after the click instead of 24 s; a second shot no longer waits up to 23 s (REQ-F16, REQ-F27).
- `--timing` prints every request with its duration (performance checks).
- Wi-Fi: live view start retries when the camera answers 520 right after switching to shooting mode.
- Wi-Fi: during live view the header shows free shots and the current focal length, and the value strip shows the ISO in use with ISO Auto and the shutter speed and aperture the camera uses in auto modes (REQ-F29).

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
