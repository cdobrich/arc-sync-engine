from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.executor import ExecutionResult
from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalReaction,
)
from archive_sync_engine.models.ids import (
    AttachmentId,
    ConversationId,
    EmojiId,
    IdentityKey,
    MessageId,
)
from archive_sync_engine.operations import EditMessageOperation
from archive_sync_engine.repository import SQLiteStateRepository
from archive_sync_engine.sync import SynchronizationState
from archive_sync_engine.importer import ImportSession
from archive_sync_engine.importer.state import ImportState


def test_sqlite_repository_round_trips_complete_synchronization_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-1"),
        filename="document.txt",
        content_type="text/plain",
        size=12,
        sha256="a" * 64,
    )
    reaction = CanonicalReaction(
        identity_key=IdentityKey("identity-1"),
        emoji="custom",
        emoji_id=EmojiId("emoji-1"),
        is_custom=True,
    )
    state = SynchronizationState(
        conversations={
            "conversation-1": DestinationConversationRef(
                "destination-conversation-1",
            ),
        },
        identities={
            "identity-1": DestinationIdentityRef(
                "destination-identity-1",
            ),
        },
        messages={"message-1": DestinationMessageRef("destination-1")},
        conversation_fingerprints={
            "conversation-1": "conversation-full",
        },
        conversation_parent_ids={
            "conversation-1": "conversation-parent",
        },
        identity_fingerprints={
            "identity-1": "identity-full",
        },
        message_fingerprints={"message-1": "full"},
        message_content_fingerprints={"message-1": "content"},
        message_reactions={"message-1": (reaction,)},
        message_attachments={"message-1": (attachment,)},
        message_pinned={"message-1": True},
        message_reply_to={"message-1": None},
    )

    result = ExecutionResult(canonical_id="message-1")
    operation = EditMessageOperation(
        message=_message(),
    )

    with SQLiteStateRepository(path) as repository:
        repository.record_execution(operation, result, state)

    with SQLiteStateRepository(path) as repository:
        assert repository.load_synchronization_state() == state


