import pytest

from opencommune.config import Settings


def test_raw_override_leaves_database_and_processed_data_unchanged(tmp_path):
    raw = tmp_path / "volume" / "raw"
    raw.mkdir(parents=True)
    config = Settings(
        _env_file=None,
        data_dir=tmp_path / "local",
        raw_data_dir=raw,
        database_url="sqlite:///local.db",
    )
    config.ensure_dirs()
    assert config.raw_dir == raw
    assert config.parsed_dir == tmp_path / "local" / "parsed"
    assert config.database_url == "sqlite:///local.db"
    assert not (tmp_path / "local" / "raw").exists()


def test_missing_external_directory_fails_instead_of_creating_an_empty_archive(tmp_path):
    external = tmp_path / "unmounted" / "raw"
    config = Settings(_env_file=None, data_dir=tmp_path / "local", raw_data_dir=external)
    with pytest.raises(FileNotFoundError, match="RAW_DATA_DIR"):
        config.ensure_dirs()
    assert not external.exists()


def test_default_raw_directory_still_follows_data_dir(tmp_path):
    config = Settings(_env_file=None, data_dir=tmp_path, raw_data_dir=None)
    assert config.raw_dir == tmp_path / "raw"
