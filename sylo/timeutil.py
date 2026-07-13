from __future__ import annotations

from datetime import datetime


def format_receipt_time(dt: datetime) -> str:
    """Fixed-width UTC ISO8601 with microseconds always present.

    datetime.isoformat() omits the fractional part entirely when microsecond
    == 0, which breaks lexicographic sort/comparison between rows that do
    and don't happen to land on a whole second. Both the raw text files and
    the indexer DB use this so a rebuild reproduces byte-identical strings.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00"
