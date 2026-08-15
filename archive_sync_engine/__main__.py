"""Run Archive-Sync Engine as ``python -m archive_sync_engine``."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
