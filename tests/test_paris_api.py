import datetime as dt
from urllib.parse import parse_qs, urlsplit

from opencommune.crawl.adapters import paris_api
from opencommune.crawl.adapters.paris_api import ParisApiAdapter
from opencommune.schemas import AdapterConfig, AdapterStep, SourceConfig

BASE = "https://www.gemeinderat-zuerich.ch/api/sitzung/searchdetails/"


class FixedDate(dt.date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 18)


def test_listing_queries_one_calendar_year_each_newest_first(monkeypatch):
    monkeypatch.setattr(paris_api.dt, "date", FixedDate)
    source = SourceConfig(
        adapter="paris_api",
        listing_urls=[BASE],
        adapter_config=AdapterConfig(steps=[AdapterStep(selector="Dokument")], since_days=1000),
    )
    queries = [parse_qs(urlsplit(u).query) for u in ParisApiAdapter().listing_urls(source)]
    windows = [q["q"][0].split('"')[1::2] for q in queries]
    assert windows == [
        ["2026-01-01 00:00:00", "2026-10-18 23:59:59"],
        ["2025-01-01 00:00:00", "2025-12-31 23:59:59"],
        ["2024-01-22 00:00:00", "2024-12-31 23:59:59"],  # 1000 days before 2026-10-18
    ]
    assert all(q["m"] == [str(paris_api.YEAR_LIMIT)] for q in queries)
