"""Registry for concrete source/destination synchronization combinations.

The generic adapter registry describes individual platform roles.  This
registry describes which concrete application runtimes currently know how to
combine a source adapter with a destination adapter.  Keeping the pairing
knowledge here prevents generic CLI code from accumulating platform-pair
conditionals and leaves room for combinations such as Fluxer -> Fluxer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SyncPairDescriptor:
    """Describe one supported source-to-destination runtime combination."""

    input_adapter: str
    destination_adapter: str
    description: str = ""

    def __post_init__(self) -> None:
        input_adapter = self.input_adapter.strip().lower()
        destination_adapter = self.destination_adapter.strip().lower()
        if not input_adapter:
            raise ValueError("Sync input adapter name must not be empty.")
        if not destination_adapter:
            raise ValueError("Sync destination adapter name must not be empty.")
        object.__setattr__(self, "input_adapter", input_adapter)
        object.__setattr__(self, "destination_adapter", destination_adapter)

    @property
    def key(self) -> tuple[str, str]:
        return self.input_adapter, self.destination_adapter


class SyncPairRegistry:
    """Register and resolve concrete source/destination runtime combinations."""

    def __init__(self, descriptors: tuple[SyncPairDescriptor, ...] = ()) -> None:
        self._descriptors: dict[tuple[str, str], SyncPairDescriptor] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: SyncPairDescriptor) -> None:
        if descriptor.key in self._descriptors:
            source, destination = descriptor.key
            raise ValueError(
                f"Sync adapter pair {source!r} -> {destination!r} is already registered."
            )
        self._descriptors[descriptor.key] = descriptor

    def get(self, input_adapter: str, destination_adapter: str) -> SyncPairDescriptor:
        key = (input_adapter.strip().lower(), destination_adapter.strip().lower())
        try:
            return self._descriptors[key]
        except KeyError as exc:
            available = ", ".join(
                f"{source}->{destination}"
                for source, destination in sorted(self._descriptors)
            ) or "none"
            raise ValueError(
                f"Unsupported sync adapter pair {input_adapter!r} -> "
                f"{destination_adapter!r}. Available pairs: {available}."
            ) from exc

    def list(self) -> tuple[SyncPairDescriptor, ...]:
        return tuple(self._descriptors[key] for key in sorted(self._descriptors))


def default_sync_pair_registry() -> SyncPairRegistry:
    """Return synchronization combinations implemented by the application."""
    return SyncPairRegistry(
        (
            SyncPairDescriptor(
                input_adapter="discord",
                destination_adapter="fluxer",
                description="Discord import synchronized to Fluxer.",
            ),
        )
    )
