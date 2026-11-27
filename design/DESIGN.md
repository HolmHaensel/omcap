# E-M1 Capture – design

Design canvas (private to the maintainer, ask for access): Live View, 2026-11-11; design system board
"Quiet Precision" v0.2, 2026-11-26.
Tokens: [`tokens.css`](tokens.css) (production values, implemented in version 0.4.0 on 2026-11-11; the build
order at the end of this file is done). The confirmed 1.0 direction below is recorded here first; the page and
`tokens.css` are not yet migrated to it. V4.0 tokens and components exist isolated in `omcap/web/ds/` (section below).

## Design system 1.0: Quiet Precision (v0.2, confirmed direction 2026-11-26)

**Timeless hardware. Evolving intelligence.** Camera Control keeps the camera's own language and direct
operation. Computational Extension uses available sensor data within the limits of optics, signal, exposure and
the body. Intelligent Assistance (MCP) helps the photographer understand and apply supported choices. People
who know the E-M1 take a first shot without onboarding; task shortcuts (e.g. preparing a macro series) shorten
repeated work while each camera control stays within reach.

Authority: the maintainer confirms design decisions. The E-M1 manual defines terms and intended operations; the
USB/Wi-Fi parity table and tests on the real camera decide what a body, firmware, connection and mode actually
support. This section records decisions only. Nothing in the page changes until a migration step is agreed.

### Status of each decision

| Status | Covers |
|---|---|
| **Confirmed** | Master Reference 01 (composition), Dark palette and roles, Inter hierarchy, Aperture scale correction, Center Lock as preferred scale model (Fixed Range as alternative), Precision Color Control V9, Snap to Reality, iconography direction, Control View / Fullscreen with Fit and Fill, MCP approval flow |
| Studies | Scale model per parameter, V9 reconstructions, device layouts (60/40 landscape split, richer Watch controls) |
| To validate | Long value lists and their ends, colour capability per body, Color All and Monochrome semantics, keyboard and touch, native reach, Watch sizing, Daylight and Astro Red themes, contrast over real live view, orientation and AF mapping |
| **Open (not built)** | The individual photographic glyphs of the icon family (see Iconography). Not implemented until the maintainer confirms them. |

### Master Reference 01

The control view shows live view, the shutter and the current working context together. The active
photographic value gets the most weight: a large light numeral for the value being adjusted (e.g. the aperture),
legible smaller secondary values, fine visible ticks, a restrained status line and **one bright shutter**. Space
groups controls; borders and icons are there only where they do a job. The active AF area stays usable.

### Foundations (Dark is primary)

| Role | Value | Use |
|---|---|---|
| Canvas | `#141414` | main work area |
| Surface | `#282828` | control surfaces |
| Warm White | `#F1EFE8` | primary text and the primary action, including the bright shutter |
| Muted Silver | `#BDBDB7` | readable secondary values and labels |
| Amber | `#D4AA62` | active selection, adjustment, scale indicator |
| Focus Green | `#7EB89A` | confirmed focus or connection, always with a second cue |
| Signal Red | `#D65C5C` | recording and critical states, always with a second cue |

Contrast on Surface: Warm White 12.81:1, Muted Silver 7.81:1, Amber 6.83:1, Focus Green 6.47:1, Signal Red
3.89:1, so red never carries text alone (light label next to a red indicator); normal text needs at least 4.5:1.
Daylight and Astro Red are field-validation candidates.

**Change against the production tokens:** today `--accent` (amber) marks both the shutter and the selection.
In 1.0 the shutter is Warm White and amber marks selection and adjustment only. Map the roles before any
migration and reuse existing token names where the role still matches.

Type: Inter, tabular numerals for changing camera values (IBM Plex Mono stays optional for technical
measurements). Medium with slight tracking for small labels, light weights only at large sizes, no regular use
of 11 px. The hierarchy is confirmed; the numbers are working tokens until checked on devices.

| Style | Size | Weight | Tracking |
|---|---:|---:|---:|
| Display XL / L / M | 80 / 64 / 48 px | 300 | −0.04 / −0.04 / −0.025 em |
| Value L / M / S / XS | 32 / 28 / 24 / 22 px | 400 | −0.01 em / 0 / 0 / 0 |
| Section | 18 px | 500 | 0 |
| Body | 16 px | 400 | 0 |
| Navigation | 15 px | 500 | 0 |
| Label L / M / S | 14 / 13 / 12 px | 500 | +0.07 / +0.06 / +0.05 em |
| Status | 13 px | 400 | 0 |

