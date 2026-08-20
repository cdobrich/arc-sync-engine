from __future__ import annotations

import hashlib

from archive_sync_engine.adapters.source import SourceAdapter
from archive_sync_engine.archive import Archive
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.importer.canonical_importer import CanonicalImporter
from archive_sync_engine.models import CanonicalCustomEmoji
from archive_sync_engine.models.ids import EmojiId
from archive_sync_engine.archive.writer import ArchiveWriter


class EmojiSource(SourceAdapter):
    @property
    def name(self):
        return "emoji-source"

    def iter_conversations(self):
        return ()

    def iter_identities(self):
        return ()

    def iter_custom_emojis(self):
        content = b"emoji-bytes"
        yield CanonicalCustomEmoji(
            id=EmojiId("emoji-1"), name="mewheart", animated=False,
            content_type="image/png", size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )

    def custom_emoji_bytes(self, emoji):
        return b"emoji-bytes"

    def iter_messages(self, conversation):
        return ()

    def attachment_bytes(self, attachment):
        raise AssertionError("not used")


def test_import_persists_custom_emoji_asset(tmp_path) -> None:
    paths = ArchivePaths(tmp_path / "archive")
    from archive_sync_engine.asset_store import AssetStore
    with ArchiveWriter(paths) as writer:
        CanonicalImporter().import_source(
            EmojiSource(),
            writer,
            AssetStore(paths.root),
        )
        writer.commit()

    with Archive(paths) as archive:
        emojis = tuple(archive.iter_custom_emojis())
        assert len(emojis) == 1
        assert archive.asset_store.get(emojis[0].sha256) == b"emoji-bytes"
