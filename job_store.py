"""Small SQLite-backed persistence layer for web application jobs."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from config import JOB_DATABASE


def _connect() -> sqlite3.Connection:
    folder = os.path.dirname(os.path.abspath(JOB_DATABASE))
    os.makedirs(folder, exist_ok=True)
    connection = sqlite3.connect(JOB_DATABASE, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def init_db() -> None:
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL,
                message TEXT NOT NULL,
                error TEXT,
                result_json TEXT,
                detail TEXT,
                error_kind TEXT,
                error_status INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(jobs)")
        }
        migrations = {
            "type": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'running'",
            "progress": "INTEGER NOT NULL DEFAULT 0",
            "message": "TEXT NOT NULL DEFAULT ''",
            "error": "TEXT",
            "result_json": "TEXT",
            "detail": "TEXT",
            "error_kind": "TEXT",
            "error_status": "INTEGER",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
            "payload_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, definition in migrations.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs(created_at DESC)"
        )


def save_job(job: dict[str, Any]) -> None:
    result = job.get("result")
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                id, type, status, progress, message, error, result_json,
                detail, error_kind, error_status, created_at, updated_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type,
                status=excluded.status,
                progress=excluded.progress,
                message=excluded.message,
                error=excluded.error,
                result_json=excluded.result_json,
                detail=excluded.detail,
                error_kind=excluded.error_kind,
                error_status=excluded.error_status,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                payload_json=excluded.payload_json
            """,
            (
                job["id"],
                job.get("type", ""),
                job.get("status", ""),
                int(job.get("progress", 0)),
                job.get("message", ""),
                job.get("error"),
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                job.get("detail"),
                job.get("error_kind"),
                job.get("error_status"),
                job["created_at"],
                job["updated_at"],
                json.dumps(job, ensure_ascii=False),
            ),
        )


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    job = json.loads(row["payload_json"])
    job.update(
        {
            "id": row["id"],
            "type": row["type"],
            "status": row["status"],
            "progress": row["progress"],
            "message": row["message"],
            "error": row["error"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "detail": row["detail"],
            "error_kind": row["error_kind"],
            "error_status": row["error_status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_job(row) for row in rows]


init_db()
