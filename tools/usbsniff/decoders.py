"""Decoder plugins: Transfer list -> Operation list.

Each decoder is a function registered in DECODERS. `pick()` chooses one by content when the user
does not name it. Add a decoder by writing `def decode_x(transfers, names)` and registering it.
"""
import json
import os
import struct

from .model import IN, OUT, Operation

HERE = os.path.dirname(os.path.abspath(__file__))
DECODERS = {}


def register(name):
    def deco(fn):
        DECODERS[name] = fn
        return fn
    return deco


def load_names(path=None):
    """PTP name tables as {section: {int: name}}; edit ptp_names.json or pass your own file."""
    with open(path or os.path.join(HERE, "ptp_names.json")) as f:
        raw = json.load(f)
    names = {k: {int(c, 16): n for c, n in v.items()} for k, v in raw.items() if isinstance(v, dict)}
    names["property_ops"] = {int(c, 16) for c in raw.get("property_ops", [])}
    return names


def _name(names, section, code, fallback):
    return names.get(section, {}).get(code) or "%s_0x%04X" % (fallback, code)


# ---- PTP -------------------------------------------------------------------------------------
def _containers(transfers):
    """Reassemble the PTP container stream of both bulk directions in time order (a container may
    span several transfers; data may be truncated, so lengths come from Transfer.length).
    Yields (time, direction, (len, type, code, tid), stored payload, full payload length, status, end time)."""
    state = {IN: [b"", 0, 0, 0.0, "ok"], OUT: [b"", 0, 0, 0.0, "ok"]}  # buf, need, got, t0, status
    for tr in transfers:
        if tr.kind == "interrupt":
            continue
        s = state[tr.direction]
        if s[1] == 0:
            if len(tr.data) < 12:
                continue
            s[:] = [b"", struct.unpack_from("<I", tr.data)[0], 0, tr.time, tr.status]
        s[0] += tr.data
        s[2] += tr.length
        if s[2] >= s[1]:
            ln, ctype, code, tid = struct.unpack_from("<IHHI", s[0])
            yield s[3], tr.direction, (ln, ctype, code, tid), s[0][12:ln], ln - 12, s[4], tr.time
            s[1] = 0


def _u32s(payload):
    n = len(payload) // 4
    return struct.unpack_from("<%dI" % n, payload) if n else ()


@register("ptp")
def decode_ptp(transfers, names):
    ops, by_tid = [], {}
    for t, direction, (ln, ctype, code, tid), payload, plen, status, t_end in _containers(transfers):
        op = by_tid.get(tid)
        if direction == OUT and ctype == 1:
            op = Operation(t, "ptp", code, _name(names, "operations", code, "Op"), params=_u32s(payload))
            ops.append(op)
            by_tid[tid] = op
        elif ctype == 2 and op:
            if direction == OUT:
                op.data_out, op.data_out_len = payload, plen
            else:
                op.data_in, op.data_in_len = payload, plen
        elif direction == IN and ctype == 3 and op:
            op.resp_code, op.resp_params, op.end_time = code, _u32s(payload), t_end
            op.resp_name = _name(names, "responses", code, "Resp")
            if status != "ok":
                op.notes.append(status)
    for tr in transfers:
        if tr.kind == "interrupt" and tr.direction == IN and len(tr.data) >= 12:
            ln, ctype, code, tid = struct.unpack_from("<IHHI", tr.data)
            if ctype == 4:
                ops.append(Operation(tr.time, "ptp", code, _name(names, "events", code, "Event"),
                                     params=_u32s(tr.data[12:ln]), kind="event"))
    ops.sort(key=lambda o: o.time)
    for op in ops:
        if op.code in names.get("property_ops", ()) and op.params:
            op.notes.append("prop " + _name(names, "properties", op.params[0], "Prop"))
    return ops


# ---- USB mass storage (bulk-only transport) --------------------------------------------------
SCSI = {0x00: "TestUnitReady", 0x03: "RequestSense", 0x12: "Inquiry", 0x1A: "ModeSense6",
        0x1E: "PreventAllowMediumRemoval", 0x23: "ReadFormatCapacities", 0x25: "ReadCapacity10",
        0x28: "Read10", 0x2A: "Write10", 0x35: "SynchronizeCache10", 0x5A: "ModeSense10"}


@register("mass_storage")
def decode_msc(transfers, names):
    ops, cur = [], None
    for tr in transfers:
        d = tr.data
        if tr.direction == OUT and len(d) == 31 and d[:4] == b"USBC":
            _, tag, dlen, flags, lun, cblen = struct.unpack_from("<IIIBBB", d)
            cdb = d[15:15 + cblen]
            op = cdb[0] if cdb else 0
            cur = Operation(tr.time, "msc", op, SCSI.get(op, "SCSI_0x%02X" % op),
                            params=tuple(cdb[1:]), notes=["lun %d" % lun, "expect %d bytes" % dlen])
            ops.append(cur)
        elif len(d) == 13 and d[:4] == b"USBS" and cur:
            _, tag, residue, st = struct.unpack_from("<IIIB", d)
            cur.resp_code, cur.resp_name, cur.end_time = st, ("OK", "Failed", "PhaseError")[min(st, 2)], tr.time
            cur = None
        elif cur:
            if tr.direction == IN:
                cur.data_in += tr.data
                cur.data_in_len += tr.length
            else:
                cur.data_out += tr.data
                cur.data_out_len += tr.length
    return ops


# ---- HID and raw fallback --------------------------------------------------------------------
@register("hid")
def decode_hid(transfers, names):
    return [Operation(tr.time, "hid", tr.data[0] if tr.data else 0, "Report%s" % tr.direction.upper(),
                      data_in=tr.data if tr.direction == IN else b"", data_in_len=tr.length if tr.direction == IN else 0,
                      data_out=tr.data if tr.direction == OUT else b"", data_out_len=tr.length if tr.direction == OUT else 0,
                      kind="report", notes=[tr.endpoint])
            for tr in transfers if tr.kind == "interrupt"]


@register("hex")
def decode_hex(transfers, names):
    return [Operation(tr.time, "raw", 0, "%s %s" % (tr.endpoint, tr.direction),
                      data_in=tr.data if tr.direction == IN else b"", data_in_len=tr.length if tr.direction == IN else 0,
                      data_out=tr.data if tr.direction == OUT else b"", data_out_len=tr.length if tr.direction == OUT else 0,
                      kind="raw", notes=[tr.status] if tr.status != "ok" else [])
            for tr in transfers]


def pick(transfers):
    """Guess the decoder from the first outgoing bulk transfers."""
    for tr in transfers:
        if tr.direction != OUT or tr.kind != "bulk" or len(tr.data) < 12:
            continue
        if tr.data[:4] == b"USBC" and len(tr.data) == 31:
            return "mass_storage"
        ln, ctype = struct.unpack_from("<IH", tr.data)
        if ctype == 1 and 12 <= ln <= 32:
            return "ptp"
        break
    if transfers and all(tr.kind == "interrupt" for tr in transfers):
        return "hid"
    return "hex"
