import fcntl

from opencommune import cli, db
from opencommune.config import settings


def test_catalog_command_skips_concurrent_refresh(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    def unexpected_database_access():
        raise AssertionError("Concurrent refresh must not start database work")

    monkeypatch.setattr(db, "init_db", unexpected_database_access)
    with (tmp_path / "catalog.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cli.catalog_command()
    assert "already running" in capsys.readouterr().out
