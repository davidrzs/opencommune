"""Bounded jobs rotate communes without discarding their download checkpoints."""

import json
import threading
from types import SimpleNamespace

import pytest

from opencommune.config import settings
from opencommune.crawl import linked_archive, scheduling, store, wordpress


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.lock = threading.Lock()

    def monotonic(self):
        with self.lock:
            return self.now

    def advance(self, seconds):
        with self.lock:
            self.now += seconds


def test_priority_separates_backlog_progress_from_refresh_attempts():
    new = scheduling.source_priority(None, refresh=False)
    large_old = {
        "updated_at": "2026-09-01T00:00:00+00:00",
        "refresh_attempted_at": "2026-09-25T00:00:00+00:00",
        "downloads": {str(i): {"status": "held"} for i in range(100)},
    }
    small_recent = {
        "updated_at": "2026-09-20T00:00:00+00:00",
        "refreshed_at": "2026-09-10T00:00:00+00:00",
        "downloads": {},
    }
    assert new < scheduling.source_priority(large_old, refresh=False)
    assert scheduling.source_priority(large_old, refresh=False) < scheduling.source_priority(
        small_recent, refresh=False
    )
    assert scheduling.source_priority(small_recent, refresh=True) < scheduling.source_priority(
        large_old, refresh=True
    )


def test_global_budget_caps_commune_slice(monkeypatch):
    monkeypatch.setattr(scheduling, "time", SimpleNamespace(monotonic=lambda: 100.0))
    assert scheduling.commune_deadline(105.0, 2) == 105.0
    assert scheduling.commune_deadline(300.0, 2) == 220.0
    assert scheduling.commune_deadline(None, 2) == 220.0
    assert scheduling.commune_deadline(105.0, None) == 105.0


def _setup_fake_job(module, tmp_path, monkeypatch, ids):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    if module is wordpress:
        sources = [
            wordpress.ArchiveSourceConfig(
                bfs_id=i,
                website=f"https://commune{i}.test",
                listing_url=f"https://commune{i}.test/wp-json/wp/v2/media?per_page=100&page=1",
            )
            for i in ids
        ]
        entries = [SimpleNamespace(bfs_id=i, name=str(i), canton="BE") for i in ids]
        monkeypatch.setattr(wordpress, "validate_sources", lambda configs, entries=None: configs)
        monkeypatch.setattr(wordpress, "summary", lambda state: {"bfs_id": state["bfs_id"]})
        kwargs = {"entries": entries}
    else:
        sources = [SimpleNamespace(bfs_id=i) for i in ids]
        monkeypatch.setattr(linked_archive, "validate_sources", lambda sources: sources)
        monkeypatch.setattr(
            linked_archive,
            "load_register",
            lambda: [SimpleNamespace(bfs_id=i, name=str(i)) for i in ids],
        )
        kwargs = {}
    monkeypatch.setattr(store, "load_index", lambda: {})
    return sources, kwargs


@pytest.mark.parametrize("module", [wordpress, linked_archive])
def test_two_bounded_jobs_rotate_even_a_large_archive(module, tmp_path, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(module, "time", clock)
    monkeypatch.setattr(scheduling, "time", clock)
    sources, kwargs = _setup_fake_job(module, tmp_path, monkeypatch, (1, 2))
    directory = module.directory()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "1.json").write_text(
        json.dumps(
            {
                "bfs_id": 1,
                "updated_at": "2026-09-01T00:00:00+00:00",
                "downloads": {str(i): {"status": "held"} for i in range(100)},
            }
        )
    )
    (directory / "2.json").write_text(
        json.dumps({"bfs_id": 2, "updated_at": "2026-09-20T00:00:00+00:00", "downloads": {}})
    )
    visited = []

    def fake_fetch_one(source, *args, **kw):
        visited.append(source.bfs_id)
        state = module.read(source.bfs_id)
        module.save(state)
        if len(visited) == 1:
            # Cooperative fetch_one can finish an in-flight request after the job deadline.
            clock.advance(0.08)
        return {"bfs_id": source.bfs_id, "status": "complete", "downloads": {}, "documents": {}}

    monkeypatch.setattr(module, "fetch_one", fake_fetch_one)
    module.run_fetch(sources, max_minutes=0.001, workers=1, emit=lambda _: None, **kwargs)
    assert visited == [1]
    module.run_fetch(sources, max_minutes=0.005, workers=1, emit=lambda _: None, **kwargs)
    assert visited == [1, 2, 1]


@pytest.mark.parametrize("module", [wordpress, linked_archive])
@pytest.mark.parametrize("workers", [1, 2])
def test_slow_first_commune_yields_a_turn_to_second(module, workers, tmp_path, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(module, "time", clock)
    monkeypatch.setattr(scheduling, "time", clock)
    sources, kwargs = _setup_fake_job(module, tmp_path, monkeypatch, (1, 2))
    visits = []

    def fake_fetch_one(source, *args, **kw):
        start = clock.monotonic()
        deadline = kw["deadline"]
        visits.append((source.bfs_id, start, deadline))
        assert 0 < deadline - start <= 0.08
        # Model a slow cooperative source reaching its deadline, with no wall-clock sleeps.
        clock.advance(max(0, deadline - clock.monotonic()) + 0.005)
        return {"bfs_id": source.bfs_id, "status": "pending", "downloads": {}, "documents": {}}

    monkeypatch.setattr(module, "fetch_one", fake_fetch_one)
    module.run_fetch(
        sources,
        max_minutes=0.006,
        commune_max_minutes=0.001,
        workers=workers,
        emit=lambda _: None,
        **kwargs,
    )
    assert {bfs for bfs, _, _ in visits} == {1, 2}


def test_wordpress_refresh_attempt_is_saved_even_when_source_needs_review(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    source = wordpress.ArchiveSourceConfig(
        bfs_id=999999,
        website="https://commune.test",
        listing_url="https://commune.test/wp-json/wp/v2/media?per_page=100&page=1",
    )
    state = wordpress.fetch_one(source, None, None, None, {}, refresh=True)
    assert state["status"] == "review"
    assert wordpress.read(source.bfs_id)["refresh_attempted_at"]
