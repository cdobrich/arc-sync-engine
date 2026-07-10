"""
Attachment import operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.models import CanonicalAttachment

from .base import ImportOperation


@dataclass(frozen=True, slots=True)
class ImportAttachmentOperation(ImportOperation):
    """
    Import a canonical attachment into the Archive.

    The attachment metadata is stored in the Archive.

    Downloading and storing the attachment contents is performed
    separately by the Importer.
    """

    attachment: CanonicalAttachment