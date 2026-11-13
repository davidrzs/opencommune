import json

import httpx
import pytest

from opencommune.classify import jobs, record
from opencommune.classify.batch_api import BatchAPI, parse_line
from opencommune.classify.render import Rendered
from opencommune.classify.store import Store

VERSION = record.DEFAULT_VERSION
SHAS = [f"{n:02x}" * 32 for n in range(1, 31)]


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "process.db") as opened:
        yield opened


@pytest.fixture
def paths(tmp_path):
    return jobs.Paths(tmp_path / "process.db", tmp_path / "outputs", tmp_path / "scratch")


def rows(shas=SHAS):
    return [{"sha256": sha, "canton": "ZH", "commune_name": "Musterdorf"} for sha in shas]


def fake_render(row):
    line = {"custom_id": row["sha256"], "method": "POST", "url": "/v1/responses", "body": {}}
    return Rendered(json.dumps(line), 4, 4, 75, 1000)


def prepare(store, paths, tmp_path, job="cls-1", shas=SHAS, work=fake_render):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    for sha in shas:
        (raw / f"{sha}.pdf").write_bytes(b"%PDF")
    loaded = record.load(VERSION)
    return jobs.prepare(store, paths, loaded, job, rows(shas), raw, workers=2, work=work)


# --- which documents are open ---------------------------------------------------------------


def test_an_answered_document_never_comes_back(store):
    store.add_answer(SHAS[0], VERSION, "j", {"x": 1}, {})
    assert jobs.open_documents(rows(SHAS[:2]), store, VERSION) == rows(SHAS[1:2])
    assert jobs.open_documents(rows(SHAS[:2]), store, "classify-other") == rows(SHAS[:2])


def test_a_document_stops_after_three_failures_and_expired_requests_do_not_count(store):
    for at in ("1", "2"):
        store.add_failure(SHAS[0], VERSION, "j", "render", "crashed, exit code -9", at=at)
    for at in ("3", "4", "5"):
        store.add_failure(SHAS[0], VERSION, "j", "request", "batch_expired", at=at)
    assert jobs.open_documents(rows(SHAS[:1]), store, VERSION) == rows(SHAS[:1])
    store.add_failure(SHAS[0], VERSION, "j", "request", "server_is_overloaded", at="6")
    assert jobs.open_documents(rows(SHAS[:1]), store, VERSION) == []


def test_a_version_is_always_rendered_by_the_same_library(store):
    store.freeze_renderer(VERSION, "pymupdf 1.28.2")
    store.freeze_renderer(VERSION, "pymupdf 1.28.2")
    with pytest.raises(ValueError, match=r"rendered with pymupdf 1\.28\.2"):
        store.freeze_renderer(VERSION, "pymupdf 1.29.0")


def test_many_missing_pdfs_stop_and_a_few_stay_open(tmp_path):
    with pytest.raises(RuntimeError, match="missing"):
        jobs.present(rows(), tmp_path)
    for sha in SHAS[:25]:
        (tmp_path / f"{sha}.pdf").write_bytes(b"%PDF")
    assert jobs.present(rows(), tmp_path) == rows(SHAS[:25])


# --- importing the first implementation's ledger ----------------------------------------------


def old_ledger(path):
    usage = {
        "prompt_tokens": 900,
        "completion_tokens": 100,
        "completion_tokens_details": {"reasoning_tokens": 40},
    }
    lines = [
        {
            "sha256": SHAS[0],
            "status": "answered",
            "job": "cls-2",
            "prompt_version": VERSION,
            "model_returned": "gpt-6-luna",
            "pages": 5,
            "pages_sent": 5,
            "jpeg_quality": 75,
            "answer": {"document_kind": "standalone"},
            "usage": usage,
            "error": None,
            "at": "2026-11-12T01:22:23+00:00",
        },
        {
            "sha256": SHAS[1],
            "status": "unreadable",
            "stage": "render",
            "job": "cls-2",
            "prompt_version": VERSION,
            "error": "unreadable",
            "at": "2026-11-11T20:00:00+00:00",
        },
        {
            "sha256": SHAS[2],
            "status": "failed",
            "job": "cls-2",
            "prompt_version": VERSION,
            "model_returned": None,
            "pages": 2,
            "pages_sent": 2,
            "jpeg_quality": 75,
            "answer": None,
            "usage": {},
            "error": {"code": "batch_expired", "message": "expired"},
            "at": "2026-11-13T10:00:00+00:00",
        },
    ]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def test_a_ledger_is_imported_once_and_keeps_what_it_says(store, tmp_path):
    ledger = old_ledger(tmp_path / "ledger.jsonl")
    before = ledger.read_bytes()
    frozen = tmp_path / "frozen.json"
    frozen.write_text(json.dumps({"prompt_version": VERSION, "pymupdf": "1.28.2"}))
    assert jobs.import_ledger(store, ledger, frozen) == {
        "answers": 1,
        "failures": 2,
        "already there": 0,
    }
    assert jobs.import_ledger(store, ledger, frozen) == {
        "answers": 0,
        "failures": 0,
        "already there": 3,
    }
    assert ledger.read_bytes() == before
    assert dict(store.answers(VERSION)) == {SHAS[0]: {"document_kind": "standalone"}}
    assert store.usage(VERSION) == (900, 100)
    assert jobs.open_documents(rows(SHAS[:3]), store, VERSION) == rows(SHAS[1:3])
    with pytest.raises(ValueError, match="rendered with"):
        store.freeze_renderer(VERSION, "pymupdf 1.29.0")


