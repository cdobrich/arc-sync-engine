"""
Platform adapter interfaces.

Adapters are the only components that understand platform-specific
concepts such as Discord, Fluxer, or future messaging services.

The Archive Engine communicates exclusively through the interfaces
defined in this package. Adapters are responsible for translating
between platform-specific representations and the canonical models.

Two primary adapter roles exist:

    • SourceAdapter
        Reads conversations, messages, identities,
        reactions, and assets from a source platform.

    • DestinationAdapter
        Creates and updates conversations, messages,
        reactions, and assets on a destination platform.

Adapters contain no synchronization logic.
Planning, reconciliation, and execution remain the responsibility
of the Archive Engine.
"""

from .capabilities import DestinationCapabilities
from .registry import AdapterDescriptor, AdapterRegistry, default_adapter_registry
from .source_registry import SourceRuntimeRegistry, default_source_runtime_registry
from .source_runtime_request import SourceRuntimeRequest
from .sync_registry import SyncPairDescriptor, SyncPairRegistry, default_sync_pair_registry
from .destination import DestinationAdapter
from .exceptions import (
    AdapterError,
    AuthenticationError,
    AuthorizationError,
    CapabilityError,
    ConflictError,
    NotFoundError,
    RateLimitError,
)
from .source import SourceAdapter
from .discord import DiscordSourceAdapter
from .fluxer import FluxerDestinationAdapter, FluxerIdentityMapping
from .fluxer_runtime import FluxerClientConfig, FluxerHttpClientFactory
from .references import (
    DestinationAttachmentRef,
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)

__all__ = [
    "AdapterDescriptor",
    "AdapterError",
    "AdapterRegistry",
    "AuthenticationError",
    "default_adapter_registry",
    "AuthorizationError",
    "CapabilityError",
    "ConflictError",
    "DestinationAdapter",
    "DestinationAttachmentRef",
    "DestinationCapabilities",
    "DestinationConversationRef",
    "DiscordSourceAdapter",
    "FluxerClientConfig",
    "FluxerDestinationAdapter",
    "FluxerHttpClientFactory",
    "FluxerIdentityMapping",
    "DestinationIdentityRef",
    "DestinationMessageRef",
    "NotFoundError",
    "RateLimitError",
    "SourceAdapter",
    "SourceRuntimeRegistry",
    "SourceRuntimeRequest",
    "default_source_runtime_registry",
    "SyncPairDescriptor",
    "SyncPairRegistry",
    "default_sync_pair_registry",
]
