# Agent brief — E-M1 Mark II, Wi-Fi side

You are picking up work on **E-M1 Capture** (repo `HolmHaensel/omcap`) for an **Olympus OM-D E-M1 Mark II**
(firmware 1.00). Someone already took it as far as it goes over USB on Windows; this machine has Wi-Fi, so
your job is the **Wi-Fi half**, which is still completely untested on this body.

Read `README.md` in this folder first — it lists the measurements and the four USB bugs already fixed.
Do not re-derive them; reproduce only if you need to confirm a regression.

## Rules (from CONTRIBUTING.md, not negotiable)

1. Never write or flash firmware.
2. Read-only first. Anything that changes a setting, writes to the card or fires the shutter requires the
   app started with `--allow-write`. Do not enable it for exploratory runs.
3. No serial numbers, no photos of people, no home paths or e-mail addresses in anything you commit.
4. Camera tests are manual and described in the PR; the unit tests must pass without a camera.

## Setup

```sh
git clone https://github.com/HolmHaensel/omcap.git
cd omcap
python3 -m venv .venv
.venv/bin/pip install -e ".[usb,film]"     # on Linux this pulls python-gphoto2 as well
.venv/bin/python -B -m unittest discover -s tests    # must be green, no camera needed
```

Check out the branch that carries the Mark II fixes before you start
(`mk2-windows-usb` on the fork that opened the PR) — it contains `ptp.trim_jpeg()`, which the USB path
needs and which the Wi-Fi path must not regress.

## What already works on this body (USB, measured)

38 operations / 282 properties; live view 320×240…1280×960 at ~15 fps; change poll `0x9489`/`0x9486` in
5 ms; settings read; shutter half and full press; card listing. Open issues: AF point readback returns
`x = 0`, zoom AF / focus stacking / movie / direct store untested.

The body must be in **PC-control** USB mode (the camera+monitor row below `PC RAW`), not MTP — see
`README.md`. Over Wi-Fi this does not matter, but do not be surprised that the USB work needed it.

## Wi-Fi test plan (in this order)

The camera is an **access point only**. It never joins a home network, so this machine must connect to the
camera's SSID (name and password are in the camera's Wi-Fi menu, or in OI.Share's pairing screen). The
camera network has no internet; turn Auto-Join off for other networks so the machine does not wander back.

### 1. Prove the link

```sh
ping -c 3 192.168.0.10
curl -s -H 'User-Agent: OlympusCameraKit' http://192.168.0.10/get_caminfo.cgi
```

Save the model string — it is the evidence that this is the Mark II and not a cached answer from the
Mark I. If the ping fails, stop: that is "camera not in AP mode", not a tool failure.

### 2. Capture the body's own capability list (read-only, do this first)

```sh
curl -s -H 'User-Agent: OlympusCameraKit' http://192.168.0.10/get_commandlist.cgi > tools/mk2/commandlist-e-m1-mark-ii.xml
```

Diff it against the Mark I list the project ships/uses. The interesting part is what this body **does not**
have: any CGI the app calls blindly (`exec_takemotion`, `exec_shutter`, `get_camprop`, `switch_cameramode`,
`get_imglist`, `get_unusedcapacity`) that is missing here will 520 or fail, and the app's Wi-Fi settings UI
will lie about what it can do. Write the diff into your results file.

```sh
curl -s -H 'User-Agent: OlympusCameraKit' 'http://192.168.0.10/get_camprop.cgi?com=desc&propname=desclist' > tools/mk2/props-e-m1-mark-ii.xml
```

That XML is the authoritative property table for this body over Wi-Fi: it names the properties, their
enums and write attributes. Compare the names the app expects (`takemode`, `shutspeedvalue`, `focalvalue`,
`isospeedvalue`, `wbvalue`, `drivemode`, `colortol`, `artfilter`, `focusmode`, `metering`, `flashmode`,
`recordmode`, `aspect`, `stabilizer`, `facepriority`, `lvqty`, `liveviewsize`) against this list and report
each one missing or renamed. This single diff is probably the most valuable output of the whole session.

### 3. Live view over Wi-Fi (the risky layer)

```sh
.venv/bin/python -B -m omcap.server --no-browser     # read-only first
```

Open `http://127.0.0.1:8765`, connect Wi-Fi, start live view.

- Measure the real rate: the app shows a performance figure; also watch `/api/state` (`lvperf`, `lvqty`,
  `lv_age`) once a second.
- The Wi-Fi path decodes a body-specific extension block (`/api/lvext` exposes it for research). Dump it
  repeatedly while changing one thing at a time on the camera — aperture, shutter, ISO, exposure comp —
  and diff the words. Log unknown IDs raw; never invent a layout from the Mark I.
- Expect a firewall prompt on the first frame: live view arrives as **UDP on port 5555** and is dropped
  silently if inbound is blocked.

### 4. Control (only with `--allow-write`, and ask the human first)

- Tap to focus, then Take picture. Note latency and whether the app's AF frame lands where the camera
  focused — this body already reports a wrong AF point over USB (`x = 0`), so check whether Wi-Fi agrees.
- LV super-control-panel writes, one property at a time, reading back after each.
- Playback and "save to computer".

### 5. Report

Write `tools/mk2/wifi-results.md`: capability diff, live view rate, extension findings, which
features work, which error. Keep it factual and body-specific, with the raw numbers you measured. No
serial numbers.

## Useful API surface when driving the app automatically

Everything the UI does is also an HTTP call on `127.0.0.1:8765`:

| Call | What |
|---|---|
| `GET /api/connections` | detected transports and names |
| `POST /api/connect` `{"type":"wifi"}` | connect |
| `GET /api/state` | live flag, `lvqty`, `lv_age`, jobs, latest shot |
| `GET /api/device` | model, battery |
| `GET /api/props` | current settings |
| `GET /api/afframe` | AF area/field |
| `GET /api/lvext` | raw Wi-Fi live view extension (research) |
| `POST /api/shoot` | full press (needs `--allow-write`) |
| `POST /api/shutter` `{"stage":1}` / `{"stage":0}` | half press / release |
| `GET /live.mjpg` | MJPEG stream |

## Pitfalls that will cost you an hour each

- **The camera is AP-only.** No bridged mode, no home-network join. If the machine has one radio, it
  cannot be on the internet and the camera at the same time.
- **A dead battery ends the session, not the link**: the body drops off Wi-Fi at low battery with no
  warning. This exact thing ended the USB session that produced `README.md` — a full battery or USB power
  first.
- **`Storage`, `MTP` and `PC RAW` are all wrong for control over USB**; only the camera+monitor entry
  exposes vendor opcodes. Not needed for Wi-Fi, but it explains the USB report.
- **Windows has no libgphoto2** — if you run any part of this on Windows, the own-PTP backend is the only
  one, and the app must be told `--usb-backend ptp`.
- **Do not "fix" the live view fps by rewriting the read loop** — the 15 fps over USB is the body's own
  rate (66 ms gaps, verified per frame). Measure before optimising.
