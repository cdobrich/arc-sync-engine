"""Canonical import traversal modes."""

from __future__ import annotations

from enum import Enum


class ImportTraversalMode(str, Enum):
    """Traversal semantics represented by an importer checkpoint."""

    FULL = "full"
    INCREMENTAL = "incremental"
