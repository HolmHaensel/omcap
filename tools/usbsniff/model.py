"""Data model shared by backends, decoders and outputs."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

IN, OUT = "in", "out"


@dataclass
class Transfer:
    """One USB transfer (or one API-level data phase) as a backend saw it.

    data may be shorter than length when the recording truncated the payload.
    """
    time: float
    direction: str            # "in" (device -> host) or "out"
    endpoint: str             # e.g. "0x81", "bulk-out", "intr-in"; free text per backend
    data: bytes
    status: str = "ok"
    length: Optional[int] = None   # full length if data is truncated
    kind: str = "bulk"        # bulk | interrupt | control | iso
    device: str = ""          # bus:dev or program name, for filtering

    def __post_init__(self):
        if self.length is None:
            self.length = len(self.data)


@dataclass
class Operation:
    """One decoded protocol step (a PTP transaction, a SCSI command, a HID report, ...)."""
    time: float
    protocol: str
    code: int
    name: str
    params: Tuple[int, ...] = ()
    data_out: bytes = b""
    data_out_len: int = 0
    data_in: bytes = b""
    data_in_len: int = 0
    resp_code: Optional[int] = None
    resp_name: str = ""
    resp_params: Tuple[int, ...] = ()
    end_time: Optional[float] = None
    kind: str = "op"          # op | event | report | raw
    notes: List[str] = field(default_factory=list)

    @property
    def duration_ms(self):
        return None if self.end_time is None else (self.end_time - self.time) * 1000.0
