# E-M1 Capture – design

Design canvas (private to the maintainer, ask for access): Live View, 2026-11-11.
Tokens: [`tokens.css`](tokens.css). Implemented in version 0.4.0 (2026-11-11); the build order below is done.

## Task-led redesign prototype

The 2026 redesign keeps the camera terminology and the live-view-first principle, but replaces the
long control stack with four task groups inspired by the current OM SYSTEM menu hierarchy:

1. **Camera** — shooting mode and exposure values.
2. **Focus** — AF Area, AF target visibility and manual-focus drive.
3. **Tools** — movie, time lapse, bracketing and long exposure.
4. **Files** — transfer settings and playback.

The shutter and self-timer remain visible in every group. Desktop uses a compact control rail beside
the image. Mobile turns the group selector into bottom navigation and keeps capture directly above it.
The Apple Watch-sized companion intentionally exposes only the live frame, the three most important
shooting values, autofocus and shutter release.

Typography now has explicit display, title, heading, body, metadata, label and camera-value levels.
Camera values retain IBM Plex Mono; navigation and explanatory text retain Inter/system UI.

### Manual-led fast workflow

The E-M1 manual establishes a mode-dependent control hierarchy rather than a flat settings grid:

- **P:** the camera balances shutter and aperture; exposure compensation is the immediate adjustment
  (manual pp. 38, 51).
- **A:** aperture is primary and the camera selects shutter speed (manual p. 39).
- **S:** shutter speed is primary and the camera selects aperture (manual p. 40).
- **M:** shutter speed and aperture are both primary; exposure compensation is unavailable
  (manual pp. 41, 51).
- **Movie:** P/A/S/M movie exposure is selected before recording; exposure values cannot be changed
  while recording (manual p. 71).
- **Focus:** the AF target is selected directly in the frame; AF Area changes the target-selection
  strategy rather than the shooting workflow (manual pp. 54–56).

The interface therefore shows only the mode-relevant exposure controls plus ISO and white balance by
default. Drive, color, metering, record mode and other Super Control Panel settings remain available
behind **All settings**. Navigation uses the user tasks **Shoot, Focus, Sequence, Review** rather than
camera implementation categories.

The **Sequence** navigation icon follows the E-M1 Sequential H/L symbol: stacked image frames with
motion lines on the left (manual p. 57). The H/L speed suffix is omitted because the tab also contains
bracketing, time lapse and movie sequences.

Playback icons follow the E-M1 touch UI (manual p. 34): Index is a framed thumbnail matrix, Calendar
adds a clock/date badge to that matrix, and Full-picture/close-up uses an image frame with the manual's
zoom marker.

On mobile, live-view size is automatic rather than another shooting control. The app starts at the
smallest stream that still covers the physical display resolution, up to 1280×960, then steps down
when a rolling five-second sample falls below 12 complete fps, exceeds 18% damaged frames, or stalls.
It never adapts while the camera is intentionally busy focusing, shooting, recording or indexing.
Desktop keeps the explicit size selector for monitoring and focus-check workflows.

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
7. **Show a control only in the shooting modes where the camera lets you select it** (maintainer decision
   2026-11-12), following the manual's per-mode logic: e.g. BULB / LIVE TIME / LIVECOMP only in M, Art filter
   only in ART, AE BKT not in M. Over USB the modes iAUTO, ART, SCN and PHOTO STORY read as P and are treated as P.
   Where the manual is unclear or wrong, the camera decides: test it and record the result (maintainer, 2026-11-12).
8. **Handle the picture the way people do today, not the way the camera did in 2013** (maintainer decision
   2026-11-18). Zoom and drag follow the habits of current photo apps, maps and the iOS Camera app; the old
   flow of the camera and of Olympus/OM Capture (button for the zoom frame, arrow keys, ratio list, frame
   jumps) is deliberately overwritten. The camera's own functions stay the engine underneath – the app gives
   the E-M1 a modern touch, a "rebirth", without changing what the camera does.

## Zoom and drag (USB, REQ-F54) – modern handling on top of Zoom frame AF

The engine is the camera's Zoom frame AF/zoom AF (E-M1 manual p.56, ×3/×5/×7/×10/×14): a sharp crop from the
sensor, not an enlarged screen picture. The handling on top follows today's habits:

| Habit (today) | In the app | Instead of (old flow) |
|---|---|---|
| The point under the finger/pointer stays put while zooming | Wheel, trackpad and pinch zoom about the pointer; continuous while the gesture runs, snaps to the camera's next ratio at rest | Zoom button → zoom frame → ratio list, always about the frame |
| Grab the picture and move it | Drag moves the picture directly, without delay; the sharp crop moves over the last normal frame, so there are never black edges | Four arrow keys, one step per press |
| Where am I? | Overview map bottom left: whole picture, visible view, camera crop; click or drag in the map moves the view | No overview while magnified |
| Tap = act | A click in the zoomed view focuses (half press, no shot) | Separate AF button |
| Nothing flickers | One camera command only at rest (after the pointer is up / the wheel has stopped); the old crop keeps flowing until the new one is recognised in the picture; normal frames never show while zoomed; the view then glides to where the camera really is | Picture blanks or jumps on every frame move |

Rules learned on the camera (2026-11-16/18, maintainer's local research notes): the crop is exactly
1/ratio; the point (`0x9483`) is in the grid of the current live view size, with x landing 1.135× as far from
the centre as sent; the crop centre stays inside [0.1+0.5/r, 0.9−0.5/r]; a ratio change while zoomed goes
`d04b` off → `d0cf` → point → on; the live view lags 1–5 frames behind a switch, so the page recognises the new
crop by picture, not by time. One page drives the zoom; other open pages follow without sending.

Arrow buttons stay as a keyboard path (accessibility). Wi-Fi has no Zoom frame AF command; there the app keeps
its own screen zoom (REQ-F55) with the same handling and no camera command: wheel/pinch zoom continuously about
the pointer (1×–4×, the live view is at most 1280×960), drag pans inside the picture, the 1×/2×/4× buttons stay
and light up on a match, the overview map shows the current live frame and the visible view, and a click without
drag picks the AF target at that picture point, also while zoomed. On the phone the live view size goes up
while the zoom rests above 1.5× (1024×768 up to 2.5×, 1280×960 above) and returns to the adaptive size at 1×;
if the sharp size is too slow the app falls back and uses it only for focusing ("sharp on focus").

**Why it matters beyond comfort:** this precise, calm zoom is the base of the **Star AF aid (REQ-F24)** –
measuring star size/sharpness in the magnified sensor crop and focusing with the focus ring or the focus drive
(`0x9487`) needs a steady, sharp, correctly placed crop at ×10/×14. This zoom is the base for REQ-F24.

## Live view and shutter always together

The live view and *Take picture* are visible at the same time on every screen size, without scrolling:
- **Wide (> 1100 px):** the page fits the window; only the right column scrolls, and the shutter block
  sticks inside it (top and bottom). The live view box is limited by the window height.
- **Narrow, tablet, phone portrait (≤ 1100 px):** the live view sticks to the top (max. 45 % of the
  height), the shutter block is a bar fixed at the bottom, the panels scroll in between.
- **Phone landscape (≤ 520 px high):** three columns, nothing sticky.
- The live view box always stays exactly 4:3 (width derived from the available height), so the AF grid
  lies on the picture.

## Screen layout (computer)

| Area | Content |
|---|---|
| Header | App name, connection chip (E-M1 · Wi-Fi/USB), *Write enabled* chip, lens, battery (USB), card space, Playback, On the computer, Disconnect, Turn off camera (Wi-Fi) |
| Live view | Image, AF grid, Displayed Grid, Histogram, Highlight&Shadow, Peaking, focus status chip, self-timer countdown, last shot, value strip |
| Under the image | Zoom: over USB 1×/×3–×14 (camera Zoom frame AF, see "Zoom and drag"), over Wi-Fi smooth view zoom 1×–4× with buttons 1×/2×/4× (app only, see "Zoom and drag"), Size (Wi-Fi; USB only with libgphoto2 2.5.34.1 or later), live view aids as toggles, Second monitor, Webcam (OBS), Stop live view; one status line |
| Right column (340 px) | LV super control panel: shooting mode, value tiles; AF target (USB); read-only settings line; Movie and Shooting options; Self-timer; Press halfway + Take picture; Save to |

States: live view off, focusing (amber field), in focus (green field), self-timer running,
recording a movie, read only, Wi-Fi drop-out (last good frame kept, "No signal for N s").

## Phone layouts (redesign)

- **Landscape:** values on the left rail, image in the middle, shutter column on the right
  (LV super control panel, self-timer, Take picture 76 px, Press halfway, last shot).
- **Portrait:** header, image (full width), value chips, one value editor (scale), self-timer,
  LV super control panel button; bottom row last shot · Take picture 84 px · Press halfway.
- **Phone header (≤ 700 px):** Playback, ⋯ and Turn off camera; ⋯ opens Reset camera, Disconnect and
  Quit E-M1 Capture (user 2026-11-21: reachable, but out of the way).

## Playback and picture info

- **Index display:** thumbnail grid grouped by day, sizes S/M/L, multi-select (save to computer),
  "Share Order only" filter, badges ORF+JPG, movie length, Share. Optional one-line EXIF on each
  thumbnail (mode, shutter speed, aperture, ISO).
- **Grid zoom:** pinch apart moves 4×4 → 3×3 → 2×2; pinch together moves 2×2 → 3×3 → 4×4
  → Calendar. Trackpad pinch follows the same sequence. The compact toolbar mirrors these states
  with icons instead of explanatory text.
- **Calendar display:** month grid (weeks start Monday), a thumbnail and a count per day; a click
  opens that day in Index display.
- **Single-frame playback:** picture at 4:3 with the value strip, previous/next, Fit / 100 %
  (close-up playback), and the camera's INFO cycle **Image only / Simplified display /
  Overall display**. Overall display shows a histogram and the EXIF list (shooting mode, shutter
  speed, aperture value, exposure compensation, ISO, white balance, metering mode, flash, focal
  length, lens, Picture Mode, color space, record mode, pixel count, date/time, file number) and,
  if the maker note records it, the AF target used. Buttons: Overlay on live view, HSL…, Save to
  computer. The same info opens from the last shot after Take picture.
- Protect and Share Order editing stay on the camera. Erase works over USB only, in Select mode, with a confirm bar (Wi-Fi has no erase CGI).
- Watch-sized view: the status line (live view size, fps, "Camera not found") is hidden on purpose; the picture alone shows whether the live view runs.

## Terms (checked against the E-M1 manual)

| In the app | Manual | Page |
|---|---|---|
| LV super control panel | "LV super control panel" (live view), "super control panel" (viewfinder) | p.19, p.24 |
| Level gauge (Horizon, Tilt) | "Level gauge" (INFO cycle in live view; tilt on the vertical bar, horizon on the horizontal bar) | p.35, p.37 |
| Zoom AF, Zoom ratio, Move the zoom frame | "Zoom frame AF/zoom AF", zoom frame, zoom ratio ×3–×14 (the app button switches the magnified stage, zoom AF) | p.56 |
| Hold angle, Clear angle, Angle matched, Δ Horizon / Δ Tilt, "Level ✓", Sound | app terms (no manual equivalent) for a held target horizon/tilt and the level feedback, built on "Horizon" and "Tilt" | p.35, p.37 |
| Phone, Open on a phone, Stay here, Auto · {size}, Live view adjusted to … | app terms (no manual equivalent) for the phone link, auto-connect and the automatic live view size | – |
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
| Time lapse, AE BKT, LIVE TIME, LIVECOMP | Time Lapse Settings, AE BKT, LIVE TIME, LIVECOMP | p.41, p.85, menus |
| Press halfway / Take picture | "press the shutter button halfway" / "press fully" | p.20 |
| Index display, Calendar display, single-frame playback, close-up playback | same | p.31–33, p.63 |
| Image only / Simplified display / Overall display | INFO button cycle during playback | p.62 |
| View zoom 1×–4× (smooth; buttons 1×/2×/4×) | not a camera function (the camera's own is Magnify / Zoom frame AF, ×3–×14); label it as the app's view zoom | – |

## Build order for `omcap/web/index.html` (done in 0.4.0; kept as record)

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
