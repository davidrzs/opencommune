from pathlib import Path

from opencommune.config import Settings


def test_configuration_defaults_to_data_dir():
    s = Settings(_env_file=None, data_dir=Path("/state"))
    assert s.communes_file == Path("/state/communes.yaml")
    assert s.cantons_file == Path("/state/cantons.yaml")


def test_config_dir_separates_configuration_from_crawl_state():
    s = Settings(_env_file=None, data_dir=Path("/state"), config_dir=Path("/repo/data"))
    assert s.communes_file == Path("/repo/data/communes.yaml")
    assert s.parsed_dir == Path("/state/parsed")
