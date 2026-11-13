"""OpenAI's Batch API: send input files, follow the batches, read and delete their results.

Uploaded files hold page images, so none stays at OpenAI longer than its batch needs it: a file is
deleted when its batch cannot be created, and all of a batch's files once its results are stored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from .render import ENDPOINT

BASE_URL = "https://api.openai.com/v1"
# USD per million input and output tokens at the batch price, from OpenAI's pricing page, 2026-11.
PRICES = {"gpt-6-luna": (0.05, 0.25)}
FINISHED = frozenset({"completed", "expired", "failed", "cancelled"})
FIND_PAGES = 20  # pages of 100 batches, newest first, searched for batches a crash lost track of


@dataclass(frozen=True)
class Outcome:
    sha256: str
    answer: dict | None
    model: str | None
    usage: dict
    reason: str | None  # why there is no answer: an error code or a short text
    detail: object  # the error as returned


def input_name(file: int) -> str:
    return f"input-{file:04d}.jsonl"


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1e6


class BatchAPI:
    def __init__(self, client: httpx.Client) -> None:
        self.http = client

    @classmethod
    def connect(cls, key: str) -> BatchAPI:
        timeout = httpx.Timeout(600, connect=30)  # uploads of up to 200 MB
        headers = {"Authorization": f"Bearer {key}"}
        return cls(httpx.Client(base_url=BASE_URL, headers=headers, timeout=timeout))

    def close(self) -> None:
        self.http.close()

    def send(self, path: Path, job: str, file: int) -> str:
        """Upload one input file and start its batch; returns the batch id."""
        with path.open("rb") as stream:
            uploaded = self.http.post(
                "/files", data={"purpose": "batch"}, files={"file": (path.name, stream)}
            )
        uploaded.raise_for_status()
        file_id = uploaded.json()["id"]
        created = self.http.post(
            "/batches",
            json={
                "input_file_id": file_id,
                "endpoint": ENDPOINT,
                "completion_window": "24h",
                "metadata": {"job": job, "file": input_name(file)},
            },
        )
        if created.is_error:
            self.http.delete(f"/files/{file_id}")
        created.raise_for_status()
        return created.json()["id"]

    def get(self, batch_id: str) -> dict:
        response = self.http.get(f"/batches/{batch_id}")
        response.raise_for_status()
        return response.json()

    def find(self, job: str) -> dict[int, str]:
        """The job's batches that OpenAI holds, by input file number."""
        found: dict[int, str] = {}
        params: dict = {"limit": 100}
        for _ in range(FIND_PAGES):
            response = self.http.get("/batches", params=params)
            response.raise_for_status()
            page = response.json()
            for batch in page["data"]:
                metadata = batch.get("metadata") or {}
                name = re.fullmatch(r"input-(\d+)\.jsonl", metadata.get("file") or "")
                if metadata.get("job") == job and name:
                    found.setdefault(int(name.group(1)), batch["id"])
            if not page.get("has_more") or not page["data"]:
                break
            params = {"limit": 100, "after": page["data"][-1]["id"]}
        return found

    def result_lines(self, batch: dict) -> list[str]:
        """The lines of a finished batch's output and error files, as OpenAI returns them."""
        lines: list[str] = []
        for field in ("output_file_id", "error_file_id"):
            if batch.get(field):
                response = self.http.get(f"/files/{batch[field]}/content")
                response.raise_for_status()
                lines.extend(response.text.splitlines())
        return lines

    def delete_files(self, batch: dict) -> None:
        for field in ("input_file_id", "output_file_id", "error_file_id"):
            if batch.get(field):
                response = self.http.delete(f"/files/{batch[field]}")
                if response.status_code != 404:
                    response.raise_for_status()

    def cancel(self, batch_id: str) -> None:
        self.http.post(f"/batches/{batch_id}/cancel").raise_for_status()


def parse_line(line: str) -> Outcome:
    """One line of a batch's output or error file."""
    record = json.loads(line)
    response = record.get("response") or {}
    body = response.get("body") or {}
    text = refusal = None
    for item in body.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    text = part.get("text")
                elif part.get("type") == "refusal":
                    refusal = part.get("refusal")
    answer = None
    problem = record.get("error") or body.get("error") or refusal or body.get("incomplete_details")
    if response.get("status_code") == 200 and body.get("status") == "completed" and text:
        try:
            answer = json.loads(text)
        except ValueError:
            problem = "answer is not JSON"
        else:
            if not isinstance(answer, dict):
                answer, problem = None, "answer is not a JSON object"
    if answer is None and not problem:
        problem = f"no answer, status {body.get('status') or response.get('status_code')}"
    return Outcome(
        sha256=record["custom_id"],
        answer=answer,
        model=body.get("model"),
        usage=body.get("usage") or {},
        reason=None if answer is not None else _reason(problem),
        detail=None if answer is not None else problem,
    )


def _reason(problem) -> str:
    if isinstance(problem, dict):
        return str(problem.get("code") or problem.get("reason") or problem.get("message"))
    return str(problem)
