from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..parser import ParsedFields, parse_syslog
from ..timeutil import format_receipt_time


@dataclass(slots=True)
class RawMessage:
    """What the ingest callback actually builds: device id + bytes, nothing
    parsed yet. Keeps the event loop callback to device-id-extraction plus a
    non-blocking enqueue (plan line 17) -- RFC3164/5424 field parsing happens
    later, off the hot ingest path, in the per-device writer coroutine.
    """

    raw: bytes
    receipt_time: datetime
    source_ip: str
    source_port: int
    transport: str


@dataclass(slots=True)
class MessageEnvelope:
    receipt_time: datetime
    source_ip: str
    source_port: int
    transport: str  # "udp" or "tcp"
    raw: bytes
    facility: int | None
    severity: int | None
    host: str | None
    tag: str | None
    message: str
    malformed: bool

    @classmethod
    def build(
        cls,
        raw: bytes,
        receipt_time: datetime,
        source_ip: str,
        source_port: int,
        transport: str,
    ) -> "MessageEnvelope":
        fields: ParsedFields = parse_syslog(raw)
        return cls(
            receipt_time=receipt_time,
            source_ip=source_ip,
            source_port=source_port,
            transport=transport,
            raw=raw,
            facility=fields.facility,
            severity=fields.severity,
            host=fields.host,
            tag=fields.tag,
            message=fields.message,
            malformed=fields.malformed,
        )

    @classmethod
    def from_raw(cls, raw_message: RawMessage) -> "MessageEnvelope":
        return cls.build(
            raw_message.raw,
            raw_message.receipt_time,
            raw_message.source_ip,
            raw_message.source_port,
            raw_message.transport,
        )

    def to_line(self) -> str:
        """Render for the append-only text file (source of truth, section 2).

        One line per message: ISO8601 receipt timestamp (authoritative,
        independent of whatever the device itself claims) followed by the
        raw payload, with embedded newlines/CRs stripped so the one-line-
        per-message invariant holds even for malformed input.
        """
        raw_text = self.raw.decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ")
        return f"{format_receipt_time(self.receipt_time)} {raw_text}"
