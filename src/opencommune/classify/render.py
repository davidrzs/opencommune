"""Page images and batch request lines, each document rendered in its own process.

A PDF can crash the rendering library, hang, or grow to many gigabytes. One process per document,
with a time limit and a memory limit, costs only that document when it does.
"""

from __future__ import annotations

import base64
import json
import math
import multiprocessing
import resource
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from .record import PromptRecord

ENDPOINT = "/v1/responses"
ANSWER_NAME = "document_sections"
PATCH = 32  # pixels on each side of an image patch, as OpenAI counts them
RENDER_MEMORY = 4_000_000_000  # bytes of address space for one document; most need under 0.5 GB


@dataclass(frozen=True)
class Rendered:
    line: str  # the batch input line, without its newline
    pages: int
    pages_sent: int
    jpeg_quality: int
    estimated_tokens: int  # image tokens only


def pages_to_send(count: int, cap: int) -> list[int]:
    """All pages up to the cap. Above it, the first third of the cap, the last sixth, and the rest
    spread evenly in between (0-based)."""
    if count <= cap:
        return list(range(count))
    head, tail = cap // 3, cap // 6
    middle = cap - head - tail
    between = count - head - tail
    spaced = [head + (2 * i + 1) * between // (2 * middle) for i in range(middle)]
    return sorted(set(range(head)) | set(spaced) | set(range(count - tail, count)))


def image_tokens(width: int, height: int) -> int:
    """OpenAI's patch rule for the model family."""
    return math.ceil(math.ceil(width / PATCH) * math.ceil(height / PATCH) * 1.2)


def page_jpeg(page, dpi: int, max_patches: int, quality: int) -> tuple[bytes, int, int]:
    import pymupdf

    scale = dpi / 72
    width, height = page.rect.width * scale, page.rect.height * scale
    patches = (width / PATCH) * (height / PATCH)
    if max_patches and patches > max_patches:
        scale *= math.sqrt(max_patches / patches) * 0.98
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    return pixmap.tobytes("jpeg", jpg_quality=quality), pixmap.width, pixmap.height


def document_request(row: dict, pdf: Path, record: PromptRecord) -> Rendered | None:
    """The request for one document: canton and commune, then each page sent after its label.
    None if the PDF has no readable page. A request over the size limit is rendered again at the
    next JPEG quality."""
    import pymupdf

    settings = record.settings
    try:
        with pymupdf.open(pdf) as doc:
            total = doc.page_count
            if not total:
                return None
            for quality in settings.jpeg_quality_first_then_if_too_large:
                header = f"Canton: {row['canton']}\nCommune: {row['commune_name']}"
                content = [{"type": "input_text", "text": header}]
                tokens = size = 0
                for index in pages_to_send(total, settings.max_pages):
                    jpeg, width, height = page_jpeg(
                        doc[index], settings.dpi, settings.max_patches, quality
                    )
                    image = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
                    content.append({"type": "input_text", "text": f"Page {index + 1} of {total}"})
                    content.append({"type": "input_image", "image_url": image})
                    tokens += image_tokens(width, height)
                    size += len(jpeg)
                if size * 4 / 3 < settings.max_request_bytes:  # base64 grows by a third
                    break
    except (RuntimeError, ValueError, FileNotFoundError):
        return None
    body = {
        "model": settings.model,
        "instructions": record.prompt.rstrip("\n"),
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": ANSWER_NAME,
                "strict": True,
                "schema": record.schema,
            }
        },
        "store": settings.store,
    }
    line = {"custom_id": row["sha256"], "method": "POST", "url": ENDPOINT, "body": body}
    return Rendered(json.dumps(line), total, (len(content) - 1) // 2, quality, tokens)


def _child(work: Callable[[dict], Rendered | None], row: dict, target: Path, memory: int) -> None:
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        # When memory runs out, the kernel stops this process, not someone else's work.
        Path("/proc/self/oom_score_adj").write_text("1000")
    result = work(row)
    part = target.with_suffix(".part")
    part.write_text(json.dumps(asdict(result) if result else None))
    part.rename(target)


def render_all(
    rows: Iterable[dict],
    work: Callable[[dict], Rendered | None],
    folder: Path,
    workers: int,
    timeout: float,
    on_done: Callable[[dict, Rendered | None, str | None], None],
    memory: int = RENDER_MEMORY,
    poll: float = 0.05,
) -> None:
    """Render each row in its own process, at most `workers` at a time. `on_done(row, result,
    problem)` runs in this process; `problem` is None, "unreadable", "timed out" or "crashed, exit
    code N"."""
    context = multiprocessing.get_context("fork")
    pending = iter(rows)
    live: dict = {}
    while True:
        while len(live) < workers and (row := next(pending, None)) is not None:
            target = folder / f"{row['sha256']}.json"
            process = context.Process(target=_child, args=(work, row, target, memory), daemon=True)
            process.start()
            live[process] = (row, target, time.monotonic())
        if not live:
            return
        for process, (row, target, started) in list(live.items()):
            if process.is_alive():
                if time.monotonic() - started > timeout:
                    process.kill()
                    process.join()
                    del live[process]
                    target.with_suffix(".part").unlink(missing_ok=True)
                    on_done(row, None, "timed out")
                continue
            process.join()
            del live[process]
            if process.exitcode == 0 and target.exists():
                data = json.loads(target.read_text())
                target.unlink()
                on_done(row, Rendered(**data) if data else None, None if data else "unreadable")
            else:
                target.with_suffix(".part").unlink(missing_ok=True)
                on_done(row, None, f"crashed, exit code {process.exitcode}")
        time.sleep(poll)
