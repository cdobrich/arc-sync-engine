"""Archive Package integrity validation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .archive import Archive
from .paths import ArchivePaths
from .manifest import ARCHIVE_FORMAT_VERSION


@dataclass(frozen=True, slots=True)
class ArchiveIntegrityReport:
    """Result of validating one Archive Package."""

    valid: bool
    errors: tuple[str, ...]
    conversations_checked: int
    identities_checked: int
    messages_checked: int
    attachments_checked: int
    manifest_loaded: bool


def validate_archive_package(
    paths: ArchivePaths,
) -> ArchiveIntegrityReport:
    """
    Validate an Archive Package without changing canonical state.

    Validation checks the package manifest, canonical SQLite recomposition,
    and content-addressed attachment bytes.  No synchronization state or
    destination API is consulted.
    """

    errors: list[str] = []
    conversations_checked = 0
    identities_checked = 0
    messages_checked = 0
    attachments_checked = 0
    manifest_loaded = False

    if not paths.root.is_dir():
        errors.append(f"Archive Package directory does not exist: {paths.root}")
        return ArchiveIntegrityReport(
            valid=False,
            errors=tuple(errors),
            conversations_checked=0,
            identities_checked=0,
            messages_checked=0,
            attachments_checked=0,
            manifest_loaded=False,
        )

    if not paths.manifest.is_file():
        errors.append(f"Archive manifest is missing: {paths.manifest}")
    if not paths.database.is_file():
        errors.append(f"Archive database is missing: {paths.database}")

    if errors:
        return ArchiveIntegrityReport(
            valid=False,
            errors=tuple(errors),
            conversations_checked=0,
            identities_checked=0,
            messages_checked=0,
            attachments_checked=0,
            manifest_loaded=False,
        )

    try:
        with Archive(paths) as archive:
            manifest = archive.manifest
            manifest_loaded = True
            if manifest.archive_format_version != ARCHIVE_FORMAT_VERSION:
                errors.append(
                    "Unsupported archive format version "
                    f"{manifest.archive_format_version}."
                )
            if manifest.hash_algorithm.lower() != "sha256":
                errors.append(
                    "Unsupported archive attachment hash algorithm "
                    f"{manifest.hash_algorithm!r}; expected 'sha256'."
                )

            conversations = tuple(archive.iter_conversations())
            identities = tuple(archive.iter_identities())
            messages = tuple(archive.iter_messages())
            attachments = tuple(archive.iter_attachments())

            conversations_checked = len(conversations)
            identities_checked = len(identities)
            messages_checked = len(messages)
            attachments_checked = len(attachments)

            conversation_ids = {conversation.id for conversation in conversations}
            identity_keys = {
                identity.identity_key for identity in identities
            }
            message_ids = {message.id for message in messages}

            for message in messages:
                if message.conversation_id not in conversation_ids:
                    errors.append(
                        f"Message {message.id} references missing conversation "
                        f"{message.conversation_id}."
                    )
                if message.identity_key not in identity_keys:
                    errors.append(
                        f"Message {message.id} references missing identity "
                        f"{message.identity_key}."
                    )
                if (
                    message.reply_to is not None
                    and message.reply_to not in message_ids
                ):
                    errors.append(
                        f"Message {message.id} references missing reply target "
                        f"{message.reply_to}."
                    )

            attachment_store = archive.asset_store
            for attachment in attachments:
                attachments_checked += 0
                try:
                    path = attachment_store.path_for_sha256(attachment.sha256)
                except ValueError as exc:
                    errors.append(
                        f"Attachment {attachment.id} has invalid SHA-256: {exc}"
                    )
                    continue

                if not path.is_file():
                    errors.append(
                        f"Attachment {attachment.id} is missing content: {path}"
                    )
                    continue

                content = path.read_bytes()
                actual_size = len(content)
                actual_sha256 = hashlib.sha256(content).hexdigest()
                if actual_size != attachment.size:
                    errors.append(
                        f"Attachment {attachment.id} size mismatch: "
                        f"expected {attachment.size}, got {actual_size}."
                    )
                if actual_sha256 != attachment.sha256:
                    errors.append(
                        f"Attachment {attachment.id} SHA-256 mismatch: "
                        f"expected {attachment.sha256}, got {actual_sha256}."
                    )

    except Exception as exc:
        errors.append(f"Archive Package validation failed: {exc}")

    return ArchiveIntegrityReport(
        valid=not errors,
        errors=tuple(errors),
        conversations_checked=conversations_checked,
        identities_checked=identities_checked,
        messages_checked=messages_checked,
        attachments_checked=attachments_checked,
        manifest_loaded=manifest_loaded,
    )
