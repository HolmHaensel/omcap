# Changelog

## Unreleased

- HSL in the web app (USB and Wi-Fi): HSL button per computer file and in the single-frame view, preset dialog with before/after slider, results in `out/hsl/`, optional auto-apply when saving to the computer.

## 0.2.0 – 2026-11-09

- Header shows free card space (Wi-Fi and USB) and battery level (USB); read-only camera settings Anti-Shock, Silent, Noise Reduct., BULB/TIME Timer and Digital Tele-converter under the LV super control panel (Wi-Fi).
- Playback over Wi-Fi: Share Order filter with count, Save all to computer and Reset Share Order; movie length in the single-frame view.
- Wi-Fi: Turn off camera button in the header (`exec_pwoff`, with confirmation); returns to the start screen.
- Live view aids computed in the browser: Histogram (luma, optional RGB), Highlight&Shadow warning and Peaking with color choice.
- Software HSL colour profiles modelled on the PEN-F COLOR dial (`omcap.hsl`: 12 sectors, H/S/L −7…+7, 3 slots, CLI for ORF/JPG).
- Self-timer (Off / 2 s / 10 s) next to Take picture with a countdown over the live view; click again to cancel.
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