def test_a_ledger_of_an_unknown_prompt_is_refused_whole(store, tmp_path):
    ledger = old_ledger(tmp_path / "ledger.jsonl")
    ledger.write_text(ledger.read_text().replace(VERSION, "classify-000000000000", 1))
    with pytest.raises(ValueError, match="no prompt record"):
        jobs.import_ledger(store, ledger)
    assert store.answered(VERSION) == set()


# --- prepare ----------------------------------------------------------------------------------


def test_prepare_renders_what_is_open_and_records_failures(store, paths, tmp_path):
    def work(row):
        return None if row["sha256"] == SHAS[0] else fake_render(row)

    counts = prepare(store, paths, tmp_path, work=work)
    assert counts == {"rendered": 29, "failed": 1}
    lines = (paths.inputs("cls-1") / "input-0001.jsonl").read_text().splitlines()
    assert len(lines) == 29 and store.requested("cls-1") == set(SHAS[1:])
    assert store.failure_counts(VERSION) == {SHAS[0]: 1}


def test_a_new_job_waits_until_the_open_one_is_back(store, paths, tmp_path):
    prepare(store, paths, tmp_path)
    with pytest.raises(RuntimeError, match="finish cls-1"):
        prepare(store, paths, tmp_path, job="cls-2")
    assert prepare(store, paths, tmp_path) == {"rendered": 0, "failed": 0}  # it may resume


def test_a_cut_or_unlisted_line_is_dropped_from_the_last_input_file(tmp_path):
    path = tmp_path / "input-0001.jsonl"
    good = b'{"custom_id": "aa", "x": 1}\n'
    path.write_bytes(good + b'{"custom_id": "bb", "x": 1}\n' + b'{"custom_id": "aa", "x"')
    jobs.drop_unlisted_lines(path, {"aa"})
    assert path.read_bytes() == good
    jobs.drop_unlisted_lines(path, set())
    assert not path.exists()


def test_one_prepare_or_drive_per_version(paths):
    paths.database.parent.mkdir(parents=True, exist_ok=True)
    with (
        jobs.exclusive(paths, VERSION),
        pytest.raises(RuntimeError),
        jobs.exclusive(paths, VERSION),
    ):
        pass
    with jobs.exclusive(paths, VERSION):
        pass


# --- drive ------------------------------------------------------------------------------------


def answer_line(sha, usage):
    body = {
        "status": "completed",
        "model": "gpt-6-luna",
        "usage": usage,
        "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"ok": 1}'}]}],
    }
    return json.dumps({"custom_id": sha, "response": {"status_code": 200, "body": body}})


class FakeBatchAPI:
    """Batches finish when first asked about, unless `slow` names their input file."""

    def __init__(self, usage=None, found=None, slow=()):
        self.usage = usage or {"input_tokens": 1000, "output_tokens": 100}
        self.found, self.slow = found or {}, set(slow)
        self.sent, self.cancelled, self.deleted = [], [], []
        self.requests = {}

    def find(self, job):
        return dict(self.found)

    def send(self, path, job, file):
        batch_id = f"batch-{file}"
        self.sent.append(file)
        self.requests[batch_id] = [json.loads(line)["custom_id"] for line in path.open()]
        return batch_id

    def get(self, batch_id):
        file = int(batch_id.split("-")[1])
        if batch_id in self.cancelled:
            status = "cancelled"
        else:
            status = "in_progress" if file in self.slow else "completed"
        return {"id": batch_id, "status": status, "output_file_id": f"out-{file}"}

    def result_lines(self, batch):
        if batch["status"] != "completed":
            return []
        return [answer_line(sha, self.usage) for sha in self.requests.get(batch["id"], [])]

    def delete_files(self, batch):
        self.deleted.append(batch["id"])

    def cancel(self, batch_id):
        self.cancelled.append(batch_id)


def small_files(monkeypatch):
    monkeypatch.setattr(jobs, "MAX_FILE_BYTES", 150)  # one request per file


