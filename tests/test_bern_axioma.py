import datetime as dt
from urllib.parse import parse_qs, urlsplit

from opencommune.crawl.adapters import bern_axioma
from opencommune.crawl.adapters.bern_axioma import BernAxiomaAdapter
from opencommune.schemas import AdapterConfig, AdapterStep, SourceConfig

BASE = "https://stadtrat.bern.ch/format/module/politik_axioma/sitzungen/sitzungen_data_server.php"


class FixedDate(dt.date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 18)


def test_listing_queries_one_calendar_year_each_newest_first(monkeypatch):
    monkeypatch.setattr(bern_axioma.dt, "date", FixedDate)
    source = SourceConfig(
        adapter="bern_axioma",
        listing_urls=[BASE],
        adapter_config=AdapterConfig(steps=[AdapterStep(selector="data")], since_days=700),
    )
    queries = [parse_qs(urlsplit(u).query) for u in BernAxiomaAdapter().listing_urls(source)]
    assert [(q["dateFrom"][0], q["dateTo"][0]) for q in queries] == [
        ("01.01.2026", "31.12.2026"),
        ("01.01.2025", "31.12.2025"),
        ("01.01.2024", "31.12.2024"),  # 700 days before 2026-10-18 is in 2024
    ]
    assert all(q["params[length]"] == ["450"] for q in queries)
