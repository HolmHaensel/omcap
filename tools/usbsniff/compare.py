"""Compare a baseline recording with an action recording.

An operation counts as "known" when the baseline holds one with the same protocol, code, params and
outgoing data. Polling noise is dropped by code (default: live view frames). For change-poll
operations (default: OMD_ChangedProperties, OMD_PollProperties) the reply data is part of the key,
so a poll that suddenly reports something new shows up.
"""
DEFAULT_IGNORE = {0x9484}               # OMD_GetLiveViewImage
DEFAULT_REPLY_WATCH = {0x9486, 0x948A}  # change polls: new reply data is interesting


def _key(op, reply_watch):
    k = (op.protocol, op.kind, op.code, op.params, op.data_out)
    if op.code in reply_watch:
        k += (op.data_in,)
    return k


def diff(baseline, action, ignore=DEFAULT_IGNORE, reply_watch=DEFAULT_REPLY_WATCH):
    """Operations of `action` (in order) that the baseline does not contain. Repeats inside the
    action are kept once."""
    known = {_key(op, reply_watch) for op in baseline}
    seen, out = set(), []
    for op in action:
        if op.code in ignore:
            continue
        k = _key(op, reply_watch)
        if k in known or k in seen:
            continue
        seen.add(k)
        out.append(op)
    return out