def test_sqlite_repository_serializes_state_deterministically(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    state = SynchronizationState(
        conversations={
            "conversation-b": DestinationConversationRef("destination-b"),
            "conversation-a": DestinationConversationRef("destination-a"),
        },
        identities={
            "identity-b": DestinationIdentityRef("destination-b"),
            "identity-a": DestinationIdentityRef("destination-a"),
        },
        messages={
            "message-b": DestinationMessageRef("destination-b"),
            "message-a": DestinationMessageRef("destination-a"),
        },
        conversation_fingerprints={
            "conversation-b": "b",
            "conversation-a": "a",
        },
        conversation_parent_ids={
            "conversation-b": None,
            "conversation-a": "parent",
        },
        identity_fingerprints={
            "identity-b": "b",
            "identity-a": "a",
        },
        message_fingerprints={"message-b": "b", "message-a": "a"},
        message_content_fingerprints={
            "message-b": "b",
            "message-a": "a",
        },
        message_reactions={"message-b": (), "message-a": ()},
        message_attachments={"message-b": (), "message-a": ()},
        message_pinned={"message-b": False, "message-a": True},
        message_reply_to={
            "message-b": None,
            "message-a": None,
        },
    )

    with SQLiteStateRepository(path) as repository:
        repository.record_execution(
            EditMessageOperation(message=_message()),
            ExecutionResult(canonical_id="message-a"),
            state,
        )
        first_payload = repository._connection.execute(
            "SELECT payload FROM synchronization_state WHERE id = 1",
        ).fetchone()[0]

    with SQLiteStateRepository(path) as repository:
        repository.record_execution(
            EditMessageOperation(message=_message()),
            ExecutionResult(canonical_id="message-a"),
            state,
        )
        second_payload = repository._connection.execute(
            "SELECT payload FROM synchronization_state WHERE id = 1",
        ).fetchone()[0]

    assert first_payload == second_payload


def test_sqlite_repository_rolls_back_state_and_execution_log_together(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    initial_state = SynchronizationState(
        messages={
            "message-1": DestinationMessageRef("destination-old"),
        },
        message_content_fingerprints={"message-1": "old-content"},
    )
    new_state = SynchronizationState(
        messages={
            "message-1": DestinationMessageRef("destination-new"),
        },
        message_content_fingerprints={"message-1": "new-content"},
    )

    with SQLiteStateRepository(path) as repository:
        repository.record_execution(
            EditMessageOperation(message=_message()),
            ExecutionResult(canonical_id="message-1"),
            initial_state,
        )
        repository._connection.execute(
            """
            CREATE TRIGGER fail_execution_log_insert
            BEFORE INSERT ON execution_log
            BEGIN
                SELECT RAISE(ABORT, 'forced execution-log failure');
            END
            """,
        )

        try:
            repository.record_execution(
                EditMessageOperation(message=_message()),
                ExecutionResult(canonical_id="message-1"),
                new_state,
            )
        except sqlite3.IntegrityError as exc:
            assert "forced execution-log failure" in str(exc)
        else:
            raise AssertionError("Expected SQLite transaction failure.")

    with SQLiteStateRepository(path) as repository:
        assert repository.load_synchronization_state() == initial_state
        rows = repository._connection.execute(
            "SELECT canonical_id FROM execution_log ORDER BY id",
        ).fetchall()
        assert [row[0] for row in rows] == ["message-1"]


def test_sqlite_repository_persists_import_session(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    now = datetime.now(timezone.utc)
    session = ImportSession(
        started_at=now,
        updated_at=now,
        state=ImportState(payload={"cursor": "cursor-1", "page": 4}),
        paused=True,
        error="temporary failure",
    )

    with SQLiteStateRepository(path) as repository:
        repository.save_import_session(session)

    with SQLiteStateRepository(path) as repository:
        assert repository.load_import_session() == session


def test_sqlite_repository_starts_with_empty_state(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"

    with SQLiteStateRepository(path) as repository:
        assert repository.load_synchronization_state() == SynchronizationState()
        assert repository.load_import_session() is None


def test_sqlite_repository_records_execution_and_state_atomically(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    state = SynchronizationState(
        messages={"message-1": DestinationMessageRef("destination-1")},
        message_content_fingerprints={"message-1": "content"},
    )

    with SQLiteStateRepository(path) as repository:
        repository.record_execution(
            EditMessageOperation(message=_message()),
            ExecutionResult(canonical_id="message-1"),
            state,
        )

        rows = repository._connection.execute(
            "SELECT operation_type, canonical_id FROM execution_log",
        ).fetchall()

        assert [(row[0], row[1]) for row in rows] == [
            ("EditMessageOperation", "message-1"),
        ]


def _message():
    from archive_sync_engine.models import CanonicalMessage
    from archive_sync_engine.models.ids import ConversationId

    return CanonicalMessage(
        id=MessageId("message-1"),
        conversation_id=ConversationId("conversation-1"),
        identity_key=IdentityKey("identity-1"),
        content="hello",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

def test_sqlite_repository_accepts_valid_partial_message_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    state = SynchronizationState(
        messages={"message-1": DestinationMessageRef("destination-1")},
        message_content_fingerprints={"message-1": "content"},
        message_reactions={"message-1": ()},
    )

    with SQLiteStateRepository(path) as repository:
        repository.record_execution(
            EditMessageOperation(message=_message()),
            ExecutionResult(canonical_id="message-1"),
            state,
        )

    with SQLiteStateRepository(path) as repository:
        assert repository.load_synchronization_state() == state


def test_sqlite_repository_rejects_state_with_orphan_fingerprint(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    state = SynchronizationState(
        message_fingerprints={"message-1": "full"},
    )

    with SQLiteStateRepository(path) as repository:
        try:
            repository.record_execution(
                EditMessageOperation(message=_message()),
                ExecutionResult(canonical_id="message-1"),
                state,
            )
        except ValueError as exc:
            assert "message fingerprints" in str(exc)
        else:
            raise AssertionError("Expected invalid synchronization state.")

        assert repository.load_synchronization_state() == SynchronizationState()


def test_sqlite_repository_rejects_full_message_without_all_baselines(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    state = SynchronizationState(
        messages={"message-1": DestinationMessageRef("destination-1")},
        message_fingerprints={"message-1": "full"},
        message_content_fingerprints={"message-1": "content"},
        message_reactions={"message-1": ()},
        message_attachments={"message-1": ()},
        message_reply_to={"message-1": None},
    )

    with SQLiteStateRepository(path) as repository:
        try:
            repository.record_execution(
                EditMessageOperation(message=_message()),
                ExecutionResult(canonical_id="message-1"),
                state,
            )
        except ValueError as exc:
            assert "required component baselines" in str(exc)
        else:
            raise AssertionError("Expected invalid synchronization state.")


def test_sqlite_repository_rejects_dangling_reply_baseline(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    state = SynchronizationState(
        messages={"message-1": DestinationMessageRef("destination-1")},
        message_content_fingerprints={"message-1": "content"},
        message_reply_to={"message-1": MessageId("missing")},
    )

    with SQLiteStateRepository(path) as repository:
        try:
            repository.record_execution(
                EditMessageOperation(message=_message()),
                ExecutionResult(canonical_id="message-1"),
                state,
            )
        except ValueError as exc:
            assert "dangling message reply baselines" in str(exc)
        else:
            raise AssertionError("Expected invalid synchronization state.")


def test_sqlite_repository_rejects_invalid_persisted_state_on_load(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"

    with SQLiteStateRepository(path) as repository:
        repository._connection.execute(
            """
            INSERT INTO synchronization_state (id, payload)
            VALUES (1, ?)
            """,
            ('{"message_fingerprints":{"message-1":"full"}}',),
        )
        repository._connection.commit()

    with SQLiteStateRepository(path) as repository:
        try:
            repository.load_synchronization_state()
        except ValueError as exc:
            assert "message fingerprints" in str(exc)
        else:
            raise AssertionError("Expected invalid persisted state.")



def test_sqlite_repository_queries_execution_log_newest_first(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"

    with SQLiteStateRepository(path) as repository:
        repository.record_execution(
            EditMessageOperation(message=_message()),
            ExecutionResult(canonical_id="message-1"),
            SynchronizationState(),
        )
        repository.record_execution(
            EditMessageOperation(message=_message()),
            ExecutionResult(canonical_id="message-2"),
            SynchronizationState(),
        )

        entries = repository.query_execution_log()

        assert [entry.canonical_id for entry in entries] == [
            "message-2",
            "message-1",
        ]
        assert [entry.id for entry in entries] == [2, 1]


def test_sqlite_repository_queries_execution_log_with_filters_and_limit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"

    with SQLiteStateRepository(path) as repository:
        repository.record_execution(
            EditMessageOperation(message=_message()),
            ExecutionResult(canonical_id="message-1"),
            SynchronizationState(),
        )
        repository.record_execution(
            EditMessageOperation(message=_message()),
            ExecutionResult(canonical_id="message-1"),
            SynchronizationState(),
        )

        entries = repository.query_execution_log(
            canonical_id="message-1",
            operation_type="EditMessageOperation",
            limit=1,
        )

        assert len(entries) == 1
        assert entries[0].canonical_id == "message-1"
        assert entries[0].operation_type == "EditMessageOperation"


def test_sqlite_repository_query_reports_deletion_metadata(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"

    from archive_sync_engine.executor.result import DeletedEntityType

    with SQLiteStateRepository(path) as repository:
        repository.record_execution(
            EditMessageOperation(message=_message()),
            ExecutionResult(
                canonical_id="message-1",
                deleted=True,
                deleted_entity=DeletedEntityType.MESSAGE,
            ),
            SynchronizationState(),
        )

        entry = repository.query_execution_log()[0]

        assert entry.deleted is True
        assert entry.deleted_entity is DeletedEntityType.MESSAGE


def test_sqlite_repository_query_rejects_negative_limit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"

    with SQLiteStateRepository(path) as repository:
        try:
            repository.query_execution_log(limit=-1)
        except ValueError as exc:
            assert "limit" in str(exc)
        else:
            raise AssertionError("Expected negative limit to be rejected.")
