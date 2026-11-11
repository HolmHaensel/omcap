# E-M1 Capture – design

Design canvas (private to the maintainer, ask for access): Live View, 2026-11-11.
Tokens: [`tokens.css`](tokens.css). Planned for version 0.4.

## Principles

1. **Live view is the hero.** It takes the left/centre of the screen at 4:3; panels sit beside it on the
   computer and around it on the phone, never on top by default.
2. **The 9×9 AF grid is never covered.** Chips (status, histogram, last shot) sit at the edges of the
   image, outside the area most people tap.
3. **One bright control:** *Take picture*. Everything else is quiet.
4. **Values read like the camera:** a value strip under the image (mode, shutter speed, aperture,
   exposure compensation, ISO, white balance) in a monospaced font, and value tiles in the
   *LV super control panel*.
5. **Colour has meaning:** amber = selected or working, green = in focus / connected,
   red = recording or turning the camera off. Nothing else is coloured.
6. **Hide what the connection cannot do** (maintainer decision 2026-11-11): USB-only functions do not
   appear over Wi-Fi and vice versa, so the screen stays calm. Only missing write permission is shown
   as disabled with a reason ("Write is off …").

## Screen layout (computer)

| Area | Content |
|---|---|
| Header | App name, connection chip (E-M1 · Wi-Fi/USB), *Write enabled* chip, lens, battery (USB), card space, Playback, On the computer, Disconnect, Turn off camera (Wi-Fi) |
| Live view | Image, AF grid, Displayed Grid, Histogram, Highlight&Shadow, Peaking, focus status chip, self-timer countdown, last shot, value strip |
| Under the image | View zoom 1×/2×/4× (app only), Size (Wi-Fi), live view aids as toggles, Second monitor, Webcam (OBS), Stop live view; one status line |
| Right column (340 px) | LV super control panel: shooting mode, value tiles; AF target (USB); read-only settings line; Movie and Shooting options; Self-timer; Press halfway + Take picture; Save to |

States: live view off, focusing (amber field), in focus (green field), self-timer running,
recording a movie, read only, Wi-Fi drop-out (last good frame kept, "No signal for N s").

## Phone (Wi-Fi only)

- **Landscape:** values on the left rail, image in the middle, shutter column on the right
  (LV super control panel, self-timer, Take picture 76 px, Press halfway, last shot).
- **Portrait:** header, image (full width), value chips, one value editor (scale), self-timer,
  LV super control panel button; bottom row last shot · Take picture 84 px · Press halfway.

## Playback and picture info

- **Index display:** thumbnail grid grouped by day, sizes S/M/L, multi-select (save to computer),
  "Share Order only" filter, badges ORF+JPG, movie length, Share. Optional one-line EXIF on each
  thumbnail (mode, shutter speed, aperture, ISO).
- **Calendar display:** month grid (weeks start Monday), a thumbnail and a count per day; a click
  opens that day in Index display.
- **Single-frame playback:** picture at 4:3 with the value strip, previous/next, Fit / 100 %
  (close-up playback), and the camera's INFO cycle **Image only / Simplified display /
  Overall display**. Overall display shows a histogram and the EXIF list (shooting mode, shutter
  speed, aperture value, exposure compensation, ISO, white balance, metering mode, flash, focal
  length, lens, Picture Mode, color space, record mode, pixel count, date/time, file number) and,
  if the maker note records it, the AF target used. Buttons: Overlay on live view, HSL…, Save to
  computer. The same info opens from the last shot after Take picture.
- Protect, Erase and Share Order editing stay on the camera; the app only reads the card.

## Terms (checked against the E-M1 manual)

| In the app | Manual | Page |
|---|---|---|
| LV super control panel | "LV super control panel" (live view), "super control panel" (viewfinder) | p.19, p.24 |
| Shooting mode iAUTO / P / A / S / M / ART / Movie | iAUTO, Program shooting, Aperture priority, Shutter priority, Manual shooting, ART, movie mode | p.18, p.38–50 |
| Shutter speed, Aperture, Exposure compensation | Shutter speed, Aperture value, exposure compensation | p.40–41, p.51 |
| ISO | ISO sensitivity (panel legend), ISO (menus) | p.24, p.59 |
| White balance | White balance | p.58 |
| Sequential shooting/self-timer · Single-frame | Sequential shooting/self-timer; single-frame shooting, Sequential H/L, 12 SEC, 2 SEC, Custom Self-timer | p.24, p.57 |
| Picture Mode, Art filter | Picture Mode / Picture mode, Art filter | p.70 |
| AF target (AF Area): All Targets, Single Target, Small Target, Group Target | "Choosing a focus target (AF Area)", same four names | p.54–55 |
| Displayed Grid | Displayed Grid (options shown as icons; the app names them Rule of thirds, Crosshair, Grid) | p.95 |
| Histogram, Highlight&Shadow, Peaking | Histogram Settings, Highlight&Shadow, MF Assist › Peaking, Peaking Settings | p.95, p.102, p.176 |
| Anti-Shock, Silent, Noise Reduct., BULB/TIME Timer, Digital Tele-converter | same | menus |
| Time lapse, AE BKT, LIVE TIME, LIVECOMP | Time Lapse Settings, AE BKT, LIVE TIME, LIVE COMP | p.85, menus |
| Press halfway / Take picture | "press the shutter button halfway" / "press fully" | p.20 |
| Index display, Calendar display, single-frame playback, close-up playback | same | p.31–33, p.63 |
| Image only / Simplified display / Overall display | INFO button cycle during playback | p.62 |
| View zoom 1×/2×/4× | not a camera function (the camera's own is Magnify / Zoom frame AF, ×3–×14); label it as the app's view zoom | – |

## Build order for `omcap/web/index.html` (feature-dev, one step per commit)

1. Load `design/tokens.css` (inline copy in the page) and switch colours, type and radii to tokens; dark only.
2. New page skeleton: header row, two columns (live view 1044 px max / right column 340 px), responsive
   stack below 1100 px.
3. Live view overlays: value strip, focus status chip (amber → green), last shot bottom-right,
   histogram top-left; keep the AF grid hit area unchanged.
4. Toolbar under the image: view zoom segmented control, Size, aids as toggle chips, Second monitor,
   Webcam, Stop live view.
5. LV super control panel: mode segmented control (Wi-Fi) or read-only mode card (USB), value tiles
   with the editing state, read-only settings line.
6. Shutter block: self-timer segmented control, Press halfway (pressed state), Take picture, Save to.
7. Hide functions the connection cannot do; disabled-with-reason only for read-only mode; States (live view off, recording, read only,
   drop-out with last good frame and "No signal for N s").
8. Playback: Index display and Calendar display in the new style; single-frame playback with the
   info cycle and the Overall display panel (EXIF from `omcap/exif.py`, extended beyond lens data).
9. Phone layouts (portrait/landscape) as a media-query version of the same page.

Every step keeps all I18N keys, USB/Wi-Fi parity and the existing tests; camera tests happen in one
bundle after step 7.
