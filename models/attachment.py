"""
Canonical attachment model.

Attachments describe files associated with messages.

The canonical model stores metadata only. File bytes are managed
separately by the Archive's AssetStore using content-addressed storage.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ids import AttachmentId


@dataclass(frozen=True, slots=True)
class CanonicalAttachment:
    """
    Immutable attachment metadata.
    """

    id: AttachmentId
    filename: str
    content_type: str | None
    size: int
    sha256: str