Kept: spacing 4/8/12/16/20/32 px, 44 px web hit area, preferred 56 × 56 px mobile target, 64 px shutter
height, motion 120/200 ms with reduced-motion support. Native and Watch sizes are validated separately.

### Precision Scale

Center Lock (indicator fixed in the centre, scale moves beneath) is the preferred default; Fixed Range (scale
fixed, indicator moves) stays the alternative. Both use the same tokens, only real camera stops and the same
state rules. Aperture correction: labels closer to the marks, 12 px Medium labels, 1.25 px Muted Silver minor
ticks, 2 px Amber active tick; other scales keep their current treatment. To test: long ISO, white balance and
shutter-speed lists, ends of the list, one-step changes, tap vs. drag vs. keyboard vs. wheel, and the return to
the confirmed value after a rejected write. Digital Crown and haptics are platform hypotheses.

### Precision Color Control V9

Preferred direction for the colour tools: one instrument; the active colour, its name and the requested value
grouped in the centre; directly draggable handles; detailed measurement on the active axis; Color All inside
the ring, no second slider or duplicate readout.

| Variant | Behaviour |
|---|---|
| Color Profile Control | twelve hue regions with a connected contour; radial drag changes the selected hue's saturation in discrete steps; Color All inside the ring |
| Color Creator | one handle: angle = hue, radius = saturation |
| Monochrome Profile Control | pick a filter, set its strength radially in the same family |

The PEN-F manual (p.39) gives 12 hue regions at −5…+5 (Color Profile) and 30 hue × 8 saturation positions
(Color Creator) for that body. Monochrome steps, Color All semantics and availability per body, firmware, USB
and Wi-Fi are still to verify on the E-M1. Camera Picture Modes stay distinct from software preview looks.

### Snap to Reality

Selectable values come from the current camera mapping; a tap or drag lands on a real stop; intermediate
values only where the camera supports them. The page distinguishes requested/preview, pending,
camera-confirmed and error. After a rejection or an unclear result it re-reads the camera where it can and says
what is known. Capabilities are recomputed when body, lens, connection, mode or prerequisites change. This
matches principles 6 and 7 below (hide what the connection or mode cannot do; disabled with a reason only for
missing write permission); after a context change the page says why an action disappeared and the next step.

### Control View, Fullscreen, Fit and Fill

Control View keeps live view and the shutter available. Fullscreen is a deliberate composition view with an
obvious way back to Control View. Desktop: large preview, separate controls. Phone portrait: thumb reach;
landscape: the picture and clearance for the hot-shoe mount. Watch: reduced companion. Fit shows the whole
frame (padding if needed) and is the default; Fill is a deliberate crop of the preview only. Capture geometry
is independent; focus taps map through the displayed transform, taps in the padding are ignored. After a lost
connection the last picture is marked as stale.

### MCP approval

The Intelligent Camera Operator, Personal Photo Coach and Computational Assistant are offered on demand. Before
a write the page shows current and proposed state, target camera, exact scope and consequences; explicit
approval and active write permission are required, a changed scope or target needs a fresh approval. Outcomes
are read back as done, failed, partial or uncertain. The photographer keeps the creative decision.

### Iconography (direction confirmed, glyphs open)

Fine, legible photographic symbols with clean geometry, optical weight matched to Inter. Normal icons Warm
White or Muted Silver; Amber only for an active state together with a second cue. Photo Coach: a sparkle symbol
with a clear label. Sizes 16 (status), 24 (standard), 28–32 px (primary); stroke 1.5 px at 24 px with optical
correction; optical size separate from the hit area; 8–12 px between targets; labels 12–14 px Medium at
+0.03…+0.05 em.

**Open, not to be built yet:** the individual glyphs (AF, Star AF, Focus Stacking, Live Composite, Live Time,
bracketing, Super Control Panel, the exact Photo Coach glyph). They are designed and confirmed with the
maintainer first; until then the page keeps its current icons.

### Evidence to keep

The decisions from real use stay valid: the comparison overlay removal, the calendar hierarchy, capture and
focus feedback, the hold-angle level, the USB Zoom AF (REQ-F54) vs. Wi-Fi view zoom (REQ-F55) distinction with
pointer-centred zoom, overview map and keyboard arrows (sections below). Keep the stock camera paths and test
the first unassisted shot; compare the existing path with each task shortcut for time, steps, errors and
comprehension.

## Design system V4.0 in code (branch `claude/design-system-v4`, 2026-11-27)

