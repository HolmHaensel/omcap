# E-M1 Capture – all features

Every feature over Wi-Fi and USB, with test status and details. Short overview: [README](README.md#what-it-can-do).

✅ works (tested on the camera) · 🟡 built, not tested on the camera yet · – not possible or not built (reason in the note)

### Live view

| Feature | Wi-Fi | USB | Note |
|---|---|---|---|
| Live view with zoom, Displayed Grid and overlay | ✅ | ✅ | |
| Zoom (USB): 1× and ×3–×14 are the camera's own Zoom AF and replace the screen zoom; click = focus, drag = move, wheel/pinch = smooth zoom that snaps to the camera's ratios at rest and turns sharp (Wi-Fi has its own screen zoom, next row) | – | 🟡 | no Wi-Fi command (`exec_takemisc ctrlzoom` is the lens power zoom); AF in the zoomed view uses the screen centre, and the camera has no AF with Four Thirds lenses while zoomed (manual p.56, untested); USB both layers; camera-checked by hand 2026-11-16 (on/off, ratios, arrows); smooth zoom (drag, wheel, overview map, pinch on the phone) tried with the camera 2026-11-18; click focus (half press 1, release 5) not camera-tested (REQ-F54) |
| Zoom (Wi-Fi): smooth screen zoom 1×–4× in the app (wheel, trackpad, pinch about the pointer; drag pans; 1×/2×/4× buttons; overview map; click = AF target, also zoomed) | ✅ | – | picture zoom only, no camera command (the live view is at most 1280×960); on the phone, and on the computer (also with a size picked by hand: that size is the 1× size, "Auto" next to Size only adds the adaptive size at 1×), the live view size goes up while zoomed (1024×768 up to 2.5×, 1280×960 above) and back at 1× (if too slow: sharp only while focusing); tried over Wi-Fi with the camera 2026-11-18 (wheel, drag, overview map, phone pinch); read-only USB not tested; a focus action while zoomed above 1.5× brings 1280×960 for 5 s, the Size select shows the size in use with Auto; tried over Wi-Fi 2026-11-22 (2×/4×, explicit size, tap AF, Halfway): a tap AF is refused ("Release Press halfway first") while Halfway is held, and Halfway does not change the size; on the computer the Size select is hidden while Auto is ticked (untick Auto to pick a size) |
| Live view size (up to 1280×960) | ✅ | ✅ | USB: with the app's own USB layer (macOS default); with libgphoto2 see [Larger USB live view](README.md#larger-usb-live-view-libgphoto2) |
| Histogram, Highlight&Shadow, Peaking | ✅ | ✅ | Peaking follows the focus best at a live view size of 640×480 or more |
| Frames per second shown next to the live view size (and "libgphoto2" when USB uses the slower fallback) | ✅ | 🟡 | same page code; not yet looked at over USB |
| Level gauge (horizon line and tilt dot, "Level ✓", optional sound, "Hold angle") | – | ✅ | the camera sends no tilt over Wi-Fi; USB: own USB layer only, not with libgphoto2 |
| Free card space in the header | ✅ | ✅ | |
| Battery level in the header | – | 🟡 | USB: only a rough level of the body battery (the camera reports coarse steps, 100 or 50; with an HLD-7 grip in use the grip's charge is not reported); Wi-Fi: the value the camera sends is not the battery level, so it is not shown |
| Current focal length; ISO with ISO Auto ("now 800"); shutter speed and aperture the camera uses in auto modes | ✅ | – | sent with the Wi-Fi live view; no live USB value found |

### Focus

| Feature | Wi-Fi | USB | Note |
|---|---|---|---|
| Tap the 9×9 AF grid to focus, AF target in green | ✅ | ✅ | grid in the camera's real size (read 2026-11-22); Wi-Fi: outer fields focus where tapped (the camera takes points outside its touch area) |
| AF frame on tap (white focusing, green in focus, red no focus) | ✅ | ✅ | |
| Focus tone in the app after a tap focus (high = in focus, low = no focus; switch "Focus tone", off by default) | ✅ | – | over USB the camera beeps itself on the half press (menu "Beep"), so no app tone; over Wi-Fi a tap sets the AF frame without a camera beep, a half press would need mode "shutter" and pause the live view; tried over Wi-Fi 2026-11-22 (user: works) (REQ-F59) |
| "In focus" / "No focus" chip | ✅ | ✅ | Wi-Fi after a tap; USB also after Press halfway and Take picture. With S-AF the camera only releases in focus |
| AF Area (All Targets, Single Target, Small Target, Group Target) | – | ✅ | no Wi-Fi command |
| Focus ring (MF): Near/Far in three step sizes | – | ✅ | AF mode MF or S-AF+MF; no Wi-Fi command |
| Star AF (manual): live star-size (HFR) focus aid, clipping/bright warning and hyperfocal readout (photo modes) | 🟡 | ✅ | browser-side live view measurement on computer and phone; while Star AF is on, tapping the live view picks the star instead of an AF target; 9×9 grid and AF Area hidden while Star AF is on and in MF (also over Wi-Fi); USB camera-tested 2026-11-23, Wi-Fi not tried (REQ-F24) |
| Star AF (automatic) & Focus Lock: auto-switches to MF, tap a star or click Auto Star AF (Speed/Accuracy, ×10 zoom, temporary Live View Boost), auto-locks focus when sharp | – | ✅ | needs photo mode and `--allow-write` (no Wi-Fi focus drive command); triggerable from a phone over `--lan`; click `Focus locked` to unlock; USB-tested 2026-11-23; Four Thirds lenses at ×10 untested (REQ-F24) |
| Focus Stacking On/Off (8 frames, merged in the camera, P/A/S/M) | – | ✅ | no Wi-Fi command; USB sets Bracketing, Focus BKT and stacking together; needs a card, hidden without one |

### Shooting

| Feature | Wi-Fi | USB | Note |
|---|---|---|---|
| Take picture, Press halfway (hold focus, then take picture) | ✅ | ✅ | focuses on the tapped AF point; Wi-Fi: long exposures and Movie use the shutter button route; USB: the Press halfway button not re-tested since its redesign |
| Shutter blackout: short black frame over the live view on Take picture | ✅ | ✅ | |
| Self-timer (Off, 2 s, 12 s, cancel while it runs) | ✅ | ✅ | |
| New picture in the corner and in the Index display right after the shot | ✅ | ✅ | Wi-Fi about 8 s (7 s of it is the camera's shot), USB 5–6 s after the click |
| The corner picture fades out after 6 s | 🟡 | 🟡 | |
| M mode quick select: BULB, LIVE TIME, LIVECOMP | ✅ | ✅ | |
| Movie: Start/Stop recording, movie shooting mode P/A/S/M | ✅ | ✅ | Wi-Fi: the app switches to Movie mode and back (MCP does not: Movie mode must be set first) (movie record mode cannot be changed over Wi-Fi); USB works like the REC button (not in PHOTO STORY and some SCN modes); movie settings over USB not built; needs a card: REC hidden over USB without one |
| Time lapse, AE BKT | 🟡 | ✅ | |
| Switch "Copy to computer" (the camera always writes to the card); save folder and file names | ✅ | ✅ | USB-tested 2026-11-22 (card: copy; no card: direct store; card change). A click into the Folder field opens the system folder dialog (on the computer only; a phone over `--lan` types the path; Windows/Linux untried, REQ-F62). USB without a card: no switch, note "No card: photos go to the computer". Wi-Fi: always the switch (the camera always needs a card). Files stored without a card are named `E-M1_<time>`: the prefix scheme applies, "datetime" adds nothing, the original name does not exist |

### Camera settings

| Feature | Wi-Fi | USB | Note |
|---|---|---|---|
| LV super control panel: shutter speed, aperture, exposure compensation, ISO, WB, drive, Picture Mode | ✅ | ✅ | |
| Art filter | ✅ | 🟡 | USB: not tested in ART mode |
| Partial Color colour ring (ART and Picture Mode Partial Color; 18 colours, laid out like the camera's ring) | ✅ | – | USB: the camera offers no value for the colour, only selecting Partial Color |
| Shooting mode | ✅ | – | USB: set by the mode dial; the app follows the dial and reloads the values (tested; iAUTO, ART, SCN, PHOTO STORY show as P; turn shown in 0.1–0.7 s without reconnect, USB-tested 2026-11-23) |
| AF mode, Metering, Flash mode, Record mode, Aspect ratio, Image stabilizer, Face priority | – | ✅ | no Wi-Fi command |
| Live View Boost (Off / On1 / On2, Others row: P/A/S) | – | ✅ | no Wi-Fi command; M / Bulb / Live Composite rows pending camera mapping; P/A/S and restore USB-tested 2026-11-23 (REQ-F24) |
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
| Fast last-shot picture right after the release (REQ-F60) | ✅ | ✅ | Wi-Fi: `getrecview`/`getlastjpg`. USB: PTP 0x9485 OMD_GetImage, shown before the card lists the file; camera-tested once without a card: JPEG 0.9 s after the release; with card, RAW-only, held button pending; own USB layer only (libgphoto2 keeps the card path); independent of the Rec View setting (E-M1 manual p.91); not for self-timer, Focus Stacking, Bulb/Time/Live Composite, movie |
| Shoot without a card: pictures go straight to the computer (REQ-F61) | ✅ | ✅ | Wi-Fi saves to the computer already. USB: PTP 0x9495 info and 0x9493 pieces after event 0xC004, ORF then JPG saved as `E-M1_YYYYMMDD-HHMMSS`; own USB layer only (libgphoto2 keeps the card path); with a card nothing changes; works for single shots, Bulb/Time/Live Composite and held button (no more failure after 21 s); Focus Stacking is refused without a card; camera-tested without a card (JPG only, RAW+JPEG) and with a card (unchanged); untested: RAW only, self-timer, Bulb/Time/Live Composite stop, interval, held button, sequential L/H, locked card (counts as a card, direct store skipped), movie (needs a card) |
| Movie length in the single-frame view | ✅ | – | not built for USB |

### Phone, second monitor and webcam

| Feature | Wi-Fi | USB | Note |
|---|---|---|---|
| Open the app on a phone in the home network (QR code behind **Phone**) | ✅ | 🟡 | start with `--lan`, see [On a phone](README.md#on-a-phone) |
| Phone view: live view size picked by itself, no computer-only windows | ✅ | 🟡 | Wi-Fi follows the screen and the signal; USB always 1024×768 at 30 fps |
| Second monitor (live view or last picture in its own window) | ✅ | ✅ | live view window tested 2026-11-15 |
| Webcam (OBS) | ✅ | ✅ | webcam view tested; the **Webcam (OBS)** button itself not tested; see [Use as webcam](README.md#use-as-webcam-obs) |
| AI Photo Coach (MCP for Claude Desktop / Claude Code): read-only tools, prompts & `camera_configure` dry-run | ✅ | ✅ | Demo 2026-11-23 over USB and Wi-Fi: all 5 read tools and a dry-run plan (nothing written); wish-to-settings USB-tested 2026-11-23; see [MCP server](README.md#ai-photo-coach-mcp) (REQ-F35) |
| Full MCP camera & app control in safety tiers: `camera_focus`, `live_view`, `playback`, `app_control` (`--allow-write`), `camera_shoot` (`--allow-shutter`), `card_erase` (`--allow-erase`) | 🟡 | 🟡 | Follows the app's USB/Wi-Fi and shooting-mode gating; dry-run by default for capture, erase and camera-state actions (focus, live view start, Playback, connect, refresh, disconnect, Turn off camera); over Wi-Fi a movie only in Movie mode (MCP never switches the mode); USB & Wi-Fi live-tested 2026-11-23 (`connect`, `live_view`, `camera_focus`, USB `loupe`, `camera_configure` apply/restore, `camera_shoot` single shot, `playback`, `disconnect`, Wi-Fi `poweroff` dry-run); `interval`, `bracket`, `movie`, `long_exposure` and `card_erase` offline-tested only (REQ-F35) |

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
and film looks. Ideas and wishes are welcome in [Discussions](https://github.com/HolmHaensel/omcap/discussions).

The interface is in English; all texts are in one translation table (`I18N` in `omcap/web/index.html`),
so more languages can be added.
