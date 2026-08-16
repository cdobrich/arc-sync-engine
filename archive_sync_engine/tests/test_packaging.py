from __future__ import annotations

import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_project_metadata() -> dict:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]


def test_project_metadata_defines_installable_cli() -> None:
    metadata = _load_project_metadata()

    assert metadata["name"] == "archive-sync-engine"
    assert metadata["requires-python"] == ">=3.11"
    assert metadata["dependencies"] == ["PyYAML>=6.0,<7"]
    assert metadata["scripts"] == {
        "archive-sync-engine": "archive_sync_engine.cli:main",
    }


def test_project_version_is_derived_from_runtime_metadata() -> None:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "dynamic = [\"version\"]" in pyproject
    assert 'version = {attr = "archive_sync_engine.__about__.__version__"}' in pyproject


def test_platform_adapter_dependencies_are_optional() -> None:
    metadata = _load_project_metadata()
    extras = metadata["optional-dependencies"]

    assert extras["discord"] == ["discord.py>=2.7,<3"]
    assert extras["fluxer"] == ["fluxer.py>=0.4,<0.5"]
    assert extras["sync"] == [
        "discord.py>=2.7,<3",
        "fluxer.py>=0.4,<0.5",
    ]


def test_configuration_template_is_included_in_source_manifest() -> None:
    manifest = (PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include config-example.yaml" in manifest
    assert (PROJECT_ROOT / "config-example.yaml").is_file()


def test_package_data_installs_configuration_template() -> None:
    metadata = _load_project_metadata()
    assert metadata["scripts"]["archive-sync-engine"]
    assert metadata["name"] == "archive-sync-engine"

    data_files = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["tool"]["setuptools"]["data-files"]
    assert data_files["share/archive-sync-engine"] == ["config-example.yaml"]