Built from the Figma file "OMCAP Design System" read on 2026-11-27. Isolated: the page `index.html` is **not** migrated; nothing here
talks to the camera. Gallery for design QA: `http://127.0.0.1:<port>/ds/gallery.html` (served by the app).

| File (`omcap/web/ds/`) | Content | Figma source |
|---|---|---|
| `tokens.css` | `--qp-*` semantic colours for Dark, Daylight, Astro Red (one component set, `data-qp-theme`), type scale, spacing, optical spacing, hit areas, scale and capture geometry, value states | Theme System V1.0 (32:482), Foundations (2:19), Typography (8:16), SCP & QCP (31:438) |
| `icons.svg` | 60 symbols: 43 core V4.0 glyphs, 4 V3.2 extensions the SCP uses (stabilizer, tone, aspect, face AF), 13 V3.4 white balance glyphs; geometry unchanged, `currentColor` | Iconography Library (13:2, 18:x, 24:x) |
| `precision.js` | value model (requested, pending, confirmed, failed), Precision Scale (Center Lock, Fixed Range), QCP, SCP, Color Profile, Color Creator, Monochrome | SCP & QCP, Control Panel Components, Precision Color Controls V9 (12:2) |
| `views.js` | view state model (Full, Clean, Panel; Fit, Fill; split; device, display and camera orientation as independent axes) and the resizable shell | Adaptive View Architecture V1.0 (34:967) |
| `components.css`, `gallery.html`, `fixtures/` | component styles (tokens only), gallery, the camera's own Wi-Fi value lists from `camera/desclist.xml` | – |

Contracts kept: snap only to stops handed in by the capability mapping; the camera readback always wins over the
wish; no view change produces a camera action (tested); capture, AF and Review only report `onAction`.

**Deviations from Figma and implementation choices (need a design decision):**

1. Value-state cues are a proposal: requested = muted dashed underline, pending = accent dotted underline (marker
   at 55 % on the scale), failed = red wavy underline with the camera value shown. Figma names the states only.
2. Split limits 40-80 % are a proposal (Figma: 65/35 start, exact constraints open). Phone portrait Panel View
   stacks live view over the panel (45 %), no divider.
3. Swipe momentum (release speed x 120 ms) and the 160 ms snap animation are implementation values.
4. Fixed Range spreads all stops over the width; with long lists (shutter: 61 values including the Live modes) ticks
   get dense. Center Lock stays the default.
5. Colour-ring hue names: Figma shows "BLUE"; the code shows degrees until names are decided. Color Creator
   shows hue 01-30 and saturation; Monochrome on the E-M1 has the B&W filter N/Ye/Or/R/G without strength
   (manual p.80), so the ring is selection-only.
6. Astro Red: colour swatches in the rings turn muted red (red-only rule); the brightness token dims instruments
   only, not the live view. The optional image filter is not built.
7. Only 4 of the V3.2-V3.4 family glyphs are exported (export limit 48 KB per call; families are still studies).
8. Narrow panels (container width up to 460 px) step the exposure values from Value L to Value S and the large
   value from Display XL to Display L so five values fit at 375 px.

**Precision Instrument Library V2.0 and Color Controls V9.1 (change request 2026-11-27, Figma 45:1180, 46:1125):**

- Adaptive Precision Scale: every tick is one value of the camera's list (`stopsFor`), in camera order, nothing added at
  the ends. Main values per parameter, independent of the 1/3, 1/2 or 1 EV step: full aperture stops, full shutter
  stops, ISO doublings from 200, whole EV, every 1000 K. Minor ticks carry no label. AUTO, LOW, BULB, LIVE TIME and
  LIVECOMP are semantic stops (dot, word label) set apart by a 3/4-step gap. Center Lock stays the default.
- Five instrument types in `precision.js`: Scale (`mountScale`), Selector (`mountSelector`), Wheel (`mountColorRing`),
  Axis (`mountAxis`), Relative (`mountRelative`). QCP and SCP read the same `ValueState` objects.
- White balance from the body's own data: 13 presets (manual p.58; Wi-Fi `wbvalue` codes and USB `d01e` 1-13),
  Custom WB from the USB `d00e` list (56 values, 2000-14000 K in 50/100/200/400/1000 K steps; the body has no 8000 K).
  Wi-Fi has no Kelvin property. WB correction A-B / G-M: the range is not in the E-M1 manual text and no USB or Wi-Fi
  property is known, so the axes render "not mapped" instead of a range.
- Relative focus: USB MF drive steps 1-3 near/far (tested 2026-11-13); Wi-Fi shows the control disabled with the reason.
  No absolute focus position. No lens zoom control exists for this body.
