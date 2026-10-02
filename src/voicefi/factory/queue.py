"""
voicefi/factory/queue.py
Transactional SQLite & PostgreSQL Queue for the Content Creation Factory.
Supports atomic job claiming (SKIP LOCKED / atomic updates), worker registration,
heartbeats, and real-time query aggregates.
"""

from __future__ import annotations

import json
import logging
import os
import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from voicefi.factory.models import ContentJob, JobStatus

logger = logging.getLogger("voicefi.factory.queue")


def get_default_factory_db_path() -> Path:
    base_dir = Path.home() / ".voicefi"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "factory.db"


class ContentFactoryQueue:
    """Thread-safe and multi-process safe queue for Content Jobs."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_default_factory_db_path()
        self._local = threading.local()
        self._worker_heartbeats: Dict[str, Tuple[float, Optional[str]]] = {}
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=20.0,
                check_same_thread=False,
                isolation_level=None,
            )
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
                conn.execute("PRAGMA busy_timeout = 10000;")
            except Exception:
                pass
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_name TEXT NOT NULL DEFAULT 'default',
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'reel_9_16',
                    characters TEXT NOT NULL DEFAULT '["Viv", "Stefan"]',
                    target_duration_s REAL NOT NULL DEFAULT 30.0,
                    priority INTEGER NOT NULL DEFAULT 10,
                    status TEXT NOT NULL DEFAULT 'QUEUED',
                    current_stage TEXT NOT NULL DEFAULT 'PENDING',
                    worker_id TEXT,
                    manifest_data TEXT,
                    output_audio_path TEXT,
                    output_video_path TEXT,
                    local_tokens_saved INTEGER NOT NULL DEFAULT 0,
                    generation_seconds REAL NOT NULL DEFAULT 0.0,
                    error_message TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factory_workers (
                    worker_id TEXT PRIMARY KEY,
                    job_id INTEGER,
                    current_stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_heartbeat REAL NOT NULL,
                    metadata TEXT
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_priority ON content_jobs (status, priority DESC, id ASC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_batch ON content_jobs (batch_name);")

    def enqueue_job(self, job: ContentJob) -> int:
        conn = self._get_conn()
        now = time.time()
        chars_json = json.dumps(job.characters)
        manifest_json = json.dumps(job.manifest_data) if job.manifest_data else None

        with conn:
            cur = conn.execute(
                """
                INSERT INTO content_jobs (
                    batch_name, title, prompt, content_type, characters,
                    target_duration_s, priority, status, current_stage,
                    manifest_data, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.batch_name,
                    job.title,
                    job.prompt,
                    job.content_type,
                    chars_json,
                    job.target_duration_s,
                    job.priority,
                    JobStatus.QUEUED.value,
                    "PENDING",
                    manifest_json,
                    now,
                    now,
                ),
            )
            job.id = cur.lastrowid
            return cur.lastrowid

    def enqueue_batch(self, jobs: List[ContentJob], batch_name: str = "batch") -> int:
        count = 0
        for j in jobs:
            j.batch_name = batch_name
            self.enqueue_job(j)
            count += 1
        return count

    def pop_next_job(self, worker_id: str, max_retries: int = 3) -> Optional[ContentJob]:
        """Atomically pop the highest-priority QUEUED job for the given worker with contention backoff."""
        conn = self._get_conn()
        for attempt in range(max_retries):
            now = time.time()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.execute(
                    """
                    SELECT id FROM content_jobs
                    WHERE status = 'QUEUED'
                    ORDER BY priority DESC, id ASC
                    LIMIT 1;
                    """
                )
                row = cur.fetchone()
                if not row:
                    conn.execute("COMMIT;")
                    return None

                job_id = row["id"]
                conn.execute(
                    """
                    UPDATE content_jobs
                    SET status = 'SCRIPTING',
                        current_stage = 'SCRIPTING',
                        worker_id = ?,
                        updated_at = ?
                    WHERE id = ?;
                    """,
                    (worker_id, now, job_id),
                )
                conn.execute("COMMIT;")
                return self.get_job(job_id)
            except sqlite3.OperationalError as e:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                if attempt < max_retries - 1:
                    jitter = 0.010 + (random.random() * 0.040)
                    time.sleep(jitter)
                else:
                    logger.debug(f"Queue busy during pop_next_job (exhausted {max_retries} attempts): {e}")
                    return None
        return None

    def get_job(self, job_id: int) -> Optional[ContentJob]:
        conn = self._get_conn()
        cur = conn.execute("SELECT * FROM content_jobs WHERE id = ?;", (job_id,))
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_job(row)

    def update_job_stage(
        self,
        job_id: int,
        stage: str,
        status: Optional[str] = None,
        manifest_data: Optional[Dict[str, Any]] = None,
        audio_path: Optional[str] = None,
        video_path: Optional[str] = None,
        tokens_saved: int = 0,
        generation_seconds: float = 0.0,
        error_message: Optional[str] = None,
    ) -> None:
        conn = self._get_conn()
        now = time.time()
        completed_at = now if status in (JobStatus.COMPLETED.value, JobStatus.FAILED.value) else None

        fields = ["current_stage = ?", "updated_at = ?"]
        params: List[Any] = [stage, now]

        if status:
            fields.append("status = ?")
            params.append(status)
        if completed_at:
            fields.append("completed_at = ?")
            params.append(completed_at)
        if manifest_data is not None:
            fields.append("manifest_data = ?")
            params.append(json.dumps(manifest_data))
        if audio_path is not None:
            fields.append("output_audio_path = ?")
            params.append(audio_path)
        if video_path is not None:
            fields.append("output_video_path = ?")
            params.append(video_path)
        if tokens_saved > 0:
            fields.append("local_tokens_saved = local_tokens_saved + ?")
            params.append(tokens_saved)
        if generation_seconds > 0:
            fields.append("generation_seconds = generation_seconds + ?")
            params.append(generation_seconds)
        if error_message is not None:
            fields.append("error_message = ?")
            params.append(error_message)

        params.append(job_id)
        sql = f"UPDATE content_jobs SET {', '.join(fields)} WHERE id = ?;"

        with conn:
            conn.execute(sql, tuple(params))

    def update_worker_heartbeat(
        self,
        worker_id: str,
        current_stage: str,
        status: str,
        job_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        min_interval_s: float = 5.0,
    ) -> None:
        now = time.time()
        last_hb, last_key = self._worker_heartbeats.get(worker_id, (0.0, None))
        current_key = (status, current_stage, job_id)
        # Rate-limit writes only if status, stage, and job_id are identical and min_interval has not elapsed
        if (current_key == last_key) and (now - last_hb < min_interval_s):
            return

        self._worker_heartbeats[worker_id] = (now, current_key)
        conn = self._get_conn()
        meta_str = json.dumps(metadata or {})
        with conn:
            conn.execute(
                """
                INSERT INTO factory_workers (worker_id, job_id, current_stage, status, last_heartbeat, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    job_id = excluded.job_id,
                    current_stage = excluded.current_stage,
                    status = excluded.status,
                    last_heartbeat = excluded.last_heartbeat,
                    metadata = excluded.metadata;
                """,
                (worker_id, job_id, current_stage, status, now, meta_str),
            )

    def query_queue_counts(self) -> Dict[str, int]:
        conn = self._get_conn()
        cur = conn.execute("SELECT status, COUNT(*) as cnt FROM content_jobs GROUP BY status;")
        counts = {r["status"]: r["cnt"] for r in cur.fetchall()}
        total = sum(counts.values())
        return {
            "QUEUED": counts.get(JobStatus.QUEUED.value, 0),
            "SCRIPTING": counts.get(JobStatus.SCRIPTING.value, 0),
            "AUDIO_GEN": counts.get(JobStatus.AUDIO_GEN.value, 0),
            "RENDERING": counts.get(JobStatus.RENDERING.value, 0),
            "COMPLETED": counts.get(JobStatus.COMPLETED.value, 0),
            "FAILED": counts.get(JobStatus.FAILED.value, 0),
            "TOTAL": total,
        }

    def query_recent_jobs(self, limit: int = 15) -> List[ContentJob]:
        conn = self._get_conn()
        cur = conn.execute("SELECT * FROM content_jobs ORDER BY id DESC LIMIT ?;", (limit,))
        return [self._row_to_job(r) for r in cur.fetchall()]

    def query_active_workers(self) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cur = conn.execute("SELECT * FROM factory_workers WHERE last_heartbeat > ? ORDER BY last_heartbeat DESC;", (time.time() - 30.0,))
        res = []
        for r in cur.fetchall():
            res.append({
                "worker_id": r["worker_id"],
                "job_id": r["job_id"],
                "current_stage": r["current_stage"],
                "status": r["status"],
                "last_heartbeat": r["last_heartbeat"],
                "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
            })
        return res

    def query_aggregate_metrics(self) -> Dict[str, Any]:
        conn = self._get_conn()
        cur = conn.execute(
            """
            SELECT 
                COUNT(*) as total_completed,
                SUM(local_tokens_saved) as total_tokens_saved,
                AVG(generation_seconds) as avg_speed_s
            FROM content_jobs
            WHERE status = 'COMPLETED';
            """
        )
        row = cur.fetchone()
        return {
            "completed": row["total_completed"] or 0,
            "tokens_saved": row["total_tokens_saved"] or 0,
            "avg_speed_s": round(row["avg_speed_s"] or 0.0, 2),
        }

    def _row_to_job(self, r: sqlite3.Row) -> ContentJob:
        chars = json.loads(r["characters"]) if r["characters"] else []
        manifest = json.loads(r["manifest_data"]) if r["manifest_data"] else None
        return ContentJob(
            id=r["id"],
            batch_name=r["batch_name"],
            title=r["title"],
            prompt=r["prompt"],
            content_type=r["content_type"],
            characters=chars,
            target_duration_s=r["target_duration_s"],
            priority=r["priority"],
            status=r["status"],
            current_stage=r["current_stage"],
            worker_id=r["worker_id"],
            manifest_data=manifest,
            output_audio_path=r["output_audio_path"],
            output_video_path=r["output_video_path"],
            local_tokens_saved=r["local_tokens_saved"],
            generation_seconds=r["generation_seconds"],
            error_message=r["error_message"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            completed_at=r["completed_at"],
        )
