"""Tolerant RFC3164 / RFC5424 syslog parser.

Shared between the receiver's live ingest path and the indexer's
rebuild-from-text recovery path, so both parse a given payload identically.

Must never raise on garbage input (plan line 65) -- any field that can't be
extracted is left as None and the message is flagged malformed, but parsing
always returns a ParsedFields with at least the raw text as `message`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PRI_RE = re.compile(rb"^<(\d{1,3})>")
# RFC5424: "1 " version marker right after PRI.
_5424_HEADER_RE = re.compile(
    rb"^1 (\S+) (\S+) (\S+) (\S+) (\S+) (.*)$", re.DOTALL
)
# RFC3164: "Mmm dd hh:mm:ss host tag: msg" (tag may end in [pid] or ':').
_3164_HEADER_RE = re.compile(
    rb"^(\w{3}\s+\d{1,2}\s\d{2}:\d{2}:\d{2})\s(\S+)\s(.*)$", re.DOTALL
)
_3164_TAG_RE = re.compile(rb"^([^:\[\s]{1,32})(\[\d+\])?:\s?(.*)$", re.DOTALL)


@dataclass(slots=True)
class ParsedFields:
    facility: int | None
    severity: int | None
    host: str | None
    tag: str | None
    message: str
    malformed: bool


def _decode(b: bytes) -> str:
    return b.decode("utf-8", errors="replace")


def _split_structured_data(remainder: bytes) -> bytes:
    """Separate RFC5424 MSG from the STRUCTURED-DATA that precedes it
    (RFC 5424 section 6.3): NILVALUE ("-") or one or more bracketed
    SD-ELEMENTs concatenated with no separator, e.g.
    "[id@32473 a=\"1\"][id2@32473 b=\"2\"] the actual message".

    A naive split on the first space (the previous approach here) only
    works for the nilvalue case -- as soon as an SD-PARAM value contains a
    space (routine for journald's systemd-journal-upload export format,
    e.g. MESSAGE="some words"), it cuts partway through the SD-ELEMENT and
    leaks the rest of it, MSG included, verbatim into the message field.
    This instead walks the bytes tracking quote/escape state (PARAM-VALUE
    may contain escaped \\", \\\\, \\] per the RFC) to find where
    STRUCTURED-DATA actually ends.
    """
    if remainder.startswith(b"-"):
        rest = remainder[1:]
        return rest[1:] if rest[:1] == b" " else rest

    if not remainder.startswith(b"["):
        # Not well-formed STRUCTURED-DATA -- don't guess, keep everything
        # rather than risk silently dropping real message content.
        return remainder

    i = 0
    n = len(remainder)
    while i < n and remainder[i : i + 1] == b"[":
        i += 1
        in_quotes = False
        closed = False
        while i < n:
            c = remainder[i : i + 1]
            if in_quotes:
                if c == b"\\":
                    i += 2
                    continue
                if c == b'"':
                    in_quotes = False
                i += 1
                continue
            if c == b'"':
                in_quotes = True
                i += 1
                continue
            if c == b"]":
                i += 1
                closed = True
                break
            i += 1
        if not closed:
            # Unterminated SD-ELEMENT -- malformed, keep everything as-is.
            return remainder

    return remainder[i + 1 :] if remainder[i : i + 1] == b" " else remainder[i:]


def _split_pri(raw: bytes) -> tuple[int | None, int | None, bytes]:
    m = _PRI_RE.match(raw)
    if not m:
        return None, None, raw
    pri = int(m.group(1))
    if pri > 191:  # facility(0-23)*8 + severity(0-7) -> max 191
        return None, None, raw
    facility, severity = divmod(pri, 8)
    return facility, severity, raw[m.end():]


def parse_syslog(raw: bytes) -> ParsedFields:
    try:
        return _parse_syslog(raw)
    except Exception:
        return ParsedFields(
            facility=None,
            severity=None,
            host=None,
            tag=None,
            message=_decode(raw),
            malformed=True,
        )


def _parse_syslog(raw: bytes) -> ParsedFields:
    if not raw:
        return ParsedFields(None, None, None, None, "", malformed=True)

    facility, severity, rest = _split_pri(raw)
    malformed = facility is None

    m5424 = _5424_HEADER_RE.match(rest)
    if m5424:
        _timestamp, host, app_name, _procid, _msgid, remainder = m5424.groups()
        # After APP-NAME PROCID MSGID there is STRUCTURED-DATA then optional
        # " " MSG. We only care about tag+msg per the plan's envelope spec,
        # so discard STRUCTURED-DATA entirely and keep only MSG.
        msg = _split_structured_data(remainder)
        return ParsedFields(
            facility=facility,
            severity=severity,
            host=_decode(host) if host != b"-" else None,
            tag=_decode(app_name) if app_name != b"-" else None,
            message=_decode(msg),
            malformed=malformed,
        )

    m3164 = _3164_HEADER_RE.match(rest)
    if m3164:
        _timestamp, host, remainder = m3164.groups()
        mtag = _3164_TAG_RE.match(remainder)
        if mtag:
            tag_name, _pid, msg = mtag.groups()
            return ParsedFields(
                facility=facility,
                severity=severity,
                host=_decode(host),
                tag=_decode(tag_name),
                message=_decode(msg),
                malformed=malformed,
            )
        return ParsedFields(
            facility=facility,
            severity=severity,
            host=_decode(host),
            tag=None,
            message=_decode(remainder),
            malformed=malformed,
        )

    # Neither header matched -- keep whatever PRI we got, rest is the message.
    return ParsedFields(
        facility=facility,
        severity=severity,
        host=None,
        tag=None,
        message=_decode(rest),
        malformed=True,
    )
