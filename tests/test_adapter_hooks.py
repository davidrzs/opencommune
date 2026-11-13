"""The adapter hook interface the crawl driver relies on."""

import inspect

import httpx

from opencommune.crawl.adapters import _REGISTRY, ListingAdapter, get_adapter
from opencommune.schemas import AdapterConfig, AdapterStep, SourceConfig


def _source(**kw) -> SourceConfig:
    return SourceConfig(
        listing_urls=["https://www.example.ch/politik"],
        adapter_config=AdapterConfig(steps=[AdapterStep(selector="a")]),
        **kw,
    )


def test_default_hooks_on_the_base_class():
    adapter = ListingAdapter()
    assert adapter.listing_urls(_source()) == ["https://www.example.ch/politik"]
    req = adapter.request(AdapterStep(selector="a"), "https://www.example.ch/politik")
    assert (
        isinstance(req, httpx.Request)
        and req.method == "GET"
        and str(req.url) == "https://www.example.ch/politik"
    )
    assert (
        adapter.next_url(
            "<html></html>", "https://www.example.ch/politik", AdapterStep(selector="a")
        )
        is None
    )


def test_every_registered_adapter_has_the_full_interface():
    for name, adapter in _REGISTRY.items():
        assert get_adapter(name) is adapter and isinstance(adapter, ListingAdapter)
        params = inspect.signature(adapter.extract_links).parameters
        assert list(params)[:5] == ["html", "base_url", "step", "date_regex", "date_order"]
        assert params["parent"].default is None
        assert "headers" in inspect.signature(adapter.next_url).parameters


def test_step_kind_names_a_hop():
    assert AdapterStep(selector="x", kind="meetings").kind == "meetings"
    assert AdapterStep(selector="x").kind is None
