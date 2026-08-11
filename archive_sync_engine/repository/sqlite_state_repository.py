"""
SQLite-backed StateRepository.

SQLite stores synchronization metadata only. Canonical Archive content remains
owned by the Archive and AssetStore.

The repository uses one current-state row and an append-only execution record
for each successful synchronization operation. State replacement and the
corresponding execution record are committed in the same SQLite transaction.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.executor import ExecutionResult
from archive_sync_engine.importer import ImportSession
from archive_sync_engine.importer.state import ImportState
from archive_sync_engine.models import CanonicalAttachment, CanonicalReaction
from archive_sync_engine.models.ids import MessageId
from archive_sync_engine.operations import SyncOperation
from archive_sync_engine.sync import SynchronizationState

from .state_repository import StateRepository


_SCHEMA_VERSION = 1


class SQLiteStateRepository(StateRepository):
    """
    Durable SQLite implementation of ``StateRepository``.

    The repository owns synchronization metadata, not canonical content.
    ``record_execution`` atomically replaces the current synchronization
    snapshot and records the successful execution that produced it.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._connection = sqlite3.connect(self._path)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._connection.close()

    def __enter__(self) -> "SQLiteStateRepository":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def save_import_session(self, session: ImportSession) -> None:
        """Persist the current import session as JSON metadata."""
        payload = {
            "started_at": session.started_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "state": (
                dict(session.state.payload)
                if session.state is not None
                else None
            ),
            "paused": session.paused,
            "completed": session.completed,
            "cancelled": session.cancelled,
            "error": session.error,
        }

        encoded = _encode_json(payload)

        with self._connection:
            self._connection.execute(
                """
                INSERT INTO import_session (id, payload)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload
                """,
                (encoded,),
            )

    def load_import_session(self) -> ImportSession | None:
        """Load the persisted import session, if one exists."""
        row = self._connection.execute(
            "SELECT payload FROM import_session WHERE id = 1",
        ).fetchone()

        if row is None:
            return None

        from datetime import datetime

        payload = _decode_json(row["payload"])
        state_payload = payload.get("state")

        return ImportSession(
            started_at=datetime.fromisoformat(payload["started_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            state=(
                ImportState(payload=dict(state_payload))
                if state_payload is not None
                else None
            ),
            paused=bool(payload["paused"]),
            completed=bool(payload["completed"]),
            cancelled=bool(payload["cancelled"]),
            error=payload["error"],
        )

    def load_synchronization_state(self) -> SynchronizationState:
        """Load the current synchronization-state snapshot."""
        row = self._connection.execute(
            "SELECT payload FROM synchronization_state WHERE id = 1",
        ).fetchone()

        if row is None:
            return SynchronizationState()

        state = _state_from_dict(_decode_json(row["payload"]))
        _validate_synchronization_state(state)
        return state

    def record_execution(
        self,
        operation: SyncOperation,
        result: ExecutionResult,
        synchronization_state: SynchronizationState,
    ) -> None:
        """
        Atomically persist the new state and successful execution metadata.
        """
        _validate_synchronization_state(synchronization_state)
        state_payload = _encode_json(_state_to_dict(synchronization_state))
        operation_type = type(operation).__name__

        with self._connection:
            self._connection.execute(
                """
                INSERT INTO synchronization_state (id, payload)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload
                """,
                (state_payload,),
            )
            self._connection.execute(
                """
                INSERT INTO execution_log (
                    operation_type,
                    canonical_id,
                    deleted,
                    deleted_entity
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    operation_type,
                    result.canonical_id,
                    int(result.deleted),
                    (
                        result.deleted_entity.value
                        if result.deleted_entity is not None
                        else None
                    ),
                ),
            )

    def _initialize(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS repository_metadata (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    schema_version INTEGER NOT NULL
                )
                """,
            )
            row = self._connection.execute(
                "SELECT schema_version FROM repository_metadata WHERE id = 1",
            ).fetchone()
            if row is None:
                self._connection.execute(
                    "INSERT INTO repository_metadata (id, schema_version) VALUES (1, ?)",
                    (_SCHEMA_VERSION,),
                )
            elif int(row["schema_version"]) != _SCHEMA_VERSION:
                raise RuntimeError(
                    "Unsupported SQLite StateRepository schema version: "
                    f"{row['schema_version']}."
                )

            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS synchronization_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL
                )
                """,
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_type TEXT NOT NULL,
                    canonical_id TEXT,
                    deleted INTEGER NOT NULL,
                    deleted_entity TEXT
                )
                """,
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS import_session (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL
                )
                """,
            )


def _encode_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    )


def _decode_json(value: str) -> dict[str, Any]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("Stored repository payload must be a JSON object.")
    return decoded


def _ref_to_dict(ref: object) -> dict[str, str]:
    return {"id": ref.id}


def _conversation_ref_from_dict(value: dict[str, Any]) -> DestinationConversationRef:
    return DestinationConversationRef(str(value["id"]))


def _identity_ref_from_dict(value: dict[str, Any]) -> DestinationIdentityRef:
    return DestinationIdentityRef(str(value["id"]))


def _message_ref_from_dict(value: dict[str, Any]) -> DestinationMessageRef:
    return DestinationMessageRef(str(value["id"]))


def _reaction_to_dict(reaction: CanonicalReaction) -> dict[str, Any]:
    return {
        "identity_key": str(reaction.identity_key),
        "emoji": reaction.emoji,
        "emoji_id": (
            str(reaction.emoji_id)
            if reaction.emoji_id is not None
            else None
        ),
        "is_custom": reaction.is_custom,
    }


def _reaction_from_dict(value: dict[str, Any]) -> CanonicalReaction:
    from archive_sync_engine.models.ids import EmojiId, IdentityKey

    return CanonicalReaction(
        identity_key=IdentityKey(str(value["identity_key"])),
        emoji=str(value["emoji"]),
        emoji_id=(
            EmojiId(str(value["emoji_id"]))
            if value.get("emoji_id") is not None
            else None
        ),
        is_custom=bool(value["is_custom"]),
    )


def _attachment_to_dict(attachment: CanonicalAttachment) -> dict[str, Any]:
    return {
        "id": str(attachment.id),
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "size": attachment.size,
        "sha256": attachment.sha256,
    }


def _attachment_from_dict(value: dict[str, Any]) -> CanonicalAttachment:
    from archive_sync_engine.models.ids import AttachmentId

    return CanonicalAttachment(
        id=AttachmentId(str(value["id"])),
        filename=str(value["filename"]),
        content_type=value.get("content_type"),
        size=int(value["size"]),
        sha256=str(value["sha256"]),
    )


def _state_to_dict(state: SynchronizationState) -> dict[str, Any]:
    return {
        "conversations": {
            key: _ref_to_dict(value)
            for key, value in state.conversations.items()
        },
        "identities": {
            key: _ref_to_dict(value)
            for key, value in state.identities.items()
        },
        "messages": {
            key: _ref_to_dict(value)
            for key, value in state.messages.items()
        },
        "conversation_fingerprints": dict(state.conversation_fingerprints),
        "conversation_parent_ids": dict(state.conversation_parent_ids),
        "identity_fingerprints": dict(state.identity_fingerprints),
        "message_fingerprints": dict(state.message_fingerprints),
        "message_content_fingerprints": dict(
            state.message_content_fingerprints,
        ),
        "message_reactions": {
            key: [_reaction_to_dict(reaction) for reaction in value]
            for key, value in state.message_reactions.items()
        },
        "message_attachments": {
            key: [_attachment_to_dict(attachment) for attachment in value]
            for key, value in state.message_attachments.items()
        },
        "message_pinned": dict(state.message_pinned),
        "message_reply_to": {
            key: (
                str(value)
                if value is not None
                else None
            )
            for key, value in state.message_reply_to.items()
        },
    }


def _validate_synchronization_state(
    state: SynchronizationState,
) -> None:
    """Validate the current synchronization-state persistence contract."""

    conversation_ids = set(state.conversations)
    identity_ids = set(state.identities)
    message_ids = set(state.messages)

    orphan_conversation_fingerprints = (
        set(state.conversation_fingerprints) - conversation_ids
    )
    if orphan_conversation_fingerprints:
        raise ValueError(
            "SynchronizationState contains conversation fingerprints "
            "without destination mappings: "
            f"{sorted(orphan_conversation_fingerprints)!r}"
        )

    orphan_identity_fingerprints = (
        set(state.identity_fingerprints) - identity_ids
    )
    if orphan_identity_fingerprints:
        raise ValueError(
            "SynchronizationState contains identity fingerprints "
            "without destination mappings: "
            f"{sorted(orphan_identity_fingerprints)!r}"
        )

    component_baselines = {
        "message_content_fingerprints": set(
            state.message_content_fingerprints
        ),
        "message_reactions": set(state.message_reactions),
        "message_attachments": set(state.message_attachments),
        "message_pinned": set(state.message_pinned),
        "message_reply_to": set(state.message_reply_to),
        "message_fingerprints": set(state.message_fingerprints),
    }

    for name, ids in component_baselines.items():
        orphan_ids = ids - message_ids
        if orphan_ids:
            raise ValueError(
                f"SynchronizationState contains {name} entries "
                "without destination mappings: "
                f"{sorted(orphan_ids)!r}"
            )

    missing_content_baselines = (
        message_ids - set(state.message_content_fingerprints)
    )
    if missing_content_baselines:
        raise ValueError(
            "SynchronizationState messages are missing content "
            "baselines: "
            f"{sorted(missing_content_baselines)!r}"
        )

    complete_messages = set(state.message_fingerprints)
    required_component_names = (
        "message_reactions",
        "message_attachments",
        "message_pinned",
        "message_reply_to",
    )
    for name in required_component_names:
        missing_ids = complete_messages - set(getattr(state, name))
        if missing_ids:
            raise ValueError(
                "SynchronizationState contains complete message "
                f"fingerprints without {name} baselines: "
                f"{sorted(missing_ids)!r}"
            )

    dangling_replies = {
        canonical_id: reply_to
        for canonical_id, reply_to in state.message_reply_to.items()
        if reply_to is not None and str(reply_to) not in message_ids
    }
    if dangling_replies:
        raise ValueError(
            "SynchronizationState contains dangling message reply "
            f"baselines: {dangling_replies!r}"
        )


def _state_from_dict(value: dict[str, Any]) -> SynchronizationState:
    return SynchronizationState(
        conversations={
            str(key): _conversation_ref_from_dict(ref)
            for key, ref in value.get("conversations", {}).items()
        },
        identities={
            str(key): _identity_ref_from_dict(ref)
            for key, ref in value.get("identities", {}).items()
        },
        messages={
            str(key): _message_ref_from_dict(ref)
            for key, ref in value.get("messages", {}).items()
        },
        conversation_fingerprints={
            str(key): str(item)
            for key, item in value.get("conversation_fingerprints", {}).items()
        },
        conversation_parent_ids={
            str(key): (
                str(item)
                if item is not None
                else None
            )
            for key, item in value.get("conversation_parent_ids", {}).items()
        },
        identity_fingerprints={
            str(key): str(item)
            for key, item in value.get("identity_fingerprints", {}).items()
        },
        message_fingerprints={
            str(key): str(item)
            for key, item in value.get("message_fingerprints", {}).items()
        },
        message_content_fingerprints={
            str(key): str(item)
            for key, item in value.get("message_content_fingerprints", {}).items()
        },
        message_reactions={
            str(key): tuple(
                _reaction_from_dict(item)
                for item in reactions
            )
            for key, reactions in value.get("message_reactions", {}).items()
        },
        message_attachments={
            str(key): tuple(
                _attachment_from_dict(item)
                for item in attachments
            )
            for key, attachments in value.get("message_attachments", {}).items()
        },
        message_pinned={
            str(key): bool(item)
            for key, item in value.get("message_pinned", {}).items()
        },
        message_reply_to={
            str(key): (
                MessageId(str(item))
                if item is not None
                else None
            )
            for key, item in value.get("message_reply_to", {}).items()
        },
    )

