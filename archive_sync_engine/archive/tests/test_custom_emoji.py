from __future__ import annotations

import hashlib

from archive_sync_engine.archive import Archive
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.models import CanonicalCustomEmoji
from archive_sync_engine.models.ids import EmojiId


def test_custom_emoji_round_trips_with_content_addressed_asset(tmp_path) -> None:
    paths = ArchivePaths(tmp_path / "archive")
    content = b"custom-emoji-image"
    digest = hashlib.sha256(content).hexdigest()
    emoji = CanonicalCustomEmoji(
        id=EmojiId("123"),
        name="mewheart",
        animated=False,
        content_type="image/png",
        size=len(content),
        sha256=digest,
    )

    with ArchiveWriter(paths) as writer:
        writer.upsert_custom_emoji(emoji)
        AssetStore(paths.root).put(content)
        writer.commit()

    with Archive(paths) as archive:
        assert tuple(archive.iter_custom_emojis()) == (emoji,)
        assert archive.asset_store.get(emoji.sha256) == content
