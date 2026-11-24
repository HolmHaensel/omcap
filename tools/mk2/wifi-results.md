# E-M1 Mark II — Wi-Fi test report

First Wi-Fi session with an **Olympus OM-D E-M1 Mark II** (firmware **3.7**, read from the body's own
menu: Menu → Setup → Firmware) on the 0.8.0 codebase plus the Mark II USB branch. The body was driven by
E-M1 Capture on Windows 11 over the camera's own access point. Nothing here is inferred from the Mark I:
every number was measured on the camera on 2026-11-24.

`GetDeviceInfo` over USB reports `DeviceVersion 1.00`; that is the PTP/software version, not firmware.
Serial numbers are deliberately left out of this file.

## Link

| | |
|---|---|
| Camera | AP-only, Private mode (`get_connectmode` → `private`) |
| Camera IP | `192.168.0.10`, ping 5 ms, port 80 open |
| This PC | Wi-Fi client `192.168.0.3`; Ethernet stayed up for internet (different subnet, no route conflict) |
| First connect | Windows refused with "Unable to connect to this network" until the profile was written with `netsh` (WPA2PSK/AES, explicit key); after that the association was instant |

## What the body says about itself

`get_caminfo`: model `E-M1MarkII`, `extmediaslot 1/2`, `DoubleslotSupport available`,
`GetRawImageSupport available`, `RecommendedIsoLowerLimit 200`, `MISOAExpComp available`.
No firmware element exists in `get_caminfo` — the firmware number can only come from the camera menu.

## Command list (`tools/mk2/commandlist-e-m1-mark-ii.xml`)

**38 CGIs** vs the Mark I's 23 — a strict superset, nothing the app calls is missing.
New on this body: `cancel_trimresize`, `exec_erase`, `exec_movietrimresize`, `exit_moviestream`,
`get_exif`, `get_movfileinfo`, `get_moviestream1frame`, `get_moviestreaminfo`, `get_playtargetslot`,
`get_trimresizeprocstatus`, `ready_moviestream`, `set_playtargetslot`, `start_moviestream`,
`start_moviestreamts`, `stop_moviestream`.

There is **no** `startliveview` / `getliveviewimage` CGI: live view uses `exec_takemisc?com=startliveview`
plus `switch_cammode`, exactly the Mark I route. So the app's UDP live view is the right path for this body.

## Property table (`tools/mk2/props-e-m1-mark-ii.xml`)

**54 properties, 23 writable.** Values seen: `takemode P`, `shutspeedvalue 250` (1/250),
`focalvalue 5.6`, `isospeedvalue Auto`, `wbvalue 512`, `drivemode silent-continuous-H`,
`touchactiveframe 0160-0120_0480x0360` (800×600 base), `expcomp`.

Named by the app but **not advertised** by this body over Wi-Fi:

`aspect`, `batterylevel`, `colortol`, `facepriority`, `flashmode`, `focusmode`, `liveviewsize`, `lvqty`,
`metering`, `recordmode`, `stabilizer`

Two of those have a lookalike here: this body advertises **`colortone`** (not `colortol`) and
`colorphase`; `artfilter` and `drivemode` are present under the app's names. The LV super control panel
will therefore show fewer controls than on the Mark I, and the live view size picker cannot read a
`lvqty` property (the sizes themselves do work through `switch_cammode`).

### `get_camprop` only answers in REC mode

After connecting while the camera was in Playback, every `get_camprop` call returned
`<errorcode>1001</errorcode>` (the app surfaced it as HTTP 520 `Vendor Internal Error`) — including
`com=get&propname=takemode` and `com=desc&propname=desclist`. Pressing the shutter button halfway on the
body did **not** change that. Only `switch_cammode?mode=rec` (what "Start live view" does) made the whole
table readable. The Mark I answers in play mode, so this is a Mark II difference: with a read-only start
the settings panel stays empty until live view has been started once.

## Live view

UDP/RTP on port 5555, decoded by the existing Mark I code. Windows Firewall needed an inbound UDP 5555
allow rule for the venv's `python.exe`; without it the stream is silent while everything else works.

| Size | fps (settled) | Frame | Dropped | Bandwidth |
|---|---|---|---|---|
| 320×240 | 30.1–30.3 | 7.4 KB | 0 % | 0.22 MB/s |
| 640×480 | 27.5–28.7 | 30 KB | 5–6 % | 0.82 MB/s |
| 800×600 | 16.6–24.6 (unstable) | 48.6 KB | 1–12 % | ~1.0 MB/s |
| 1024×768 | 12.9–13.0 | 83 KB | 0 % | 1.08 MB/s |
| 1280×960 | 5.8–8.1 | 130 KB | 2 % | ~1.0 MB/s |

The body appears to cap its Wi-Fi stream at about **1 MB/s (~8 Mbit/s)**, so the rate above 640×480 is
frame size, not processing: 800×600 sits exactly at the edge and oscillates (that is why it looks worse
than on the Mark I, which reached ~21 fps there). 640×480 at ~28 fps is the stable choice; 1024×768 for
checking details.

### Extension block (`/api/lvext`)

19 IDs arrive: `1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 16, 17, 18, 19, 20, 26`. The Mark I layouts decode
correctly on this body — JPEG size (1), AF result (2), card state (3, mount state 2), free shots (5),
shutter speed (8: `1/60`), f-number (9: `22 / 2.8 / 2.8`), exposure comp (10: `-5 … +5`, now `+0.3`),
ISO (12: `4000`), focal length (18: `12–40 mm`, now 12), and a 800×600 size report (26).
Four IDs are not decoded by the app yet: `6, 11, 14, 20` (raw words logged below), and ID 26 duplicates
the live view size.
**No ID 107** — the level gauge data is not in this body's Wi-Fi stream (the app only offers the level
gauge over USB anyway).

Raw samples at 800×600:

```
6:[0] 11:[512,0] 14:[262147] 20:[0] 26:[800,600,0,0,0,0]
```

## Control

- **Tap to focus works.** `exec_takemotion?com=assignafframe&point=xxxx` returned
  `affocus=ok` in about **430 ms** with `afframepoint` + `afframesize` (`90x90`) in the 800×600 grid,
  i.e. the app's Mark I frame arithmetic lands correctly on this body. 4 of 5 tested points returned ok;
  the exact centre returned `ng` (low contrast there), which the UI shows as "not focused".
- **Half press** via the app: ok in **943 ms** (`switch_cammode?mode=shutter` → `exec_shutter?com=1stpush`,
  then back to rec). `exec_shutter` called directly in rec mode answers `1001`, which is expected: this
  body only accepts it in "shutter" mode.
- The body was left in **silent-continuous-H** drive mode. A single shot from the app will fire a burst;
  set the drive mode on the camera to single before judging "one picture" timings.

## Not tested yet

Take picture, playback and save-to-computer, LV super control panel **writes**, movie, second monitor and
webcam. Over USB the same body already shoots (4.0 s per shot) and lists the card.

## Open points

1. `get_camprop` failing outside REC mode (see above) — the one behavioural difference that shows up
   before live view starts.
2. 800×600 is unstable on this body; consider 640×480 as the Wi-Fi default for the Mark II.
3. Eleven property names missing; `colortone` vs `colortol` is a likely rename worth mapping per body.
4. AF point readback over USB (`x = 0`) is **not** reproduced over Wi-Fi: the `assignafframe` reply has
   valid coordinates here.
