"""
Export pipeline.

The export pipeline reads canonical information from an Archive and
reproduces it through a DestinationAdapter.
"""

from .canonical_exporter import CanonicalExporter

__all__ = [
    "CanonicalExporter",
]