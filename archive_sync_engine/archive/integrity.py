"""Archive Package integrity validation."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from collections.abc import Callable
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
    *,
    allow_incomplete_import: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> ArchiveIntegrityReport:
    """
    Validate an Archive Package without changing canonical state.

    Validation is deliberately streaming: it never materializes the complete
    archive entity set or attachment contents in memory.  ``on_progress``
    receives ``(current, total, detail)`` so callers can report long archive
    loads without coupling this layer to a particular UI.

    When ``allow_incomplete_import`` is true, missing reply targets are
    tolerated because an interrupted import can persist a reply before the
    referenced message has been traversed. Normal validation remains strict.
    """
    errors: list[str] = []
    conversations_checked = 0
    identities_checked = 0
    messages_checked = 0
    attachments_checked = 0
    manifest_loaded = False

    def report(current: int, total: int, detail: str) -> None:
        if on_progress is not None:
            on_progress(current, total, detail)

    if not paths.root.is_dir():
        errors.append(f"Archive Package directory does not exist: {paths.root}")
        return ArchiveIntegrityReport(False, tuple(errors), 0, 0, 0, 0, False)

    if not paths.manifest.is_file():
        errors.append(f"Archive manifest is missing: {paths.manifest}")
    if not paths.database.is_file():
        errors.append(f"Archive database is missing: {paths.database}")
    if errors:
        return ArchiveIntegrityReport(False, tuple(errors), 0, 0, 0, 0, False)

    try:
        invalid_empty_messages = _find_empty_message_ids(paths.database)
        if invalid_empty_messages:
            errors.extend(
                f"Canonical message {message_id} is invalid: "
                "A message must contain text or at least one attachment."
                for message_id in invalid_empty_messages
            )

        totals = _archive_entity_counts(paths.database)
        total = sum(totals)
        current = 0
        report(0, total, "Opening archive")

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

            conversation_ids: set[object] = set()
            for conversation in archive.iter_conversations():
                conversation_ids.add(conversation.id)
                conversations_checked += 1
                current += 1
                report(current, total, f"conversations={conversations_checked}")

            identity_keys: set[object] = set()
            for identity in archive.iter_identities():
                identity_keys.add(identity.identity_key)
                identities_checked += 1
                current += 1
                report(current, total, f"identities={identities_checked}")

            message_ids: set[object] = set()
            for message in archive.iter_messages():
                message_ids.add(message.id)
                messages_checked += 1
                current += 1
                report(current, total, f"messages={messages_checked}")
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

            if not allow_incomplete_import:
                for message_id, reply_to in _find_missing_reply_targets(paths.database):
                    errors.append(
                        f"Message {message_id} references missing reply target "
                        f"{reply_to}."
                    )

            attachment_store = archive.asset_store
            for attachment in archive.iter_attachments():
                attachments_checked += 1
                current += 1
                report(current, total, f"attachments={attachments_checked}")
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
                actual_size = path.stat().st_size
                if actual_size != attachment.size:
                    errors.append(
                        f"Attachment {attachment.id} size mismatch: "
                        f"expected {attachment.size}, got {actual_size}."
                    )
                digest = hashlib.sha256()
                with path.open("rb") as content:
                    for chunk in iter(lambda: content.read(1024 * 1024), b""):
                        digest.update(chunk)
                actual_sha256 = digest.hexdigest()
                if actual_sha256 != attachment.sha256:
                    errors.append(
                        f"Attachment {attachment.id} SHA-256 mismatch: "
                        f"expected {attachment.sha256}, got {actual_sha256}."
                    )

    except Exception as exc:
        message = f"Archive Package validation failed: {exc}"
        if message not in errors:
            errors.append(message)

    return ArchiveIntegrityReport(
        valid=not errors,
        errors=tuple(errors),
        conversations_checked=conversations_checked,
        identities_checked=identities_checked,
        messages_checked=messages_checked,
        attachments_checked=attachments_checked,
        manifest_loaded=manifest_loaded,
    )


def _archive_entity_counts(database: Path) -> tuple[int, int, int, int]:
    """Return entity totals without loading archive rows into Python."""
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM conversations),
                (SELECT COUNT(*) FROM identities),
                (SELECT COUNT(*) FROM messages),
                (SELECT COUNT(*) FROM attachments)
            """
        ).fetchone()
    return tuple(int(value or 0) for value in row)



def _find_missing_reply_targets(database: Path) -> tuple[tuple[str, str], ...]:
    """Find dangling reply references directly in SQLite without materializing messages."""
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT m.message_id, m.reply_to_message_id
            FROM messages AS m
            LEFT JOIN messages AS target
                ON target.message_id = m.reply_to_message_id
            WHERE m.reply_to_message_id IS NOT NULL
              AND target.message_id IS NULL
            ORDER BY m.created_at, m.message_id
            """
        )
        return tuple((str(row[0]), str(row[1])) for row in rows)

def _find_empty_message_ids(database: Path) -> tuple[str, ...]:
    """Find persisted messages that violate the canonical content invariant.

    This check runs directly against normalized storage so an invalid message
    can be identified by canonical ID even though recomposing it into a
    ``CanonicalMessage`` necessarily raises before normal Archive traversal
    can complete.
    """
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT m.message_id
            FROM messages AS m
            LEFT JOIN message_attachments AS ma
                ON ma.message_id = m.message_id
            WHERE (m.content IS NULL OR m.content = '')
            GROUP BY m.message_id
            HAVING COUNT(ma.attachment_id) = 0
            ORDER BY m.message_id
            """
        )
        return tuple(str(row[0]) for row in rows)
