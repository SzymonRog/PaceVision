"""REST endpoints for offline video analysis.

Flow:
  1. POST /api/analyze-video      — upload video, returns job_id
  2. GET  /api/analyze-video/{id}/status  — SSE progress stream
  3. GET  /api/analyze-video/{id}/result  — JSON analysis results
  4. GET  /api/analyze-video/{id}/video   — download annotated MP4
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse

from analysis.stride_detector import CONTACT_METHODS, DEFAULT_CONTACT_METHOD
from analysis.video_pipeline import (
    VideoPipeline,
    analyze_strides_and_form,
    summarize_angles,
)
from core.config import settings
from jobs.manager import JobManager
from schemas.analyze import (
    AnalysisResult,
    AnalyzeVideoResponse,
    JobProgress,
    JobStatus,
)

logger = logging.getLogger("pacevision.analyze")

router = APIRouter(prefix="/api/analyze-video", tags=["analyze-video"])

# Limits
_MAX_FILE_SIZE = settings.max_upload_mb * 1024 * 1024
_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
_CHUNK_SIZE = 256 * 1024  # 256 KB read chunks

# Shared thread pool for CPU-bound video processing (bounded to avoid OOM)
_executor = ThreadPoolExecutor(
    max_workers=settings.analysis_workers, thread_name_prefix="video-analyze",
)


def _validate_upload(file: UploadFile) -> None:
    """Reject files that are clearly not videos or too large."""
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")

    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )

    # Content-type sniff (best effort — not authoritative)
    ct = (file.content_type or "").lower()
    if ct and not ct.startswith("video/") and ct != "application/octet-stream":
        raise HTTPException(status_code=400, detail=f"Expected video content type, got '{ct}'")


async def _save_upload(file: UploadFile, dest: Path) -> int:
    """Stream upload to disk in chunks. Returns bytes written."""
    total = 0
    with open(dest, "wb") as f:
        while True:
            chunk = await file.read(_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_FILE_SIZE:
                # Clean up partial file
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum size is {_MAX_FILE_SIZE // (1024*1024)} MB",
                )
            f.write(chunk)
    return total


def _run_pipeline(
    job_manager: JobManager,
    job_id: str,
    input_path: str,
    output_path: str,
    skip_frames: int,
    detection_height: int | None,
) -> None:
    """Synchronous worker — runs in the thread pool."""
    def on_progress(done: int, total: int) -> None:
        job_manager.update_progress(job_id, done, total)

    try:
        pipeline = VideoPipeline(
            skip_frames=skip_frames,
            detection_height=detection_height,
            progress_callback=on_progress,
        )
        frame_angles, duration, total, analyzed, fps, stride_events, stride_summaries, form_analysis = pipeline.run(
            input_path, output_path,
        )

        speed_band = form_analysis.speed_band if form_analysis else "moderate"
        summary = summarize_angles(frame_angles, stride_events, speed_band=speed_band)

        result = AnalysisResult(
            job_id=job_id,
            status=JobStatus.completed,
            duration_sec=round(duration, 2),
            total_frames=total,
            analyzed_frames=analyzed,
            video_fps=fps,
            frame_angles=frame_angles,
            summary=summary,
            stride_events=stride_events,
            stride_summary=stride_summaries,
            form_analysis=form_analysis,
            has_video=Path(output_path).exists(),
        )
        job_manager.mark_completed(job_id, result)

    except Exception:
        # Log the full traceback server-side; return a generic message to the
        # client so internal paths/details aren't leaked.
        logger.exception("Video analysis failed for job %s", job_id)
        job_manager.mark_failed(
            job_id, "Video analysis failed. Please check the input and try again.",
        )


# ── endpoints ─────────────────────────────────────────────────────────


@router.post("", response_model=AnalyzeVideoResponse, status_code=202)
async def submit_video(
    request: Request,
    file: UploadFile = File(...),
    skip_frames: int = Query(default=1, ge=1, le=10, description="Process every Nth frame"),
    detection_height: int | None = Query(
        default=None, ge=240, le=1080,
        description="Resize height for detection (None = original)",
    ),
) -> AnalyzeVideoResponse:
    """Upload a video for asynchronous pose analysis.

    Returns a job ID to poll for progress and results.
    """
    _validate_upload(file)

    job_manager: JobManager = request.app.state.job_manager

    # Admission control — bound queued/processing jobs to protect disk + memory.
    if job_manager.count_unfinished() >= settings.max_active_jobs:
        raise HTTPException(
            status_code=429,
            detail="Server is busy processing other videos. Please retry shortly.",
        )

    # Save upload to temp file
    ext = Path(file.filename).suffix.lower()  # type: ignore[arg-type]
    temp_dir = job_manager._temp_dir
    input_path = temp_dir / f"upload_{uuid.uuid4().hex[:12]}{ext}"
    await _save_upload(file, input_path)

    job = job_manager.create_job(input_path)
    job.input_path = input_path

    # Submit to thread pool
    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor,
        _run_pipeline,
        job_manager,
        job.job_id,
        str(input_path),
        str(job.output_path),
        skip_frames,
        detection_height,
    )

    return AnalyzeVideoResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at,
    )


@router.get("/{job_id}/status")
async def job_status_sse(job_id: str, request: Request) -> StreamingResponse:
    """Server-Sent Events stream of job progress.

    Sends progress updates every 500ms until the job completes or fails,
    then sends a final event and closes.
    """
    job_manager: JobManager = request.app.state.job_manager
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    async def event_stream():
        while True:
            j = job_manager.get_job(job_id)
            if j is None:
                yield f"event: error\ndata: Job not found\n\n"
                break

            progress = JobProgress(
                job_id=j.job_id,
                status=j.status,
                progress_pct=j.progress_pct,
                frames_processed=j.frames_processed,
                total_frames=j.total_frames,
                error=j.error,
            )
            yield f"data: {progress.model_dump_json()}\n\n"

            if j.status in (JobStatus.completed, JobStatus.failed):
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{job_id}/result", response_model=AnalysisResult)
async def get_result(
    job_id: str,
    request: Request,
    contact_method: str = Query(
        default=DEFAULT_CONTACT_METHOD,
        description=f"Initial-contact detection method. One of: {', '.join(CONTACT_METHODS)}",
    ),
) -> AnalysisResult:
    """Get the full analysis results for a completed job.

    ``contact_method`` re-derives the initial-contact frames (and therefore
    the contact-phase angle ratings, strides, and form problems) from the
    cached per-frame data — no re-upload or re-processing.  The annotated
    video keeps the overlay baked with the default method.
    """
    if contact_method not in CONTACT_METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown contact_method '{contact_method}'. "
                   f"Allowed: {', '.join(CONTACT_METHODS)}",
        )

    job_manager: JobManager = request.app.state.job_manager
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.status == JobStatus.failed:
        raise HTTPException(status_code=422, detail=f"Analysis failed: {job.error}")

    if job.status in (JobStatus.queued, JobStatus.processing):
        raise HTTPException(status_code=409, detail="Analysis still in progress")

    if job.result is None:
        raise HTTPException(status_code=500, detail="Result missing")

    base = job.result
    if contact_method == DEFAULT_CONTACT_METHOD:
        return base

    # Recompute strides/form/summary from cached per-frame data (cheap).
    events, summaries, form = analyze_strides_and_form(
        base.frame_angles, base.video_fps, contact_method=contact_method,
    )
    speed_band = form.speed_band if form else "moderate"
    summary = summarize_angles(base.frame_angles, events, speed_band=speed_band)

    return base.model_copy(update={
        "summary": summary,
        "stride_events": events,
        "stride_summary": summaries,
        "form_analysis": form,
    })


@router.get("/{job_id}/video")
async def download_video(job_id: str, request: Request) -> FileResponse:
    """Download the annotated output video."""
    job_manager: JobManager = request.app.state.job_manager
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.status != JobStatus.completed:
        raise HTTPException(status_code=409, detail="Analysis not yet completed")

    if job.output_path is None or not job.output_path.exists():
        raise HTTPException(status_code=404, detail="Output video not found")

    # Serve inline (NOT as an attachment) so the <video> element can play and
    # seek it. The frontend's download button uses an <a download> anchor, which
    # forces a download regardless, so inline here does not break downloads.
    # FileResponse honours HTTP Range requests automatically, which the browser
    # needs for scrubbing.
    return FileResponse(
        path=str(job.output_path),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'inline; filename="pacevision_{job_id}.mp4"',
            "Accept-Ranges": "bytes",
        },
    )


@router.get("/{job_id}/notebook")
async def download_notebook(job_id: str, request: Request) -> StreamingResponse:
    """Generate and download a Jupyter notebook with analysis plots."""
    from analysis.notebook_generator import generate_notebook
    import nbformat as nbf

    job_manager: JobManager = request.app.state.job_manager
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.status != JobStatus.completed:
        raise HTTPException(status_code=409, detail="Analysis not yet completed")

    if job.result is None:
        raise HTTPException(status_code=500, detail="Result missing")

    nb = generate_notebook(job.result)
    content = nbf.writes(nb)

    return StreamingResponse(
        iter([content]),
        media_type="application/x-ipynb+json",
        headers={
            "Content-Disposition": f'attachment; filename="pacevision_{job_id}.ipynb"',
        },
    )
