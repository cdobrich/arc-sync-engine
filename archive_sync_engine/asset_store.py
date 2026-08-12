"""
Content-addressed attachment storage.

AssetStore owns the binary contents of canonical attachments.

The canonical attachment model stores metadata, including the SHA-256
digest. AssetStore stores the corresponding bytes in a deterministic
content-addressed filesystem layout.

For a SHA-256 digest:

    <root>/assets/<first-two>/<next-two>/<sha256>

For example:

    assets/
        ab/
            cd/
                abcdef1234...

The SHA-256 digest is the identity of the stored content.

AssetStore does not know about SourceAdapters, messages, conversations,
or database persistence.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from archive_sync_engine.models import CanonicalAttachment


class AssetStore:
    """
    Persistent content-addressed storage for archive assets.
    """

    _ASSET_DIRECTORY = "assets"

    def __init__(
        self,
        root: Path,
    ) -> None:
        """
        Create an AssetStore rooted at ``root``.
        """

        self._root = root
        self._assets = root / self._ASSET_DIRECTORY

        self._assets.mkdir(
            parents=True,
            exist_ok=True,
        )

    #
    # Paths
    #

    def path_for_sha256(
        self,
        sha256: str,
    ) -> Path:
        """
        Return the content-addressed path for a SHA-256 digest.
        """

        self._validate_sha256(
            sha256,
        )

        return (
            self._assets
            / sha256[:2]
            / sha256[2:4]
            / sha256
        )

    #
    # Storage
    #

    def put(
            self,
            content: bytes,
    ) -> str:
        """
        Store bytes and return their SHA-256 digest.

        Existing content with the same digest is reused.
        """

        sha256 = hashlib.sha256(
            content,
        ).hexdigest()

        path = self.path_for_sha256(
            sha256,
        )

        if path.exists():
            return sha256

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = path.with_name(
            f".{path.name}.tmp",
        )

        try:
            temporary.write_bytes(
                content,
            )

            if path.exists():
                return sha256

            temporary.rename(
                path,
            )

        finally:
            temporary.unlink(
                missing_ok=True,
            )

        return sha256

    def put_attachment(
            self,
            attachment: CanonicalAttachment,
            content: bytes,
    ) -> None:
        """
        Store attachment bytes and verify their canonical SHA-256 digest.
        """

        if len(content) != attachment.size:
            raise ValueError(
                "Attachment content size does not match "
                f"canonical attachment {attachment.id}: "
                f"expected {attachment.size}, "
                f"got {len(content)}."
            )

        actual_sha256 = hashlib.sha256(
            content,
        ).hexdigest()

        if actual_sha256 != attachment.sha256:
            raise ValueError(
                "Attachment content SHA-256 does not match "
                f"canonical attachment {attachment.id}: "
                f"expected {attachment.sha256}, "
                f"got {actual_sha256}."
            )

        self.put(
            content,
        )

    #
    # Retrieval
    #

    def exists(
        self,
        sha256: str,
    ) -> bool:
        """
        Return whether content for the given SHA-256 digest exists.
        """

        return self.path_for_sha256(
            sha256,
        ).is_file()

    def get(
        self,
        sha256: str,
    ) -> bytes:
        """
        Read content identified by SHA-256.

        Raises FileNotFoundError when the asset is not present.
        """

        return self.path_for_sha256(
            sha256,
        ).read_bytes()

    #
    # Validation
    #

    @staticmethod
    def _validate_sha256(
        sha256: str,
    ) -> None:
        """
        Validate a SHA-256 hexadecimal digest.
        """

        if len(sha256) != 64:
            raise ValueError(
                "SHA-256 digest must contain exactly 64 "
                "hexadecimal characters."
            )

        try:
            int(
                sha256,
                16,
            )
        except ValueError as exc:
            raise ValueError(
                "SHA-256 digest must contain only "
                "hexadecimal characters."
            ) from exc