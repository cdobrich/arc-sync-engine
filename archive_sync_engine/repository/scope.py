"""Helpers for isolating durable synchronization state by destination scope."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


def synchronization_state_path(
    archive_root: str | Path,
    *,
    adapter: str,
    scope: tuple[str, ...],
) -> Path:
    """Return the durable state database for one destination scope.

    Synchronization mappings are destination-local.  A single Archive may be
    exported to many servers, so their destination references and baselines
    must never share one state snapshot.
    """
    if not adapter.strip():
        raise ValueError("Destination adapter must not be empty.")
    if not scope or any(not value.strip() for value in scope):
        raise ValueError("Destination scope must contain non-empty values.")

    normalized_adapter = re.sub(r"[^A-Za-z0-9_.-]+", "_", adapter.strip().lower())
    scope_key = "\x1f".join(value.strip() for value in scope)
    digest = hashlib.sha256(scope_key.encode("utf-8")).hexdigest()[:16]
    label = "-".join(
        re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
        for value in scope
    )
    if len(label) > 80:
        label = label[:80]
    return Path(archive_root) / f"synchronization.{normalized_adapter}.{label}.{digest}.sqlite"


def synchronization_state_paths(archive_root: str | Path) -> tuple[Path, ...]:
    """Return all synchronization-state databases currently present."""
    root = Path(archive_root)
    candidates = []
    legacy = root / "synchronization.sqlite"
    if legacy.is_file():
        candidates.append(legacy)
    candidates.extend(sorted(root.glob("synchronization.*.sqlite")))
    return tuple(dict.fromkeys(candidates))
