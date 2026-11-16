"""usbsniff command line.

  usbsniff decode FILE [--decoder auto|ptp|mass_storage|hid|hex] [--device BUS:DEV]
                       [--jsonl OUT] [--pcapng OUT] [--names JSON]
  usbsniff diff BASELINE ACTION [--ignore 0x9484,...] [--watch-replies 0x9486,...]
  usbsniff hook build | prepare [--app PATH] | run NAME [--app PATH] [--max BYTES] [--restart-ptpcamerad]

The tool only listens. It has no replay.
"""
import argparse
import sys

from . import backends, compare, decoders, output


def _codes(s):
    return {int(c, 16) for c in s.split(",") if c.strip()} if s else set()


def _decode(path, decoder="auto", device=None, names_path=None):
    _backend, transfers = backends.load(path, device)
    names = decoders.load_names(names_path)
    name = decoders.pick(transfers) if decoder == "auto" else decoder
    return transfers, decoders.DECODERS[name](transfers, names), name


def cmd_decode(a):
    transfers, ops, name = _decode(a.file, a.decoder, a.device, a.names)
    t0 = ops[0].time if ops else 0.0
    print("# %s: %d transfers, decoder %s, %d operations" % (a.file, len(transfers), name, len(ops)))
    for op in ops:
        print(output.log_line(op, t0))
    if a.jsonl:
        with open(a.jsonl, "w") as f:
            for op in ops:
                f.write(output.to_json(op) + "\n")
    if a.pcapng:
        output.write_pcapng(transfers, a.pcapng)


def cmd_diff(a):
    _, base, _ = _decode(a.baseline, a.decoder, a.device, a.names)
    _, act, name = _decode(a.action, a.decoder, a.device, a.names)
    ignore = _codes(a.ignore) if a.ignore is not None else compare.DEFAULT_IGNORE
    watch = _codes(a.watch_replies) if a.watch_replies is not None else compare.DEFAULT_REPLY_WATCH
    new = compare.diff(base, act, ignore, watch)
    t0 = act[0].time if act else 0.0
    print("# only in %s (%d of %d operations, decoder %s)" % (a.action, len(new), len(act), name))
    for op in new:
        print(output.log_line(op, t0))


def cmd_hook(a):
    from . import app
    if a.what == "build":
        app.build()
    elif a.what == "prepare":
        app.prepare(a.app)
    else:
        if not a.name:
            sys.exit("usbsniff hook run NAME")
        app.run(a.name, a.app, a.max, a.restart_ptpcamerad)


def main(argv=None):
    p = argparse.ArgumentParser(prog="usbsniff", description="Listen-only USB capture and decoding.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--decoder", default="auto", choices=["auto"] + sorted(decoders.DECODERS))
        sp.add_argument("--device", help="pcap only: bus:dev to keep")
        sp.add_argument("--names", help="own PTP name table (JSON, like ptp_names.json)")

    d = sub.add_parser("decode", help="decode one recording")
    d.add_argument("file")
    d.add_argument("--jsonl")
    d.add_argument("--pcapng")
    common(d)
    d.set_defaults(fn=cmd_decode)

    c = sub.add_parser("diff", help="operations in ACTION that are not in BASELINE")
    c.add_argument("baseline")
    c.add_argument("action")
    c.add_argument("--ignore", help="hex codes to drop (default 0x9484)")
    c.add_argument("--watch-replies", help="hex codes whose reply data counts (default 0x9486,0x948A)")
    common(c)
    c.set_defaults(fn=cmd_diff)

    h = sub.add_parser("hook", help="ImageCaptureCore hook (macOS)")
    h.add_argument("what", choices=["build", "prepare", "run"])
    h.add_argument("name", nargs="?")
    h.add_argument("--app", default="/Applications/OM Capture.app")
    h.add_argument("--max", type=int, default=4096, help="bytes kept per data phase")
    h.add_argument("--restart-ptpcamerad", action="store_true",
                   help="stop macOS's camera service first (fixes a hung service; ask the user)")
    h.set_defaults(fn=cmd_hook)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
