"""Durable job manager for asynchronous video analysis.

Job state is persisted in a SQLite database on a mounted volume so that it
survives process restarts, OOM kills, and redeploys.  Each job tracks its
lifecycle (queued → processing → completed/failed), result data, and output
file path.  The annotated video is stored as a file alongside the database;
the raw upload is deleted as soon as processing finishes.

Live progress (the per-frame counter shown over SSE) is intentionally kept in
memory only — it changes too often to persist, and is meaningful solely for an
in-flight job in this single-worker process.

Completed/failed jobs auto-expire after a configurable TTL, which also powers
short-lived shareable result links.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.config import settings
from schemas.analyze import AnalysisResult, JobStatus

logger = logging.getLogger("pacevision.jobs")

_UNFINISHED = (JobStatus.queued.value, JobStatus.processing.value)


@dataclass
class _Job:
    """Read-model for a job, assembled from a DB row + live progress."""

    job_id: str
    status: JobStatus
    created_at: datetime
    finished_at: datetime | None = None

    progress_pct: float = 0.0
    frames_processed: int = 0
    total_frames: int = 0

    input_path: Path | None = None
    output_path: Path | None = None

    # Populated only by get_result() — get_job() leaves this None so frequent
    # status polls don't pay to parse a multi-MB result blob.
    result: AnalysisResult | None = None
    error: str | None = None


def _now() -> int:
    return int(time.time())


def _to_dt(epoch: int | None) -> datetime | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


class JobManager:
    """Thread-safe, SQLite-backed registry for video analysis jobs."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = self._resolve_writable_dir(data_dir)
        self._jobs_dir = self._data_dir / "jobs"
        self._jobs_dir.mkdir(parents=True, exist_ok=True)

        db_path = self._data_dir / "pacevision.db"
        # check_same_thread=False: the thread-pool worker and the async API
        # handlers (event-loop thread) both touch the connection. All access is
        # serialized by self._lock, so a single connection is safe.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.Lock()
        self._progress: dict[str, tuple[int, int, float]] = {}  # id -> (done, total, pct)
        self._init_schema()

    @staticmethod
    def _resolve_writable_dir(data_dir: Path) -> Path:
        """Use ``data_dir`` if writable; otherwise fall back to a temp dir.

        Production mounts a volume at ``/data``. Local dev (and tests) may not
        have that path, so degrade gracefully instead of crashing on startup.
        """
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            probe = data_dir / ".write_test"
            probe.touch()
            probe.unlink(missing_ok=True)
            return data_dir
        except OSError:
            import tempfile

            fallback = Path(tempfile.gettempdir()) / "pacevision_jobs"
            logger.warning(
                "data_dir %s not writable; falling back to %s (state will NOT "
                "survive restarts)", data_dir, fallback,
            )
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id          TEXT PRIMARY KEY,
                    status          TEXT NOT NULL,
                    created_at      INTEGER NOT NULL,
                    finished_at     INTEGER,
                    expires_at      INTEGER,
                    total_frames    INTEGER NOT NULL DEFAULT 0,
                    analyzed_frames INTEGER NOT NULL DEFAULT 0,
                    input_ext       TEXT NOT NULL DEFAULT '',
                    result_json     TEXT,
                    error           TEXT,
                    has_video       INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_expires ON jobs(expires_at)"
            )
            self._conn.commit()

    # ── paths ─────────────────────────────────────────────────────────

    def _job_dir(self, job_id: str) -> Path:
        return self._jobs_dir / job_id

    def _input_path(self, job_id: str, input_ext: str) -> Path | None:
        if not input_ext:
            return None
        return self._job_dir(job_id) / f"input{input_ext}"

    def _output_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "output.mp4"

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    # ── job lifecycle ─────────────────────────────────────────────────

    def create_job(self, input_ext: str) -> _Job:
        """Register a new job, create its directory, and return it.

        ``input_ext`` is the upload's suffix (e.g. ``.mp4``), used to build the
        path the caller should stream the upload into.
        """
        # Full 128-bit UUID — unguessable so results/videos can't be
        # enumerated by a third party (IDOR protection).
        job_id = uuid.uuid4().hex
        self._job_dir(job_id).mkdir(parents=True, exist_ok=True)
        created = _now()

        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (job_id, status, created_at, input_ext) "
                "VALUES (?, ?, ?, ?)",
                (job_id, JobStatus.queued.value, created, input_ext),
            )
            self._conn.commit()

        return _Job(
            job_id=job_id,
            status=JobStatus.queued,
            created_at=_to_dt(created),  # type: ignore[arg-type]
            input_path=self._input_path(job_id, input_ext),
            output_path=self._output_path(job_id),
        )

    def get_job(self, job_id: str) -> _Job | None:
        """Return job state (without the heavy result payload), or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT status, created_at, finished_at, total_frames, "
                "input_ext FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            progress = self._progress.get(job_id)

        if row is None:
            return None

        status_str, created_at, finished_at, total_frames, input_ext = row
        done, total, pct = progress if progress else (0, total_frames, 0.0)
        if JobStatus(status_str) == JobStatus.completed:
            pct = 100.0

        return _Job(
            job_id=job_id,
            status=JobStatus(status_str),
            created_at=_to_dt(created_at),  # type: ignore[arg-type]
            finished_at=_to_dt(finished_at),
            progress_pct=pct,
            frames_processed=done,
            total_frames=total or total_frames,
            input_path=self._input_path(job_id, input_ext),
            output_path=self._output_path(job_id),
            error=self._error_for(job_id),
        )

    def _error_for(self, job_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT error FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return row[0] if row else None

    def get_result(self, job_id: str) -> AnalysisResult | None:
        """Parse and return the stored AnalysisResult, or None if absent."""
        with self._lock:
            row = self._conn.execute(
                "SELECT result_json FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if not row or row[0] is None:
            return None
        return AnalysisResult.model_validate_json(row[0])

    def count_unfinished(self) -> int:
        """Number of jobs still queued or processing (for admission control)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN (?, ?)", _UNFINISHED
            ).fetchone()
        return int(row[0]) if row else 0

    def mark_processing(self, job_id: str, total_frames: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = ?, total_frames = ? WHERE job_id = ?",
                (JobStatus.processing.value, total_frames, job_id),
            )
            self._conn.commit()
            self._progress[job_id] = (0, total_frames, 0.0)

    def update_progress(self, job_id: str, frames_done: int, total: int) -> None:
        # In-memory only — see module docstring.
        pct = round((frames_done / max(total, 1)) * 100, 1)
        with self._lock:
            self._progress[job_id] = (frames_done, total, pct)

    def mark_completed(self, job_id: str, result: AnalysisResult) -> None:
        finished = _now()
        expires = finished + settings.job_ttl_sec
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = ?, result_json = ?, finished_at = ?, "
                "expires_at = ?, analyzed_frames = ?, has_video = ? "
                "WHERE job_id = ?",
                (
                    JobStatus.completed.value,
                    result.model_dump_json(),
                    finished,
                    expires,
                    result.analyzed_frames,
                    1 if result.has_video else 0,
                    job_id,
                ),
            )
            self._conn.commit()
            self._progress.pop(job_id, None)
        # Drop the raw upload as soon as we're done with it (privacy).
        self._delete_input(job_id)

    def mark_failed(self, job_id: str, error: str) -> None:
        finished = _now()
        expires = finished + settings.job_ttl_sec
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = ?, error = ?, finished_at = ?, "
                "expires_at = ? WHERE job_id = ?",
                (JobStatus.failed.value, error, finished, expires, job_id),
            )
            self._conn.commit()
            self._progress.pop(job_id, None)
        # Clean up both files on failure.
        self._delete_input(job_id)
        self._output_path(job_id).unlink(missing_ok=True)

    def delete_job(self, job_id: str) -> bool:
        """Manually delete a job and all its files. Returns False if unknown."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM jobs WHERE job_id = ?", (job_id,)
            )
            self._conn.commit()
            self._progress.pop(job_id, None)
            existed = cur.rowcount > 0
        shutil.rmtree(self._job_dir(job_id), ignore_errors=True)
        return existed

    def _delete_input(self, job_id: str) -> None:
        for child in self._job_dir(job_id).glob("input.*"):
            child.unlink(missing_ok=True)

    # ── cleanup & recovery ────────────────────────────────────────────

    def cleanup_stale(self) -> int:
        """Remove jobs past their TTL. Returns count of removed jobs."""
        now = _now()
        with self._lock:
            rows = self._conn.execute(
                "SELECT job_id FROM jobs WHERE expires_at IS NOT NULL "
                "AND expires_at < ?",
                (now,),
            ).fetchall()
            ids = [r[0] for r in rows]
            if ids:
                self._conn.executemany(
                    "DELETE FROM jobs WHERE job_id = ?", [(i,) for i in ids]
                )
                self._conn.commit()
            for jid in ids:
                self._progress.pop(jid, None)

        for jid in ids:
            shutil.rmtree(self._job_dir(jid), ignore_errors=True)
        return len(ids)

    def recover_on_startup(self) -> None:
        """Reconcile durable state after a (re)start.

        1. Jobs left ``queued``/``processing`` are orphaned (single worker —
           nothing survived the restart) → fail them so callers see a clean
           error instead of a perpetual pending or a 404.
        2. Purge expired jobs.
        3. Remove orphan job directories with no matching row.
        """
        now = _now()
        expires = now + settings.job_ttl_sec
        interrupted = (
            "Analysis interrupted by a server restart. Please try again."
        )
        with self._lock:
            orphans = self._conn.execute(
                "SELECT job_id FROM jobs WHERE status IN (?, ?)", _UNFINISHED
            ).fetchall()
            orphan_ids = [r[0] for r in orphans]
            if orphan_ids:
                self._conn.executemany(
                    "UPDATE jobs SET status = ?, error = ?, finished_at = ?, "
                    "expires_at = ? WHERE job_id = ?",
                    [
                        (JobStatus.failed.value, interrupted, now, expires, jid)
                        for jid in orphan_ids
                    ],
                )
                self._conn.commit()
            known = {
                r[0]
                for r in self._conn.execute("SELECT job_id FROM jobs").fetchall()
            }
        self._progress.clear()

        for jid in orphan_ids:
            self._delete_input(jid)
            self._output_path(jid).unlink(missing_ok=True)

        # Sweep expired rows now too.
        purged = self.cleanup_stale()

        # Remove orphan directories (files with no DB row).
        orphan_dirs = 0
        if self._jobs_dir.exists():
            for child in self._jobs_dir.iterdir():
                if child.is_dir() and child.name not in known:
                    shutil.rmtree(child, ignore_errors=True)
                    orphan_dirs += 1

        if orphan_ids or purged or orphan_dirs:
            logger.info(
                "Startup recovery: failed %d interrupted job(s), purged %d "
                "expired, removed %d orphan dir(s).",
                len(orphan_ids), purged, orphan_dirs,
            )

    def shutdown(self) -> None:
        """Close the database. Does NOT delete the volume."""
        with self._lock:
            self._conn.close()
