"""
Executor-specific errors.
"""

from __future__ import annotations


class ExecutionError(RuntimeError):
    """
    Base exception for executor failures.
    """


class MissingDestinationReferenceError(
    ExecutionError,
):
    """
    Raised when an operation requires a destination reference that has
    not been produced during the current execution.
    """

    def __init__(
        self,
        entity_type: str,
        canonical_id: object,
    ) -> None:
        super().__init__(
            f"No destination {entity_type} reference exists for "
            f"canonical ID {canonical_id!s}."
        )

        self.entity_type = entity_type
        self.canonical_id = canonical_id