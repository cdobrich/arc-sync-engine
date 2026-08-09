"""
Canonical synchronization fingerprints.

A synchronization fingerprint represents the canonical state that has
actually been synchronized to a destination.

Fingerprints are deterministic and independent of destination-platform
implementations.

Destination routing metadata is excluded where it is not part of the
canonical source state being synchronized.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
    CanonicalReaction,
)


def canonical_fingerprint(
    value: object,
) -> str:
    """
    Return a deterministic fingerprint for a canonical entity.

    The fingerprint changes when synchronization-relevant canonical
    state changes.

    CanonicalMessage.destination_id is intentionally excluded because it
    represents engine routing metadata rather than source message state.
    """

    normalized = _normalize(
        value,
    )

    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    ).encode(
        "utf-8",
    )

    return hashlib.sha256(
        encoded,
    ).hexdigest()


def canonical_message_content_fingerprint(
    message: CanonicalMessage,
) -> str:
    """
    Return a fingerprint for message state excluding attachments,
    reactions, and pin state.

    Message content is reconciled through EditMessageOperation. Attachments,
    reactions, and pin state are reconciled by their dedicated operations.
    """

    normalized = _normalize(
        message,
    )

    normalized.pop(
        "attachments",
        None,
    )
    normalized.pop(
        "reactions",
        None,
    )
    normalized.pop(
        "pinned",
        None,
    )

    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    ).encode(
        "utf-8",
    )

    return hashlib.sha256(
        encoded,
    ).hexdigest()


def _normalize(
    value: object,
) -> Any:
    """
    Convert canonical values into deterministic JSON-compatible data.
    """

    if isinstance(
        value,
        datetime,
    ):
        return value.isoformat()

    if isinstance(
        value,
        Enum,
    ):
        return value.value

    if isinstance(
        value,
        (str, int, float, bool),
    ) or value is None:
        return value

    if isinstance(
        value,
        (CanonicalAttachment, CanonicalReaction),
    ):
        return {
            field.name: _normalize(
                getattr(
                    value,
                    field.name,
                ),
            )
            for field in fields(
                value,
            )
        }

    if isinstance(
        value,
        CanonicalIdentity,
    ):
        return {
            field.name: _normalize(
                getattr(
                    value,
                    field.name,
                ),
            )
            for field in fields(
                value,
            )
        }

    if isinstance(
        value,
        CanonicalConversation,
    ):
        return {
            field.name: _normalize(
                getattr(
                    value,
                    field.name,
                ),
            )
            for field in fields(
                value,
            )
        }

    if isinstance(
        value,
        CanonicalMessage,
    ):
        return {
            field.name: _normalize(
                getattr(
                    value,
                    field.name,
                ),
            )
            for field in fields(
                value,
            )
            if field.name != "destination_id"
        }

    if is_dataclass(
        value,
    ):
        return {
            field.name: _normalize(
                getattr(
                    value,
                    field.name,
                ),
            )
            for field in fields(
                value,
            )
        }

    if isinstance(
        value,
        dict,
    ):
        return {
            str(key): _normalize(
                item,
            )
            for key, item in value.items()
        }

    if isinstance(
        value,
        (tuple, list),
    ):
        return [
            _normalize(
                item,
            )
            for item in value
        ]

    if isinstance(
        value,
        set,
    ):
        return sorted(
            (
                _normalize(
                    item,
                )
                for item in value
            ),
            key=repr,
        )

    if isinstance(
        value,
        str,
    ):
        return value

    return str(
        value,
    )