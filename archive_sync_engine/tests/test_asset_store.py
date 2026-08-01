from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.models.attachment import CanonicalAttachment
from archive_sync_engine.models.ids import AttachmentId


def test_asset_store_put_round_trip(
    tmp_path: Path,
) -> None:
    store = AssetStore(
        tmp_path,
    )

    content = b"archive attachment content"

    sha256 = store.put(
        content,
    )

    assert sha256 == hashlib.sha256(
        content,
    ).hexdigest()

    assert store.exists(
        sha256,
    )

    assert store.get(
        sha256,
    ) == content


def test_asset_store_uses_content_addressed_path(
    tmp_path: Path,
) -> None:
    store = AssetStore(
        tmp_path,
    )

    content = b"content-addressed attachment"

    sha256 = hashlib.sha256(
        content,
    ).hexdigest()

    store.put(
        content,
    )

    assert store.path_for_sha256(
        sha256,
    ) == (
        tmp_path
        / "assets"
        / sha256[:2]
        / sha256[2:4]
        / sha256
    )


def test_asset_store_reuses_existing_content(
    tmp_path: Path,
) -> None:
    store = AssetStore(
        tmp_path,
    )

    content = b"same attachment"

    first = store.put(
        content,
    )

    second = store.put(
        content,
    )

    assert first == second

    assert store.get(
        first,
    ) == content


def test_asset_store_put_attachment_verifies_sha256(
    tmp_path: Path,
) -> None:
    store = AssetStore(
        tmp_path,
    )

    content = b"verified attachment"

    sha256 = hashlib.sha256(
        content,
    ).hexdigest()

    attachment = CanonicalAttachment(
        id=AttachmentId(
            "attachment-001",
        ),
        filename="example.txt",
        content_type="text/plain",
        size=len(content),
        sha256=sha256,
    )

    store.put_attachment(
        attachment,
        content,
    )

    assert store.get(
        sha256,
    ) == content


def test_asset_store_rejects_digest_mismatch(
    tmp_path: Path,
) -> None:
    store = AssetStore(
        tmp_path,
    )

    attachment = CanonicalAttachment(
        id=AttachmentId(
            "attachment-001",
        ),
        filename="example.txt",
        content_type="text/plain",
        size=7,
        sha256=hashlib.sha256(
            b"expected",
        ).hexdigest(),
    )

    with pytest.raises(
        ValueError,
        match="SHA-256 does not match",
    ):
        store.put_attachment(
            attachment,
            b"actual",
        )


def test_asset_store_rejects_invalid_sha256(
    tmp_path: Path,
) -> None:
    store = AssetStore(
        tmp_path,
    )

    with pytest.raises(
        ValueError,
        match="64 hexadecimal",
    ):
        store.path_for_sha256(
            "invalid",
        )