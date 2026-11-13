import datetime as dt
import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opencommune import catalog
from opencommune.config import settings
from opencommune.db import _make_engine, init_db
from opencommune.models import CatalogCommune, CatalogPDF, Commune
from opencommune.schemas import RawSidecar


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    engine = _make_engine(f"sqlite:///{tmp_path}/test.db")
    init_db(engine)
    with Session(engine) as session:
        commune = Commune(
            bfs_id=1, name="Testgemeinde", canton="BE", language="de", website="https://example.org"
        )
        session.add(commune)
        session.flush()
        yield session, commune
    engine.dispose()


def raw(
    sha,
    *,
    title="Private Person",
    date_precision="day",
    source_url="https://example.org/original.pdf",
    content_selector=None,
    listing_date=dt.date(2025, 11, 1),
):
    (settings.raw_dir / f"{sha}.pdf").write_bytes(b"%PDF-test")
    sidecar = RawSidecar(
        sha256=sha,
        source_url=source_url,
        content_selector=content_selector,
        listing_url="https://example.org/",
        commune_bfs_id=1,
        body="assembly",
        fetched_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        size=9,
        listing_title=title,
        listing_date=listing_date,
        date_precision=date_precision,
    )
    (settings.raw_dir / f"{sha}.json").write_text(sidecar.model_dump_json())


def test_unparsed_document_is_visible_untagged_and_removed_with_its_sidecar(corpus):
    session, commune = corpus
    sha = "a" * 64
    raw(sha)
    assert catalog.refresh(session, [commune]) == 1
    row = session.get(CatalogPDF, sha)
    assert row.title == "Gemeindedokument"
    assert catalog.refresh(session, [commune]) == 1
    assert row.commune_name == "Testgemeinde" and "Private Person" not in row.title
    (settings.raw_dir / f"{sha}.json").unlink()
    assert catalog.refresh(session, [commune]) == 0
    assert session.get(CatalogPDF, sha) is None


def test_a_date_more_than_a_year_after_the_download_is_unknown(corpus):
    session, commune = corpus  # the sidecars are fetched on 2026-01-01
    raw("e" * 64, listing_date=dt.date(2026, 12, 1))
    raw("f" * 64, listing_date=dt.date(2029, 5, 26))
    catalog.refresh(session, [commune])
    assert session.get(CatalogPDF, "e" * 64).source_date == dt.date(2026, 12, 1)
    assert session.get(CatalogPDF, "f" * 64).source_date is None


def test_document_without_a_held_copy_is_listed_with_its_original_link(corpus):
    session, commune = corpus
    sha = "d" * 64
    raw(sha)
    (settings.raw_dir / f"{sha}.pdf").unlink()
    assert catalog.refresh(session, [commune]) == 1
    assert session.get(CatalogPDF, sha).source_url == "https://example.org/original.pdf"


def test_other_json_files_and_html_pages_are_not_listed(corpus):
    session, commune = corpus
    (settings.raw_dir / "index.json").write_text("{}")
    sha = "e" * 64
    raw(sha, content_selector="main")
    assert catalog.refresh(session, [commune]) == 0


@pytest.mark.parametrize(
    "fields",
    [
        {"title": "Einbürgerung Private Person"},
        {"title": "Domanda di attinenza comunale"},
        {"source_url": "https://example.org/Naturalizzazione-Private-Person.pdf"},
        {"source_url": "https://example.org/Einb%C3%BCrgerung_Person.pdf"},
        {"source_url": "https://example.org/Einbu%CC%88rgerung_Person.pdf"},
        {"source_url": "https://example.org/einbuergerung-person.pdf"},
        {"source_url": "https://example.org/demande-droit-de-cite.pdf"},
    ],
)
def test_naturalisation_documents_are_not_listed(corpus, fields):
    session, commune = corpus
    raw("f" * 64, **fields)
    assert catalog.refresh(session, [commune]) == 0


@pytest.mark.parametrize(
    "path, listed",
    [
        ("verwaltung/online-schalter.html/240/print/pdf/product/158", 0),
        ("verwaltung/mitarbeitende-a-z.html/1/print/pdf/person_guid/2", 0),
        ("stadtparlament/sitzungen/traktandum-detailseite.html/7/print/pdf", 1),
        ("stadtparlament/geschaeftsdatenbank/geschaeft-detail.html/7/print/pdf", 1),
    ],
)
def test_print_views_are_listed_only_for_council_pages(corpus, path, listed):
    session, commune = corpus
    raw("f" * 64, source_url=f"https://example.org/{path}")
    assert catalog.refresh(session, [commune]) == listed


@pytest.mark.parametrize(
    "title, url, label",
    [
        ("", "https://example.org/Budgetbotschaft%202024.pdf", "Budget 2024"),
        ("Jahresrechnung", "https://example.org/x.pdf", "Jahresrechnung"),
        ("", "https://example.org/Proc%C3%A8s-verbal_12.03.2021.pdf", "Procès-verbal 2021"),
        ("", "https://example.org/20221212_PV_1671059443.pdf", "Procès-verbal"),
        ("Hans Muster", "https://example.org/Hans_Muster.pdf", "Gemeindedokument"),
        ("Hans Muster 2021", "https://example.org/Protokoll-Muster.pdf", "Protokoll 2021"),
        ("", "https://example.org/protokoll/Hans_Muster.pdf", "Gemeindedokument"),
    ],
)
def test_labels_come_from_a_fixed_list_and_show_no_other_word(corpus, title, url, label):
    session, commune = corpus
    raw("f" * 64, title=title, source_url=url)
    catalog.refresh(session, [commune])
    assert session.get(CatalogPDF, "f" * 64).title == label