- V9.1 themes: swatch lightness per theme (`--qp-seg-l`); the active sector is thicker in every theme; Astro Red paints
  sectors in red, shows indices 01-12 (Color Profile), every fifth hue number plus the active one (Color Creator) and
  filter initials (Monochrome), and an outlined grip. A theme switch writes nothing (tested in the gallery).

**More decisions needed:** QCP WB entry placement (provisional: a WB chip under the four positions); 13 presets do not
fit 375 px at 44 px targets, so the row scrolls natively and is picked by tap (swipe-pick only when the row fits);
Monochrome initials Y/O follow Figma, the E-M1 manual writes Ye/Or; Color Creator numbers hues 01-30 (Figma "HUE 06");
Color All has no visual reference in the frames read and is not built.

**Precision Detent Feedback (Instrument Library V2.1, 2026-11-28):** `detent.js` is the one interaction core for Scale,
Selector, colour instruments and the crown. Every valid value is one detent; drag, wheel/trackpad, keyboard, touch and
crown move detent by detent (no gliding values, no coasting, no overshoot); value, scale position and marker change
together. One pulse per detent passed, none at the limits; a camera readback never pulses. Rings wrap round and take
the short way. Colour instruments have two detent axes: angle (sector, hue, filter) and radius (level, saturation;
Monochrome strength only where the body has it, the E-M1 has none). Touch near the ring picks the angle axis, inside the
radial axis; arrows left/right = angle, up/down = radial.

- Feedback (`createFeedback`): sound, haptic and motion switch independently (saved per viewer); defaults by platform
  (fine pointer: click sound; touch with `navigator.vibrate`: haptic); Reduced Motion sets the detent motion to 0;
  silent shooting mutes sound only. The click is synthesised with WebAudio (no file); without support the visual
  detent stays. iOS Safari has no web vibration API, so web haptics work on Android only; native apps use their APIs.
- Command gate (`createCommandGate`): one camera command in flight per value; newer detents replace the waiting
  wish; turning back to the value on its way sends nothing. State shows the newest local selection (requested) even
  while an older value is in flight; pending, confirmed and failed stay distinct.
- Digital Crown (`crownTarget` in `views.js`): live view = zoom; instrument = active parameter; Color Profile = level of
  the selected colour; Color Creator = active axis; Monochrome = strength where available, else filter; timer = next
  valid step; review = image or zoom. watchOS: SwiftUI `digitalCrownRotation(_:from:through:by:sensitivity:isContinuous:
  isHapticFeedbackEnabled:)` bound to the index of the capability list (`from: 0, through: count - 1, by: 1`,
  `isContinuous` only for rings) gives native detent haptics; the app then reports the source `crown-native` and adds
  no haptic of its own (tested in the engine). Per developer forum, the `by` stride needs a watch with haptic crown
  (Series 4 and later); to be checked in Xcode when the watch app starts.
- Tunable (Motion & Feedback design decides): `--qp-detent-ms` (70 ms proposal), `DETENT_DEFAULTS` (wheel 40 px,
  drag = tick spacing, crown 1 unit per detent, at most 12 detents per event), click volume 0.18 and timbre, haptic 8 ms.

**Typography Refinement V1.1 (variant C, Optical Spacing; Figma Typography Audit 52:1312, 2026-11-28):** Inter kept;
Display Light 300 (80/64/48 px), Values Regular 400 (32/28/24/22 px), Labels Medium 500; Color Controls value 70 px Light.
Tracking tokens: display digits −1 %, compact values 0 %, aperture sign +5 % (its own span), Label L/M/S +7/+6/+5 %,
numeric scale labels neutral. One formatter (`formatValue`) for QCP, SCP, scales and selectors: ƒ prefix, `1/8000` and
`60"`, real minus and one EV sign rule (+0.3, ±0.0, −0.3), Kelvin unit at 0.6 em, camera words (AUTO, LOW, BULB,
LIVE TIME, LIVECOMP) as words at 0.6 em (0.5 em in compact slots) in the weight of their slot. Values never wrap.

- Fixed on the way: tabular figures were not active anywhere (a later `font:` shorthand reset `.qp-num`); now a
  doubled-class rule keeps them (checked: equal widths for 1/1000 and 1/8000, 1.2 and 8.0, 1250 and 8000).
