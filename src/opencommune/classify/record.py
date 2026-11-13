"""Prompt records: the exact prompt, answer form and request settings of one classification.

A record is a folder `prompts/<version>/` with `prompt.txt`, `schema.json` and `settings.json`. The
version is a hash of the three files, so a changed byte is a new version. Every answer is stored
with the version that produced it, and several versions can be kept side by side.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

PROMPTS = Path(__file__).parent / "prompts"
PARTS = ("prompt.txt", "schema.json", "settings.json")
DEFAULT_VERSION = "classify-65e415a748e2"


class RequestSettings(BaseModel):
    """Everything besides the prompt and the answer form that decides a request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    store: Literal[False]  # page images and answers are never kept at OpenAI
    completion_window: Literal["24h"]
    dpi: int
    max_patches: int  # a larger page is scaled down to this many 32-pixel patches
    max_pages: int
    max_request_bytes: int
    jpeg_quality_first_then_if_too_large: tuple[int, ...]
    # A hash of the code that built the requests of the first two records. It describes that code;
    # the requests built here are pinned by a test instead.
    code_sha256: str | None = None


@dataclass(frozen=True)
class PromptRecord:
    version: str
    folder: Path
    prompt: str
    schema: dict
    settings: RequestSettings


def version_of(parts: dict[str, bytes]) -> str:
    digest = hashlib.sha256(b"\0".join(parts[name] for name in PARTS)).hexdigest()
    return f"classify-{digest[:12]}"


def versions(root: Path = PROMPTS) -> list[str]:
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / PARTS[0]).exists())


def load(version: str, root: Path = PROMPTS) -> PromptRecord:
    folder = root / version
    if not folder.is_dir():
        raise ValueError(f"no prompt record {version}; known: {', '.join(versions(root))}")
    parts = {name: (folder / name).read_bytes() for name in PARTS}
    if version_of(parts) != version:
        raise ValueError(f"the files in {folder} do not match their version")
    return PromptRecord(
        version=version,
        folder=folder,
        prompt=parts["prompt.txt"].decode(),
        schema=json.loads(parts["schema.json"]),
        settings=RequestSettings.model_validate_json(parts["settings.json"]),
    )


def register(prompt: Path, schema: Path, settings: Path, root: Path = PROMPTS) -> str:
    """Copy draft files into a new record and return its version. The record must be committed
    before anything is sent with it."""
    parts = {"prompt.txt": prompt.read_bytes(), "schema.json": schema.read_bytes()}
    parts["settings.json"] = settings.read_bytes()
    RequestSettings.model_validate_json(parts["settings.json"])
    json.loads(parts["schema.json"])
    version = version_of(parts)
    folder = root / version
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in parts.items():
        (folder / name).write_bytes(content)
    return version


def require_committed(record: PromptRecord) -> None:
    """Nothing is sent with a record that is not in git as it is on disk: the record is what makes
    an answer reproducible."""
    for name in PARTS:
        path = record.folder / name
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", name], cwd=record.folder, capture_output=True
        )
        changed = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", name], cwd=record.folder, capture_output=True
        )
        if tracked.returncode != 0 or changed.returncode != 0:
            raise ValueError(f"{path} is not committed")
