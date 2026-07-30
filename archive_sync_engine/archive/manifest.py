"""
Metadata describing an Archive Package.

This metadata describes the package itself rather
than the archived content stored inside
archive.sqlite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

ARCHIVE_FORMAT_VERSION = 1


@dataclass(frozen=True, slots=True)
class ArchiveManifest:
    """
    Metadata describing an Archive Package.

    This describes the package itself rather than the
    archived content stored inside archive.sqlite.
    """

    archive_engine_version: str
    created_at: datetime

    archive_format_version: int = ARCHIVE_FORMAT_VERSION

    database_filename: str = "archive.sqlite"
    attachments_directory: str = "attachments"
    hash_algorithm: str = "sha256"


    def __post_init__(self) -> None:
        """
        Validate manifest invariants.
        """

        #
        # created_at must be timezone-aware.
        #

        if (
            self.created_at.tzinfo is None
            or self.created_at.utcoffset() is None
        ):
            raise ValueError(
                "created_at must be timezone-aware."
            )

        #
        # Format version.
        #

        if self.archive_format_version < 1:

            raise ValueError(
                "archive_format_version "
                "must be >= 1."
            )

        #
        # Required strings.
        #

        if not self.archive_engine_version:

            raise ValueError(
                "archive_engine_version "
                "cannot be empty."
            )

        if not self.database_filename:

            raise ValueError(
                "database_filename "
                "cannot be empty."
            )

        if not self.attachments_directory:

            raise ValueError(
                "attachments_directory "
                "cannot be empty."
            )

        if not self.hash_algorithm:

            raise ValueError(
                "hash_algorithm "
                "cannot be empty."
            )

    def to_json_dict(
        self,
    ) -> dict[str, object]:

        return {
            "archive_format_version":
                self.archive_format_version,

            "archive_engine_version":
                self.archive_engine_version,

            "created_at":
                self.created_at.isoformat(),

            "database_filename":
                self.database_filename,

            "attachments_directory":
                self.attachments_directory,

            "hash_algorithm":
                self.hash_algorithm,
        }

    @classmethod
    def from_json_dict(
            cls,
            data: dict[str, object],
    ) -> "ArchiveManifest":
        """
        Construct an ArchiveManifest from JSON.
        """

        created_at = datetime.fromisoformat(
            cls._require_str(
                data,
                "created_at",
            )
        )

        return cls(
            archive_engine_version=cls._require_str(
                data,
                "archive_engine_version",
            ),

            created_at=created_at,

            archive_format_version=cls._optional_int(
                data,
                "archive_format_version",
                ARCHIVE_FORMAT_VERSION,
            ),

            database_filename=cls._optional_str(
                data,
                "database_filename",
                "archive.sqlite",
            ),

            attachments_directory=cls._optional_str(
                data,
                "attachments_directory",
                "attachments",
            ),

            hash_algorithm=cls._optional_str(
                data,
                "hash_algorithm",
                "sha256",
            ),
        )


    def _require_str(
            data: dict[str, object],
            key: str,
    ) -> str:
        """
        Retrieve a required string value.
        """

        value = data.get(key)

        if not isinstance(
                value,
                str,
        ):
            raise TypeError(
                f"{key!r} must be a string."
            )

        return value

    def _require_int(
            data: dict[str, object],
            key: str,
    ) -> int:
        """
        Retrieve a required integer value.
        """

        value = data.get(key)

        if not isinstance(
                value,
                int,
        ):
            raise TypeError(
                f"{key!r} must be an integer."
            )

        return value

    def _optional_str(
            data: dict[str, object],
            key: str,
            default: str,
    ) -> str:
        """
        Retrieve an optional string value.
        """

        value = data.get(
            key,
            default,
        )

        if not isinstance(
                value,
                str,
        ):
            raise TypeError(
                f"{key!r} must be a string."
            )

        return value

    def _optional_int(
            data: dict[str, object],
            key: str,
            default: int,
    ) -> int:
        """
        Retrieve an optional integer value.
        """

        value = data.get(
            key,
            default,
        )

        if not isinstance(
                value,
                int,
        ):
            raise TypeError(
                f"{key!r} must be an integer."
            )

        return value