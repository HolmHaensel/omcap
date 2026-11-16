"""Outputs: readable log lines, JSON lines and pcapng (USBPcap link type, opens in Wireshark)."""
import json
import struct

from .model import IN


def _hexs(b, limit=16):
    s = b[:limit].hex(" ")
    return s + (" …" if len(b) > limit else "")


def _params(op):
    return ", ".join("0x%X" % p for p in op.params)


def log_line(op, t0=0.0):
    """One line per operation: time, name(params), data, response, duration, notes."""
    parts = ["%9.3f" % (op.time - t0)]
    if op.kind == "event":
        parts.append("EVENT 0x%04X %s(%s)" % (op.code, op.name, _params(op)))
    elif op.protocol == "raw":
        parts.append(op.name)
    else:
        parts.append("0x%04X %s(%s)" % (op.code, op.name, _params(op)))
    if op.data_out_len:
        parts.append("out=%dB [%s]" % (op.data_out_len, _hexs(op.data_out)))
    if op.data_in_len:
        parts.append("in=%dB [%s]" % (op.data_in_len, _hexs(op.data_in)))
    if op.resp_code is not None:
        r = "-> %s" % op.resp_name
        if op.resp_params:
            r += "(%s)" % ", ".join("0x%X" % p for p in op.resp_params)
        parts.append(r)
    if op.duration_ms is not None:
        parts.append("%.1f ms" % op.duration_ms)
    if op.notes:
        parts.append("; ".join(op.notes))
    return "  ".join(parts)


def to_json(op):
    return json.dumps({
        "t": round(op.time, 6), "protocol": op.protocol, "kind": op.kind, "code": "0x%04X" % op.code,
        "name": op.name, "params": ["0x%X" % p for p in op.params],
        "out_len": op.data_out_len, "out": op.data_out.hex(), "in_len": op.data_in_len, "in": op.data_in.hex(),
        "resp": None if op.resp_code is None else "0x%04X" % op.resp_code, "resp_name": op.resp_name,
        "resp_params": ["0x%X" % p for p in op.resp_params], "ms": op.duration_ms, "notes": op.notes,
    })


def write_pcapng(transfers, path):
    """Write transfers as pcapng with LINKTYPE_USBPCAP (249). Endpoint names that are not
    numbers get 0x81 (in) / 0x01 (out); interrupt-in events get 0x82."""
    def block(btype, body):
        body += b"\0" * (-len(body) % 4)
        n = len(body) + 12
        return struct.pack("<II", btype, n) + body + struct.pack("<I", n)

    with open(path, "wb") as f:
        f.write(block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1)))
        f.write(block(1, struct.pack("<HHI", 249, 0, 0)))
        for i, tr in enumerate(transfers):
            try:
                ep = int(tr.endpoint, 16)
            except ValueError:
                ep = (0x82 if tr.kind == "interrupt" else 0x81) if tr.direction == IN else 0x01
            xfer = 1 if tr.kind == "interrupt" else 3
            hdr = struct.pack("<HQIHBHHBBI", 27, i, 0, 0x09, 1 if tr.direction == IN else 0, 1, 1, ep, xfer, tr.length)
            pkt = hdr + tr.data  # dataLength keeps the full length; the packet holds what was recorded
            us = int(tr.time * 1e6)
            f.write(block(6, struct.pack("<IIIII", 0, us >> 32, us & 0xFFFFFFFF, len(pkt), 27 + tr.length) + pkt))
