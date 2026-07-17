"""
Archive package manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ArchiveManifest:
    """
    Metadata describing an Archive package.
    """

    archive_format_version: int

    archive_engine_version: str

    created_at: datetime