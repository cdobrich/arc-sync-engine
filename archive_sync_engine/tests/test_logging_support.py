from pathlib import Path

from archive_sync_engine.logging_support import configure_logging


def test_configured_file_log_redacts_secrets(tmp_path: Path) -> None:
    log_path = tmp_path / "engine.log"
    logger = configure_logging(
        level="INFO",
        log_file=log_path,
        secrets=("super-secret",),
    )

    logger.info("Authentication failed for token super-secret")

    contents = log_path.read_text(encoding="utf-8")
    assert "super-secret" not in contents
    assert "[REDACTED]" in contents
    assert "INFO" in contents


def test_cli_supports_log_file_and_level(tmp_path: Path) -> None:
    from archive_sync_engine.cli import build_parser

    args = build_parser().parse_args(
        ["diagnostics", "--archive", str(tmp_path), "--log-level", "INFO", "--log-file", str(tmp_path / "engine.log")]
    )

    assert args.log_level == "INFO"
    assert args.log_file == tmp_path / "engine.log"
