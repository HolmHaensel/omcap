# E-M1 Mark II — USB test report and handoff

First working session with an **Olympus OM-D E-M1 Mark II** (firmware 1.00) on the 0.8.0 codebase, over
USB on Windows 11. The body was not in the supported set, and four real incompatibilities stood between
"enumerates on the bus" and "live view + settings + AF in the browser". All four are fixed on this branch.

Everything below was measured on the camera. Nothing here is inferred from the Mark I's behaviour.

## Result

| Capability | Result over USB |
|---|---|
| Connect (own PTP layer) | works: open 0.1 s, session 1.7 s, card index 8.4 s |
| `GetDeviceInfo` | `E-M1MarkII`, firmware `1.00`, **38 operations, 282 properties, 13 events** |
| Live view | works at 320×240, 640×480, 800×600, 1024×768, 1280×960 |
| Live view rate | **~15 fps** (66 ms/frame) at every size — the body's own rate |
| Frame size | 49 KB (800×600), 80 KB (1024×768), 126 KB (1280×960) |
| Change poll (`0x9489` → `0x9486`) | works, **5 ms** per poll, returns all 7 requested properties |
| Settings read | A mode, 1/60, f/2.8, ISO AUTO, WB 5300K, 121 AF fields, level |
| Shutter (half press) | `ok`, camera focuses |
| Shutter (full press) | `ok`; shot sequence 4.0 s (release 0.1 s, fast JPEG 0.7 s, card files 2.4 s) |
| Card | 563 objects, 126 GB, `DCIM/100OLYMP` |

Not verified yet: reported AF point, zoom AF, focus stacking, movie, direct store, playback transfer.

## The four incompatibilities (each one blocked everything downstream)

1. **`killall ptpcamerad` on Windows.** `UsbCamera._open` calls it unguarded. On Windows that raises
   `FileNotFoundError [WinError 2]` and aborts *every* USB connect before a session is opened. Now
   guarded with `sys.platform == "darwin"`.
2. **Live view JPEG is followed by an `AddIndex` block.** The Mark II answers `0x9484` with the JPEG plus
   a trailing index/status block: 800×600 totals 49408 bytes, of which the JPEG ends at byte 49277
   (`FFD9`). The old completeness test (`data[-2:] == b"\xff\xd9"`) therefore rejected every frame —
   *"incomplete JPEG (80128 bytes)"* — and the ten-failure loop rebuilt the session every time.
   New `ptp.trim_jpeg()` cuts at the **last** `FFD9` (a thumbnail inside EXIF ends earlier) and is used
   by both the own-PTP path and `preview_frame`.
3. **Start screen said "not found".** `usb_camera.detect_name()` asked libgphoto2, which does not exist on
   Windows, so a body the app drives perfectly looked absent. It now falls back to the own libusb layer,
   naming the body from a short `GetDeviceInfo` session, cached 5 s (the page polls about once a second).
4. **PTP array property types.** `read_value()` raised `KeyError` on `0xD405` (UINT8 array) — the Mark I
   never advertises one. All eight PTP array types are decoded now.

## Getting the body into the right USB mode (this is the trap)

The Mark II's USB prompt reads:

```
Storage / MTP / PC RAW / [camera + monitor icon] / Print / PCM Recorder / Exit
```

- **`[camera + monitor]`, the row below `PC RAW`, is OM Capture's mode.** That is the one that works: the
  body enumerates as `07B4:0130` with the full vendor opcode set (`0x9481`, `0x9484`, `0x9486`, `0x9489`).
- **`MTP` looks like a PTP camera but is a bare MTP responder**: class 6/sub 1/proto 1, PID `0x012F`, only
  20 operations and 5 properties, and every Olympus property answers `0x200A`
  DevicePropNotSupported. File transfer works, control does not.
- `Storage` is plain mass storage, no PTP interface.
- `PC RAW` is OM Workspace's RAW link, not capture control.

Quick discriminator after opening a session: **20 operations = wrong USB mode, 38 = PC control.**

On Windows the PTP interface needs **WinUSB bound with Zadig**, and the binding is **per product id**:
changing USB mode creates a new device instance that Windows re-arms with `WUDFWpdMtp`, after which
libusb says `open: ok / claim interface 0: LIBUSB_ERROR_ACCESS`. Re-run Zadig for the new id.

## Property notes for the next body

Read from the descriptors, not from the Mark I's tables:

- `0xD06D` live view size: `0`, `(320<<16|240)`, `(640<<16|480)`, `(800<<16|600)`, `(1024<<16|768)`,
  `(1280<<16|960)` — same packing as the Mark I, plus an explicit `0` (off).
- `0xD051` AF field: 121 values (Mark I: 81 → 9×9). The AF geometry tables are Mark I shaped and will
  need a per-body grid.
- `0xD006` mode dial: 5 values here; `0xD01C` exposure `65596` = `1/60` (`(1<<16)|60`).
- `0xD01D` (5 values) is **not** aperture on this body — libgphoto2 maps aperture to `0xD002`, ISO to
  `0xD007`, WB to `0xD01E`. The Mark I tables address `d01d` as stabiliser, and that matches what this
  body reports. Aperture/ISO/WB need the libgphoto2-style codes for a per-body mapping.
- Appended live view block starts right after `FFD9` and ends with ASCII `AddIndex`; it also carries the
  camera's own status words (candidate source for the Wi-Fi `lvext` fields over USB).

## What is still open

- **AF point readback is wrong**: half-press returns `last_af = {x: 0, y: 358}`. The `0xC003` focus event
  does not use the Mark I's coordinate space, so the green AF frame will be drawn in the wrong place.
  Needs the event payload decoded from this body.
- 15 fps vs the Mark I's 30: suspected limit of the body's USB live view, not the parser. Worth checking
  whether a property raises it before anyone optimises the read loop.
- Zoom AF (`0x9483`/`0x9488`), focus stacking, movie, direct store (`0x9493`/`0x9495`) untested.
- Super-control-panel **writes** untested (reads all work). Mode dial stays read-only over USB.

## Files

| File | What |
|---|---|
| `device-e-m1-mark-ii-usb.json` | machine-readable dump: model, opcodes, all 282 properties with descriptors/values, plus the suite results |
| `AGENTS.md` | handoff brief for an agent on the Wi-Fi machine (what to run, what to compare, guardrails) |
| `../ptp_probe.py` | read-only session probe: model, opcodes, properties, storages (writes a JSON dump) |
| `../mk2_suite.py` | capability sweep: `lv` (fps per size), `props`, `poll`, `focus` |
| `../mk2_live.py` | minimal live view test: PC control → size → frames → restore |
| `../mk2_frame_timing.py` | per-frame bytes and inter-frame gaps (the fps truth) |
| `../usb_diag.py` | why libusb cannot open the body: per-device `open`/`claim` with libusb error names |
| `../usb_enum.py` | read-only descriptor dump (class/endpoints), works with any driver bound |

Windows setup used here: Python 3.14 venv, `pip install libusb-package`, Zadig 2.9 → WinUSB on
`E-M1MarkII (Interface 0)`, app started with
`python -m omcap.server --allow-write --usb-backend ptp --no-browser`.
