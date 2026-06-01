"""In-memory job manager for asynchronous video analysis.

Each job tracks its lifecycle (queued → processing → completed/failed),
progress percentage, result data, and output file path.  Jobs are stored
in a dict protected by a threading lock so that the background worker
thread and the async API handlers can access them safely.

Old completed/failed jobs are cleaned up after a configurable TTL so
that temp files don't accumulate.
"""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.config import settings
from schemas.analyze import (
    AnalysisResult,
    FrameAngles,
    AngleSummary,
    JobStatus,
)


@dataclass
class _Job:
    """Internal mutable job record."""

    job_id: str
    status: JobStatus = JobStatus.queued
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None

    # Progress
    progress_pct: float = 0.0
    frames_processed: int = 0
    total_frames: int = 0

    # Input / output paths (temp files)
    input_path: Path | None = None
    output_path: Path | None = None

    # Result (populated on completion)
    result: AnalysisResult | None = None
    error: str | None = None


class JobManager:
    """Thread-safe registry for video analysis jobs."""

    def __init__(self, temp_dir: Path) -> None:
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()
        self._temp_dir = temp_dir
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    # ── job lifecycle ─────────────────────────────────────────────────

    def create_job(self, input_path: Path) -> _Job:
        """Register a new job and return it."""
        # Full 128-bit UUID — unguessable so results/videos can't be
        # enumerated by a third party (IDOR protection).
        job_id = uuid.uuid4().hex
        output_path = self._temp_dir / f"{job_id}_output.mp4"

        job = _Job(
            job_id=job_id,
            input_path=input_path,
            output_path=output_path,
        )
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> _Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def count_unfinished(self) -> int:
        """Number of jobs still queued or processing (for admission control)."""
        with self._lock:
            return sum(
                1 for j in self._jobs.values()
                if j.status in (JobStatus.queued, JobStatus.processing)
            )

    def mark_processing(self, job_id: str, total_frames: int) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = JobStatus.processing
                job.total_frames = total_frames

    def update_progress(self, job_id: str, frames_done: int, total: int) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.frames_processed = frames_done
                job.total_frames = total
                job.progress_pct = round((frames_done / max(total, 1)) * 100, 1)

    def mark_completed(self, job_id: str, result: AnalysisResult) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = JobStatus.completed
                job.result = result
                job.finished_at = datetime.now(timezone.utc)
                job.progress_pct = 100.0
                # Clean up the uploaded input file
                if job.input_path and job.input_path.exists():
                    job.input_path.unlink(missing_ok=True)

    def mark_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = JobStatus.failed
                job.error = error
                job.finished_at = datetime.now(timezone.utc)
                # Clean up both files on failure
                if job.input_path and job.input_path.exists():
                    job.input_path.unlink(missing_ok=True)
                if job.output_path and job.output_path.exists():
                    job.output_path.unlink(missing_ok=True)

    # ── cleanup ───────────────────────────────────────────────────────

    def cleanup_stale(self) -> int:
        """Remove jobs older than TTL. Returns count of removed jobs."""
        now = time.time()
        to_remove: list[str] = []
        with self._lock:
            for jid, job in self._jobs.items():
                if job.finished_at is None:
                    continue
                age = now - job.finished_at.timestamp()
                if age > settings.job_ttl_sec:
                    to_remove.append(jid)

            for jid in to_remove:
                job = self._jobs.pop(jid)
                if job.output_path and job.output_path.exists():
                    job.output_path.unlink(missing_ok=True)
                if job.input_path and job.input_path.exists():
                    job.input_path.unlink(missing_ok=True)

        return len(to_remove)

    def shutdown(self) -> None:
        """Clean up all temp files on application shutdown."""
        if self._temp_dir.exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
