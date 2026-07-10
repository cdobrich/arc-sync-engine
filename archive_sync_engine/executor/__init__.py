"""
Synchronization operation executor.

The OperationExecutor consumes SyncOperations produced by the Planner and applies them to a DestinationAdapter.

The executor is responsible for performing synchronization work.

It must execute operations exactly in the order received.
"""

from .executor import OperationExecutor
from .result import ExecutionResult

__all__ = [
    "ExecutionResult",
    "OperationExecutor",
]
