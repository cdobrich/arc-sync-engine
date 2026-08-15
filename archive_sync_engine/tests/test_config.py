from __future__ import annotations

from pathlib import Path

import pytest

from archive_sync_engine.config import ConfigurationError, load_setup_configuration


def _write_tokens(tmp_path: Path) -> None:
    (tmp_path / "discord.token").write_text("discord-secret\n", encoding="utf-8")
    (tmp_path / "fluxer.token").write_text("fluxer-secret\n", encoding="utf-8")
    (tmp_path / "bob.key").write_text("bob-secret\n", encoding="utf-8")


def test_load_yaml_setup_uses_stable_discord_external_ids(tmp_path: Path) -> None:
    _write_tokens(tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token_file: discord.token
  guild_id: 123456789
fluxer:
  token_file: fluxer.token
  server_id: fluxer-server
delays:
  between_messages_seconds: 0.5
  between_channels_seconds: 5.0
user_mappings:
  discord:
    "123456789012345678":
      fluxer_username: BobsFluxerAccount#0909
      fluxer_auth_key_file: bob.key
""",
        encoding="utf-8",
    )

    setup = load_setup_configuration(config)

    assert setup.discord_guild_ids == (123456789,)
    assert setup.resolve_discord_token() == "discord-secret"
    assert setup.resolve_fluxer_token() == "fluxer-secret"
    assert setup.resolved_archive_path() == (tmp_path / "archive").resolve()
    mapping = setup.resolve_identity_mappings()[0]
    assert mapping.username == "discord:user:123456789012345678"
    assert mapping.fluxer_auth_key == "bob-secret"
    assert mapping.fluxer_username == "BobsFluxerAccount#0909"


def test_load_yaml_setup_allows_mixed_inline_and_file_auth_keys(tmp_path: Path) -> None:
    (tmp_path / "discord.token").write_text("discord\n", encoding="utf-8")
    (tmp_path / "fluxer.token").write_text("fluxer\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token_file: discord.token
  guild_id: 123
fluxer:
  token_file: fluxer.token
  server_id: 456
user_mappings:
  discord:
    "1":
      fluxer_username: One#0001
      fluxer_auth_key: inline-secret
    "2":
      fluxer_username: Two#0002
      fluxer_auth_key_file: second.key
""",
        encoding="utf-8",
    )
    (tmp_path / "second.key").write_text("file-secret\n", encoding="utf-8")

    setup = load_setup_configuration(config)
    mappings = setup.resolve_identity_mappings()

    assert [(m.username, m.fluxer_auth_key) for m in mappings] == [
        ("discord:user:1", "inline-secret"),
        ("discord:user:2", "file-secret"),
    ]


def test_load_yaml_setup_rejects_display_name_identity_keys(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord
  guild_id: 123
fluxer:
  token: fluxer
  server_id: 456
user_mappings:
  discord:
    "Bob#1111":
      fluxer_username: Bob#0001
      fluxer_auth_key: secret
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="stable numeric Discord user IDs"):
        load_setup_configuration(config)


def test_load_yaml_setup_rejects_two_secret_sources(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord
  token_file: other
  guild_id: 123
fluxer:
  token: fluxer
  server_id: 456
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="discord.*token"):
        load_setup_configuration(config)


