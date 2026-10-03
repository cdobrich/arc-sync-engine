"""
Import pipeline.

The import pipeline is responsible for acquiring canonical information
from a SourceAdapter and populating the Archive.

Import is intentionally independent from synchronization.

The Archive is the boundary between acquisition and synchronization.

Import Pipeline

    SourceAdapter
        │
        ▼
    Importer
        │
        ├── creates ImportOperations
        ├── executes ImportOperations
        └── reports progress
        │
        ▼
    ImportCoordinator
        │
        ├── pause
        ├── resume
        ├── checkpoint
        ├── retry
        └── persist session state
        │
        ▼
    Archive / AssetStore / StateRepository
"""

from .session import ImportSession
from .state import ImportState
from .progress import ImportProgress
from .discovery_state import DiscoveryPhase, DiscoveryState
from .traversal import ImportTraversalMode

__all__ = [
    "ImportSession",
    "ImportState",
    "ImportProgress",
    "DiscoveryPhase",
    "DiscoveryState",
    "ImportTraversalMode",
]
