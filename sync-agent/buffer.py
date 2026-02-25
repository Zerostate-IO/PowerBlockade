from __future__ import annotations

import json

import sqlite3
import time
from pathlib import Path
from typing import Any


class MetricsBuffer:
    def __init__(self, db_path: str, max_age_seconds: int = 604800):
        self.db_path = db_path
        self.max_age_seconds = max_age_seconds
        self._ensure_db()

    def _ensure_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    metrics TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON metrics_queue(timestamp)"
            )
            conn.commit()

    def put(self, metrics: dict[str, Any], timestamp: float) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO metrics_queue (timestamp, metrics) VALUES (?, ?)",
                (timestamp, json.dumps(metrics)),
            )
            conn.commit()

    def peek(self, limit: int = 100) -> list[tuple[int, dict[str, Any]]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT id, metrics FROM metrics_queue ORDER BY id ASC LIMIT ?",
                (limit,),
            )
            results = []
            for row in cursor.fetchall():
                try:
                    metrics = json.loads(row["metrics"])
                    results.append((row["id"], metrics))
                except json.JSONDecodeError:
                    continue
            return results

    def delete(self, item_ids: list[int]) -> None:
        if not item_ids:
            return
        with sqlite3.connect(self.db_path) as conn:
            placeholders = ",".join("?" * len(item_ids))
            conn.execute(
                f"DELETE FROM metrics_queue WHERE id IN ({placeholders})",
                item_ids,
            )
            conn.commit()

    def prune(self, max_age_seconds: int | None = None) -> int:
        if max_age_seconds is None:
            max_age_seconds = self.max_age_seconds
        if max_age_seconds <= 0:
            return 0

        cutoff = time.time() - max_age_seconds
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM metrics_queue WHERE timestamp < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM metrics_queue")
            return cursor.fetchone()[0]

    def close(self) -> None:
        pass