- Deviation: compact values scale with the panel width (`clamp(15px, 4.9cqi, 32px)` SCP, `clamp(15px, 5.6cqi, 24px)`
  QCP), because 1/8000 in Value L 32 px is wider than an SCP column even at the Figma width of 600 px. Panels under
  300 px use 3 (SCP) / 2×2 (QCP) columns, under 220 px 2 SCP columns; the large value steps to Display M under 260 px.
  Never below 15 px.
- Deviation: EV zero is written ±0.0 everywhere (the Figma QCP showed 0.0, the SCP ±0.0).
- Inter 4.1 variable is bundled (`omcap/web/ds/fonts/InterVariable.woff2`, 352 KB, from the official rsms/inter v4.1
  release, SIL OFL 1.1 in `fonts/Inter-OFL.txt`) and loaded by `tokens.css` via `@font-face`; the server serves
  `.woff2` and `.txt` under `/ds/` only. The page `index.html` still names Inter without the file until it migrates.
- QA (browser, no camera; Dark, Daylight, Astro Red): no layout shift in QCP and SCP over 4 value sets (250/8000/60"/
  LIVECOMP, 400/25600/AUTO/LOW, ±0.0/−4.7/+5.0/−0.3, ƒ2.8-ƒ22) at 600, 343 and 168 px panels; nothing clipped; smallest
  digits 15 px; stress table of 13 audit cases in 7 sizes without wrapping. Not on real devices yet.

**Wiring requirements for the page migration (merge-gate QA 2026-11-28):** the components hold no mode map; the page
supplies it from the existing `FEATURES` / `inMode(...)` sets (one source, no copy): shutter only in S and M (movie S/M),
aperture only in A and M, EV not in iAUTO, M or SCN (p.51), ISO as `FEATURES`; BULB, LIVE TIME and LIVECOMP only in M
(p.41), so the shutter list is re-stopped (`setStops`) without them outside M. A mode change sets unavailable values to
`null` (QCP) / `available: false` (SCP) and re-renders. Over USB iAUTO, ART, SCN and PHOTO STORY read as P. Tiles that
only one connection can set (AF mode, metering, stabilizer: USB only) are hidden on the other connection; the relative
focus control is hidden on Wi-Fi on the real page (the gallery shows it disabled for review only).

**Capability notes (E-M1 Mark I, fw 4.6):** Color Creator is a picture mode of the body, but hue/saturation have
no USB or Wi-Fi property (firmware study 2026-11-24); Color Profile and the Monochrome filter strength are PEN-F
functions and would be computed by the app (software HSL), never written to the camera.

## Incumbent design (0.4.0 – 0.8.x, still implemented)

Everything below describes the page as built today and stays binding until a migration step replaces it.

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
| Live View Boost (Off / On1 / On2) | Live View Boost (Custom menu D) | p.95, p.176, p.179 |
| Star AF (app function, not a camera mode): Auto Star AF, Lock focus, Speed/Accuracy, HFR (star size) | app function, no manual page; MF Assist > Magnify (frame set by the AF target) | p.102 |
| Anti-Shock, Silent, Noise Reduct., BULB/TIME Timer, Digital Tele-converter | same | menus |
| Time lapse, AE BKT, LIVE TIME, LIVECOMP | Time Lapse Settings, AE BKT, LIVE TIME, LIVECOMP | p.41, p.85, menus |
| Press halfway / Take picture | "press the shutter button halfway" / "press fully" | p.20 |
| Index display, Calendar display, single-frame playback, close-up playback | same | p.31–33, p.63 |
| Image only / Simplified display / Overall display | INFO button cycle during playback | p.62 |
| View zoom 1×–4× (smooth; buttons 1×/2×/4×) | not a camera function (the camera's own is Magnify / Zoom frame AF, ×3–×14); label it as the app's view zoom | – |
| White balance presets: Auto, Sunny, Shade, Cloudy, Tungsten, Fluorescent, Underwater, Flash, One-touch WB 1–4, Custom WB (CWB 2000–14000 K) | same; CWB = custom white balance in Kelvin | p.58 |
| Color Creator (hue, saturation) | Color Creator, front dial hue, rear dial saturation | p.60 |
| Monotone · B&W Filter N / Ye / Or / R / G | Monotone, B&W Filter N, Ye, Or, R, G (the design system ring shows N, Y, O, R, G per Figma V9.1: open design decision) | p.70, p.80 |
| Image stabilizer (S-IS AUTO, S-IS 1–3, S-IS Off) | Image stabilizer / IS Mode | p.68 |
| Face priority | Face priority | p.55 |
| Color Profile, Monochrome strength | app terms (no E-M1 equivalent; PEN-F functions), computed in software only | – |

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