def test_refresh_batches_rows_and_preserves_unchanged_index_time(corpus, monkeypatch):
    session, commune = corpus
    monkeypatch.setattr(catalog, "BATCH_SIZE", 2)
    shas = [f"{n:064x}" for n in range(5)]
    for sha in shas:
        raw(sha)

    assert catalog.refresh(session, [commune]) == 5
    assert not any(isinstance(obj, CatalogPDF) for obj in session.identity_map.values())
    first = session.get(CatalogPDF, shas[0])
    initial_index_time = first.indexed_at

    assert catalog.refresh(session, [commune]) == 5
    assert session.get(CatalogPDF, shas[0]).indexed_at == initial_index_time


def test_batched_refresh_is_atomic_and_stale_deletion_rolls_back(corpus, monkeypatch):
    session, commune = corpus
    monkeypatch.setattr(catalog, "BATCH_SIZE", 2)
    old_sha = "a" * 64
    raw(old_sha)
    catalog.refresh(session, [commune])
    session.commit()

    new_shas = [f"{n + 10:064x}" for n in range(3)]
    for sha in new_shas:
        raw(sha)
    (settings.raw_dir / f"{old_sha}.json").unlink()
    assert catalog.refresh(session, [commune]) == 3
    assert session.get(CatalogPDF, old_sha) is None

    with Session(session.bind) as reader:
        assert reader.get(CatalogPDF, old_sha) is not None
        assert reader.scalar(select(func.count()).select_from(CatalogPDF)) == 1
    session.rollback()
    assert session.get(CatalogPDF, old_sha) is not None
    assert session.scalar(select(func.count()).select_from(CatalogPDF)) == 1


def test_month_precision_is_kept(corpus):
    session, commune = corpus
    raw("c" * 64, date_precision="month")
    catalog.refresh(session, [commune])
    row = session.get(CatalogPDF, "c" * 64)
    assert row.date_precision == "month" and row.title == "Gemeindedokument"


def test_unsafe_urls_are_dropped():
    for value in ["javascript:alert(1)", "data:text/html,test", "//example.org", "https://["]:
        assert catalog.safe_url(value) is None


def test_machine_archive_commune_appears_without_manual_config(corpus, monkeypatch):
    from opencommune import register

    session, _ = corpus
    entry = register.RegisterEntry(
        bfs_id=2, name="New commune", canton="ZH", website="https://example.org", vendor="i-web"
    )
    monkeypatch.setattr(register, "load_register", lambda: [entry])
    sha = "f" * 64
    raw(sha)
    path = settings.raw_dir / f"{sha}.json"
    sidecar = RawSidecar.model_validate_json(path.read_text())
    sidecar.commune_bfs_id = 2
    sidecar.body = "unknown"
    path.write_text(sidecar.model_dump_json())
    assert catalog.refresh(session, []) == 1
    assert session.get(Commune, 2).language == ""
    assert session.get(CatalogPDF, sha).body == "unknown"


def test_wordpress_archive_requires_batch_configuration(corpus, monkeypatch):
    from opencommune import register

    session, _ = corpus
    entry = register.RegisterEntry(
        bfs_id=2,
        name="New WP commune",
        canton="ZH",
        website="https://example.org",
        vendor="wordpress",
    )
    monkeypatch.setattr(register, "load_register", lambda: [entry])
    sha = "f" * 64
    raw(sha)
    path = settings.raw_dir / f"{sha}.json"
    sidecar = RawSidecar.model_validate_json(path.read_text())
    sidecar.commune_bfs_id = 2
    sidecar.body = "unknown"
    sidecar.adapter = "wp_media"
    sidecar.listing_url = "https://example.org/wp-json/wp/v2/media?page=2"
    path.write_text(sidecar.model_dump_json())
    assert catalog.refresh(session, []) == 0
    (settings.data_dir / "archive-sources.yaml").write_text(
        "- bfs_id: 2\n  website: https://example.org\n  adapter: wp_media\n"
        "  listing_url: https://example.org/wp-json/wp/v2/media\n"
    )
    assert catalog.refresh(session, []) == 1
    assert session.get(Commune, 2).vendor == "wordpress"
    assert session.get(CatalogPDF, sha).commune_bfs_id == 2


def test_a_file_linked_by_two_communes_is_listed_once_with_both(corpus):
    session, commune = corpus
    session.add(
        Commune(
            bfs_id=2,
            name="Nachbargemeinde",
            canton="BE",
            language="de",
            website="https://example.net",
        )
    )
    session.flush()
    sha = "a" * 64
    raw(sha, source_url="https://example.org/a.pdf")
    lines = [
        {"url": "https://example.org/a.pdf", "sha256": sha, "commune_bfs_id": 1},
        {"url": "https://example.net/a.pdf", "sha256": sha, "commune_bfs_id": 2},
        {"url": "https://example.net/b.pdf", "sha256": sha, "commune_bfs_id": 2},
        {"url": "https://example.net/c.pdf", "sha256": "b" * 64, "commune_bfs_id": 2},
    ]
    (settings.raw_dir / "urls.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    assert catalog.refresh(session, [commune]) == 1
    links = session.execute(
        select(CatalogCommune.commune_bfs_id, CatalogCommune.source_url).order_by(
            CatalogCommune.commune_bfs_id
        )
    ).all()
    assert links == [(1, "https://example.org/a.pdf"), (2, "https://example.net/a.pdf")]
    assert session.get(CatalogPDF, sha).commune_bfs_id == 1


def test_a_catalogue_in_an_older_layout_is_dropped_and_created_again(tmp_path):
    engine = _make_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE pdf_catalog (sha256 TEXT PRIMARY KEY, status TEXT)")
    assert catalog.rebuild_if_outdated(engine)
    assert not catalog.rebuild_if_outdated(engine)
    engine.dispose()
