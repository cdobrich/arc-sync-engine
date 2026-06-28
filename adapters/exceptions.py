"""
Common adapter exceptions.

Platform adapters translate platform-specific exceptions into the
exceptions defined in this module. This prevents the Archive Engine
from depending on implementation details of any particular platform.

For example:

    discord.HTTPException
        ↓
    RateLimitError

or

    fluxer.AuthenticationFailed
        ↓
    AuthenticationError
"""


class AdapterError(Exception):
    """
    Base class for all adapter-related exceptions.
    """


class AuthenticationError(AdapterError):
    """
    Raised when an adapter cannot authenticate with the platform.
    """


class AuthorizationError(AdapterError):
    """
    Raised when authentication succeeds but the requested operation
    is not permitted.
    """


class CapabilityError(AdapterError):
    """
    Raised when an operation is requested that the destination
    platform does not support.
    """


class RateLimitError(AdapterError):
    """
    Raised when the platform requests that operations be slowed or
    temporarily paused.
    """


class NotFoundError(AdapterError):
    """
    Raised when a requested platform resource no longer exists.
    """


class ConflictError(AdapterError):
    """
    Raised when the requested operation conflicts with the current
    platform state.

    Examples include optimistic concurrency failures or attempting
    to create a resource that already exists.
    """

