"""Small scheduling rules shared by resumable municipal archive collectors."""

from __future__ import annotations

import time


def source_priority(state: dict | None, *, refresh: bool) -> tuple[str, int, bool]:
    """Oldest backlog or refresh attempt first; prefer new sources on a tie."""
    state = state or {}
    held = sum(row.get("status") == "held" for row in state.get("downloads", {}).values())
    if refresh:
        timestamp = state.get("refresh_attempted_at") or state.get("refreshed_at") or ""
    else:
        timestamp = state.get("updated_at") or ""
    return (timestamp, held, bool(state))


def commune_deadline(global_deadline: float | None, commune_max_minutes: float | None):
    """Set a cooperative commune boundary without extending the global job budget."""
    if commune_max_minutes is None:
        return global_deadline
    local = time.monotonic() + commune_max_minutes * 60
    return min(global_deadline, local) if global_deadline is not None else local
