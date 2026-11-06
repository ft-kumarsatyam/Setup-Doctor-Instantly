"""Durable Instantly webhook results.

Process memory is a cache. The file is what GET /hooks/instantly/last reads
after a restart. A corrupt file is treated as empty, not as a healthy result.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class WebhookStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(key): value for key, value in data.items() if isinstance(value, dict)}

    def put(self, domain: str, row: dict[str, Any]) -> None:
        with self._lock:
            data = self.load()
            data[domain] = row
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self.path)

    def get(self, domain: str) -> dict[str, Any] | None:
        row = self.load().get(domain)
        return row if isinstance(row, dict) else None
