"""A small disk cache, so repeat runs are fast and the demo survives source outages."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).with_name("cache")


def _path(namespace: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode()).hexdigest()[:32]
    return CACHE_DIR / namespace / f"{digest}.json"


def read(namespace: str, key: str, max_age: float | None = None) -> Any | None:
    """Return the saved value, or None if it's missing or older than `max_age` seconds."""
    return (read_with_age(namespace, key, max_age) or (None, 0.0))[0]


def read_with_age(
    namespace: str, key: str, max_age: float | None = None
) -> tuple[Any, float] | None:
    path = _path(namespace, key)
    try:
        age = time.time() - path.stat().st_mtime
        if max_age is not None and age > max_age:
            return None
        return json.loads(path.read_text()), age
    except (OSError, ValueError):
        return None  # A missing or damaged cache file is just a cache miss.


def clear(namespace: str) -> None:
    for path in (CACHE_DIR / namespace).glob("*.json"):
        path.unlink(missing_ok=True)


def write(namespace: str, key: str, value: Any) -> None:
    path = _path(namespace, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename, so a crash can't leave a half-written file behind.
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as temp:
            json.dump(value, temp)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
