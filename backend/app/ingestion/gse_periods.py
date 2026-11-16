"""GSE period grid and label validation, free of database dependencies.

Shared by the ingestion worker (``gse_job``) and the database-free Streamlit demo, so both apply
exactly the same rules: 3-minute labels, a publication lag, and refusal of mislabelled or
future-dated files.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.ingestion.gse_parser import GseFutureLabelError, GseLabelError

PERIOD = timedelta(minutes=3)
# Clock skew allowance between this host and GSE before a label counts as "in the future".
FUTURE_LABEL_TOLERANCE = timedelta(seconds=60)


def floor_period(t: datetime) -> datetime:
    """Floor an aware datetime to the 3-minute grid (GSE labels fall on :00, :03, ...)."""
    t = t.replace(second=0, microsecond=0)
    return t - timedelta(minutes=t.minute % 3)


def due_labels(now: datetime, lag: timedelta, count: int) -> list[datetime]:
    """Period labels that should be published by ``now``, newest first."""
    newest = floor_period(now - lag)
    return [newest - i * PERIOD for i in range(count)]


def validate_label(reading_label: datetime, expected_label: datetime | None, now: datetime) -> None:
    """Refuse a payload whose embedded period does not match the requested file, or lies ahead."""
    if expected_label is not None and reading_label != expected_label:
        raise GseLabelError(
            f"embedded period {reading_label.isoformat()} does not match requested "
            f"{expected_label.isoformat()}"
        )
    if reading_label > now + FUTURE_LABEL_TOLERANCE:
        raise GseFutureLabelError(f"embedded period {reading_label.isoformat()} is in the future")
