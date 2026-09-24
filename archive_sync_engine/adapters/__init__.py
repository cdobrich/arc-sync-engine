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
from .capability_validation import AdapterCapabilityReport, validate_adapter_capabilities
from .registry import AdapterDescriptor, AdapterRegistry, default_adapter_registry
from .source_registry import SourceRuntimeRegistry, default_source_runtime_registry
from .destination_registry import DestinationRuntimeRegistry, default_destination_runtime_registry
from .destination_runtime_request import DestinationRuntimeRequest
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
from .fluxer_source import FluxerSourceAdapter
from .fluxer_source_runtime import FluxerSourceRuntime, FluxerSourceRuntimeConfig
from .fluxer import (
    FluxerCustomEmojiMapping,
    FluxerDestinationAdapter,
    FluxerIdentityMapping,
)
from .fluxer_runtime import FluxerClientConfig, FluxerHttpClientFactory
from .references import (
    DestinationAttachmentRef,
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)

__all__ = [
    "AdapterCapabilityReport",
    "AdapterDescriptor",
    "AdapterError",
    "AdapterRegistry",
    "validate_adapter_capabilities",
    "AuthenticationError",
    "default_adapter_registry",
    "AuthorizationError",
    "CapabilityError",
    "ConflictError",
    "DestinationAdapter",
    "DestinationRuntimeRegistry",
    "DestinationRuntimeRequest",
    "default_destination_runtime_registry",
    "DestinationAttachmentRef",
    "DestinationCapabilities",
    "DestinationConversationRef",
    "DiscordSourceAdapter",
    "FluxerSourceAdapter",
    "FluxerSourceRuntime",
    "FluxerSourceRuntimeConfig",
    "FluxerClientConfig",
    "FluxerCustomEmojiMapping",
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
