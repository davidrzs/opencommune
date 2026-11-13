"""Keep a configurable free-space reserve on the raw archive filesystem."""

import shutil

from ..config import settings


class StorageReserveError(RuntimeError):
    """A local capacity limit, not a failed remote document."""


def require_space(incoming=0):
    """Free bytes on the raw archive filesystem; StorageReserveError below the reserve plus
    `incoming`."""
    path = settings.raw_dir
    free = shutil.disk_usage(path).free
    required = settings.raw_min_free_bytes + incoming
    if free < required:
        raise StorageReserveError(
            f"Raw archive storage paused: {free:,} bytes free at {path}; "
            f"{required:,} required including the configured reserve. "
            "Expand storage before resuming downloads."
        )
    return free
