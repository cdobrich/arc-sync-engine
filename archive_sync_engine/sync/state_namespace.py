"""Stable namespaces for destination-specific synchronization state."""
from __future__ import annotations


def destination_state_namespace(adapter: str, scope: tuple[str, ...]) -> str:
    """Return the state namespace for one destination adapter/scope pair.

    Synchronization state contains destination-local object IDs.  Therefore
    state for two destination scopes must never share a namespace, even when
    both scopes use the same adapter and Archive.
    """
    normalized_adapter = str(adapter).strip().lower()
    if not normalized_adapter:
        raise ValueError("Destination adapter name must not be empty.")
    normalized_scope = tuple(str(value).strip() for value in scope)
    if not normalized_scope or any(not value for value in normalized_scope):
        raise ValueError("Destination scope must contain non-empty values.")
    return f"{normalized_adapter}:" + "/".join(normalized_scope)