def test_load_yaml_setup_supports_per_user_discord_auth_inline_and_file(tmp_path: Path) -> None:
    (tmp_path / "discord.token").write_text("discord\n", encoding="utf-8")
    (tmp_path / "fluxer.token").write_text("fluxer\n", encoding="utf-8")
    (tmp_path / "alice-discord.key").write_text("alice-discord-secret\n", encoding="utf-8")
    (tmp_path / "bob-fluxer.key").write_text("bob-fluxer-secret\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token_file: discord.token
  guild_id: 123
fluxer:
  token_file: fluxer.token
  server_id: 456
user_mappings:
  discord:
    "123456789012345678":
      discord_auth_key: alice-discord-inline
      fluxer_username: AliceOnFluxer#1136
      fluxer_auth_key: alice-fluxer-inline
    "234567890123456789":
      discord_auth_key_file: alice-discord.key
      fluxer_username: BobsFluxerAccount#0909
      fluxer_auth_key_file: bob-fluxer.key
""",
        encoding="utf-8",
    )

    setup = load_setup_configuration(config)

    assert setup.resolve_discord_user_auth() == {
        "123456789012345678": "alice-discord-inline",
        "234567890123456789": "alice-discord-secret",
    }
    mappings = setup.resolve_identity_mappings()
    assert [(m.username, m.fluxer_auth_key, m.fluxer_username) for m in mappings] == [
        ("discord:user:123456789012345678", "alice-fluxer-inline", "AliceOnFluxer#1136"),
        ("discord:user:234567890123456789", "bob-fluxer-secret", "BobsFluxerAccount#0909"),
    ]


def test_load_yaml_setup_supports_stable_fluxer_user_ids(tmp_path: Path) -> None:
    (tmp_path / "discord.token").write_text("discord\n", encoding="utf-8")
    (tmp_path / "fluxer.token").write_text("fluxer\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token_file: discord.token
  guild_id: 123
fluxer:
  token_file: fluxer.token
  server_id: 456
user_mappings:
  discord:
    "123456789012345678":
      fluxer_username: BobsFluxerAccount#0909
      fluxer_auth_key: bob-fluxer
  fluxer:
    "1375567890027713164":
      fluxer_username: BobsFluxerAccount#0909
      fluxer_auth_key_file: bob-fluxer.key
    "1613177200987655731":
      fluxer_username: AliceOnFluxer#1136
      fluxer_auth_key: alice-fluxer
""",
        encoding="utf-8",
    )
    (tmp_path / "bob-fluxer.key").write_text("bob-fluxer-file\n", encoding="utf-8")

    setup = load_setup_configuration(config)

    assert [(m.fluxer_user_id, m.fluxer_username) for m in setup.fluxer_user_mappings] == [
        ("1375567890027713164", "BobsFluxerAccount#0909"),
        ("1613177200987655731", "AliceOnFluxer#1136"),
    ]
    assert setup.fluxer_user_mappings[0].fluxer_auth.resolve(
        base_dir=setup.config_directory, label="test"
    ) == "bob-fluxer-file"


def test_load_yaml_setup_rejects_fluxer_username_without_discriminator(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord
  guild_id: 123
fluxer:
  token: fluxer
  server_id: 456
user_mappings:
  discord:
    "1":
      fluxer_username: BobsFluxerAccount
      fluxer_auth_key: secret
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="#.*four digits"):
        load_setup_configuration(config)


def test_load_yaml_setup_rejects_two_per_user_discord_secret_sources(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord
  guild_id: 123
fluxer:
  token: fluxer
  server_id: 456
user_mappings:
  discord:
    "1":
      discord_auth_key: inline
      discord_auth_key_file: other
      fluxer_username: Bob#0001
      fluxer_auth_key: secret
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="discord_auth_key"):
        load_setup_configuration(config)


def test_setup_resolve_credentials_resolves_all_secret_sources(tmp_path: Path) -> None:
    (tmp_path / "discord.token").write_text("discord\n", encoding="utf-8")
    (tmp_path / "fluxer.token").write_text("fluxer\n", encoding="utf-8")
    (tmp_path / "discord-user.key").write_text("discord-user\n", encoding="utf-8")
    (tmp_path / "fluxer-user.key").write_text("fluxer-user\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token_file: discord.token
  guild_id: 123
fluxer:
  token_file: fluxer.token
  server_id: 456
user_mappings:
  discord:
    "1":
      discord_auth_key_file: discord-user.key
      fluxer_username: Bob#0001
      fluxer_auth_key: discord-fluxer
  fluxer:
    "2":
      fluxer_username: Alice#0002
      fluxer_auth_key_file: fluxer-user.key
""",
        encoding="utf-8",
    )

    setup = load_setup_configuration(config)
    credentials = setup.resolve_credentials()

    assert credentials.discord_token == "discord"
    assert credentials.fluxer_token == "fluxer"
    assert dict(credentials.discord_user_auth) == {"1": "discord-user"}
    assert dict(credentials.fluxer_user_auth) == {"2": "fluxer-user"}
    assert credentials.identity_mappings[0].fluxer_auth_key == "discord-fluxer"


def test_setup_resolve_credentials_fails_before_runtime_for_missing_mapping_secret_file(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord
  guild_id: 123
fluxer:
  token: fluxer
  server_id: 456
user_mappings:
  fluxer:
    "2":
      fluxer_username: Alice#0002
      fluxer_auth_key_file: missing.key
""",
        encoding="utf-8",
    )

    setup = load_setup_configuration(config)

    with pytest.raises(ConfigurationError, match="Fluxer auth for Fluxer user 2"):
        setup.resolve_credentials()
