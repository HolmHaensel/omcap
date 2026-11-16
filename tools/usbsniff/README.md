# usbsniff – listen-only USB capture and decoding

`usbsniff` records what a program says to a USB device, decodes the protocol and compares two
recordings. It only listens: there is no replay.

## Pieces

| Part | File | What it does |
|---|---|---|
| Hook backend (macOS) | `hook/usbsniff_hook.m`, `app.py` | Logs every PTP command, data phase, response and event that a program sends through Apple's ImageCaptureCore (`-[ICCameraDevice requestSendPTPCommand:…]`, `cameraDevice:didReceivePTPEvent:`). |
| pcap backend | `backends.py` | Reads pcap/pcapng with USBPcap (Windows) or usbmon (Linux) link types, e.g. from a VM guest. |
| Decoders | `decoders.py` | `ptp` (names in `ptp_names.json`, editable), `mass_storage` (CBW/CSW + SCSI), `hid`, `hex`. Chosen from the traffic or with `--decoder`. |
| Outputs | `output.py` | Log lines, JSON lines (`--jsonl`), pcapng for Wireshark (`--pcapng`). |
| Compare | `compare.py` | `diff BASELINE ACTION`: only the operations that the action adds. |

Python 3.9+, standard library only. `clang` (Xcode command line tools) builds the hook.

## Why a hook and not packet capture

On Apple Silicon there is no USB capture interface for Wireshark/libpcap. Programs that use
ImageCaptureCore (OM Capture's `OlyCCHelper` does, via `OlyRum3.framework`) hand complete PTP
containers to `ptpcamerad`, so logging at that API gives full payloads, direction and time stamps.
For programs that use IOKit or libusb directly, record in a Windows/Linux VM with USB passthrough
(USBPcap, usbmon) and import the file.

## Recording a program that uses ImageCaptureCore

```sh
python -B tools/usbsniff hook build                 # out/usbsniff/usbsniff_hook.dylib
python -B tools/usbsniff hook prepare --app "/Applications/Some App.app"
python -B tools/usbsniff hook run baseline --app "/Applications/Some App.app"
```

`prepare` copies the bundle to `out/usbsniff/apps/` and signs the **copy** ad hoc without the
hardened runtime; the installed program is never touched. `run` starts the copy with
`DYLD_INSERT_LIBRARIES` and writes `out/research/usbsniff/NAME.jsonl`. Child processes started
with NSTask inherit the hook. Data phases are cut to 4096 bytes (`--max`), the full length is kept.

Only one program may hold the device: quit the original program and anything else using it.
If the program hangs while connecting (seen 2026-11-16: the camera's answers stopped after a few
queries, with the original OM Capture too), macOS's camera service `ptpcamerad` is stuck from an
earlier session: `hook run NAME --restart-ptpcamerad` stops it first (macOS restarts it on demand).

## Decoding and comparing

```sh
python -B tools/usbsniff decode out/research/usbsniff/loupe_on.jsonl
python -B tools/usbsniff diff out/research/usbsniff/baseline.jsonl out/research/usbsniff/loupe_on.jsonl
python -B tools/usbsniff decode capture.pcapng --device 1:4 --decoder ptp --pcapng out.pcapng
```

A log line looks like

```
    0.512  0x1016 SetDevicePropValue(0xD0CF)  out=2B [02 00]  -> OK  3.1 ms  prop LoupeStage(…)
```

`diff` treats an operation as known when the baseline has one with the same code, parameters and
outgoing data. Live view frames (`0x9484`) are dropped; for the change polls `0x9486`/`0x948A` the
reply data counts, so a poll that suddenly reports a changed property shows up. Change both lists
with `--ignore` and `--watch-replies`.

Record one action per file, and always compare against a baseline taken just before: a live
image that changes is no proof of anything (the scene moves).

## Example: OM Capture and the E-M1 Mark I loupe

1. Stop E-M1 Capture and `tools/usb_props.py`; quit OM Capture.
2. `hook prepare` (default app is OM Capture), then for each step `hook run NAME`, do one thing in
   OM Capture, quit it: `baseline` (connect, wait), `loupe_on_5x`, `loupe_move`, `loupe_14x`, `loupe_off`.
3. `diff baseline loupe_on_5x` and so on. Results: `out/research/loupe_protocol.md`.

## Adding a decoder

Write `def decode_x(transfers, names)` in `decoders.py` returning `Operation` objects and decorate
it with `@register("x")`. Extend `pick()` if the protocol can be recognised from its bytes.

## Tests

`python -B -m unittest discover -s tests` (`tests/test_usbsniff_decode.py`, synthetic traffic, no hardware).
