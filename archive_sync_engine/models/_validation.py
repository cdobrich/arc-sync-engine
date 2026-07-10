"""
Internal validation helpers for canonical models.

These helpers enforce invariants shared across canonical models.
They are intentionally private to the models package.
"""

from __future__ import annotations

from datetime import datetime, timezone


def require_timezone_aware(name: str, value: datetime) -> None:
    """
    Ensure a datetime is timezone-aware.

    Canonical models require timezone-aware UTC datetimes.
    Adapters are responsible for normalizing timestamps before
    constructing canonical models.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware.")

    if value.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"{name} must be expressed in UTC.")