def test_drive_sends_each_file_once_and_cleans_up(store, paths, tmp_path, monkeypatch):
    small_files(monkeypatch)
    prepare(store, paths, tmp_path)
    api = FakeBatchAPI()
    jobs.drive(store, api, paths, record.load(VERSION), "cls-1", max_usd=10, poll=0)
    assert sorted(api.sent) == list(range(1, 31))
    assert store.answered(VERSION) == set(SHAS)
    assert sorted(api.deleted) == sorted(f"batch-{n}" for n in range(1, 31))
    assert not list(paths.inputs("cls-1").glob("input-*"))
    assert len(list(paths.outputs.glob("*.jsonl.gz"))) == 30
    assert store.open_jobs(VERSION) == []


def test_drive_does_not_send_again_what_a_crash_lost_track_of(store, paths, tmp_path, monkeypatch):
    small_files(monkeypatch)
    prepare(store, paths, tmp_path)
    api = FakeBatchAPI(found={1: "batch-1"})
    api.requests["batch-1"] = [SHAS[0]]
    jobs.drive(store, api, paths, record.load(VERSION), "cls-1", max_usd=10, poll=0)
    assert 1 not in api.sent and len(api.sent) == 29
    assert store.answered(VERSION) == set(SHAS)


def test_reaching_the_limit_cancels_what_runs_and_keeps_what_came(
    store, paths, tmp_path, monkeypatch
):
    small_files(monkeypatch)
    prepare(store, paths, tmp_path)
    api = FakeBatchAPI(usage={"input_tokens": 200_000_000, "output_tokens": 0}, slow=range(2, 31))
    jobs.drive(store, api, paths, record.load(VERSION), "cls-1", max_usd=10, poll=0)
    assert store.answered(VERSION) == {SHAS[0]}
    assert len(api.cancelled) == 29
    assert len(jobs.open_documents(rows(), store, VERSION)) == 29


def test_decide_stops_on_spend_quality_failure_and_projection():
    assert jobs.decide(0, 0, 0, 0, 250, False) is None
    assert jobs.decide(10, 100, 200, 200, 250, False) is None
    assert "limit" in jobs.decide(250, 250, 200, 200, 250, False)
    assert "usable" in jobs.decide(1, 10, 180, 200, 250, False)
    assert jobs.decide(1, 10, 9, 10, 250, False) is None  # too few to judge
    assert "projected" in jobs.decide(30, 300, 200, 200, 250, False)
    assert "failed" in jobs.decide(1, 10, 9, 10, 250, True)


# --- the Batch API ----------------------------------------------------------------------------


def test_results_are_answers_or_failures_with_a_reason():
    usage = {"input_tokens": 10, "output_tokens": 2}
    good = parse_line(answer_line(SHAS[0], usage))
    assert good.answer == {"ok": 1} and good.reason is None and good.usage == usage
    expired = parse_line(json.dumps({"custom_id": SHAS[1], "error": {"code": "batch_expired"}}))
    assert expired.answer is None and expired.reason == "batch_expired"
    cut = json.loads(answer_line(SHAS[2], usage))
    cut["response"]["body"]["output"][0]["content"][0]["text"] = '{"ok": '
    assert parse_line(json.dumps(cut)).reason == "answer is not JSON"
    incomplete = json.loads(answer_line(SHAS[3], usage))
    incomplete["response"]["body"] |= {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
    }
    assert parse_line(json.dumps(incomplete)).reason == "max_output_tokens"


def test_an_uploaded_file_is_deleted_when_its_batch_cannot_be_created(tmp_path):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/files":
            return httpx.Response(200, json={"id": "file-1"})
        if request.url.path == "/v1/batches":
            return httpx.Response(400, json={"error": {"message": "bad"}})
        return httpx.Response(200, json={})

    path = tmp_path / "input-0001.jsonl"
    path.write_text("{}\n")
    client = httpx.Client(
        base_url="https://api.openai.com/v1", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(httpx.HTTPStatusError):
        BatchAPI(client).send(path, "cls-1", 1)
    assert ("DELETE", "/v1/files/file-1") in calls


def test_lost_batches_are_found_by_job_and_file():
    page = {
        "data": [
            {"id": "b1", "metadata": {"job": "cls-1", "file": "input-0001.jsonl"}},
            {"id": "b2", "metadata": {"job": "other", "file": "input-0002.jsonl"}},
            {"id": "b3", "metadata": None},
        ],
        "has_more": False,
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=page))
    client = httpx.Client(base_url="https://api.openai.com/v1", transport=transport)
    assert BatchAPI(client).find("cls-1") == {1: "b1"}


def test_drive_refuses_to_start_when_an_unsent_file_is_missing(store, paths, tmp_path, monkeypatch):
    small_files(monkeypatch)
    prepare(store, paths, tmp_path)
    (paths.inputs("cls-1") / "input-0007.jsonl").unlink()
    api = FakeBatchAPI()
    with pytest.raises(RuntimeError, match="1 unsent input files are missing"):
        jobs.drive(store, api, paths, record.load(VERSION), "cls-1", max_usd=10, poll=0)
    assert api.sent == []
