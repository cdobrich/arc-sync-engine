"""Durable synchronization-state paths scoped to one destination target."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path


def synchronization_state_path(
    archive_root: Path,
    *,
    adapter: str,
    scope: Sequence[str],
) -> Path:
    """Return the durable state database path for one adapter/scope target.

    Synchronization state contains destination-local references and therefore
    must never be shared by two destination scopes.  The digest keeps paths
    filesystem-safe even when adapters expose multiple or unusual scope
    components.
    """
    if not adapter:
        raise ValueError("Synchronization adapter must not be empty.")
    normalized_scope = tuple(str(value) for value in scope)
    if not normalized_scope or any(not value for value in normalized_scope):
        raise ValueError("Synchronization scope must contain non-empty values.")

    identity = "\0".join((adapter, *normalized_scope)).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:24]
    return (
        Path(archive_root)
        / "synchronization"
        / adapter
        / f"{digest}.sqlite"
    )
