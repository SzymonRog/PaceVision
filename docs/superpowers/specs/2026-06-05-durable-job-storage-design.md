# Durable Job Storage — Design

**Date:** 2026-06-05
**Status:** Approved, implementing
**Area:** `backend/` job persistence

## Problem

All job state and output files currently live in **one process's RAM + local
`/tmp`** (`JobManager._jobs` dict in `jobs/manager.py`; temp files under
`<tmp>/pacevision_jobs`). Any crash, OOM kill, redeploy, or restart wipes the
registry, so subsequent polls of `/status` and `/result` return `404` for a
job that was successfully submitted.

Observed in production: a single Railway replica returning `connection refused`
(process restarting — almost certainly an OOM during MediaPipe processing),
after which every poll 404s.

## Goals

- Job state and the annotated video survive process restarts.
- Short-lived **shareable links**, no login: a result is reachable via its
  unguessable URL for a fixed window, then auto-expires.
- **24h** auto-expire + a **manual "delete now"** control.
- Privacy: the **raw upload is deleted the moment processing finishes**; only
  the annotated output + derived data persist for the window.
- Stay on **Railway volume only** — no extra managed services.

## Non-goals

- Horizontal scaling / multiple replicas (the design remains single-instance;
  files + processing are pinned to one volume/process).
- User accounts or auth.
- Fixing the underlying OOM (tracked as a follow-up; see below).

## Storage approach

**SQLite on the volume + MP4 as a file** (chosen over flat-files-only for
atomic writes and a clean expiry query; chosen over a single JSON index to
avoid rewrite contention/corruption).

### Volume layout (mounted at `/data`)

```
/data/
  pacevision.db                 # SQLite (WAL) — source of truth for job state
  jobs/<job_id>/
      input.<ext>               # raw upload — DELETED when processing finishes
      output.mp4                # annotated video — kept for the 24h window
```

### Data model — table `jobs`

| Column | Type | Notes |
|---|---|---|
| `job_id` | TEXT PRIMARY KEY | existing unguessable 128-bit hex |
| `status` | TEXT | queued / processing / completed / failed |
| `created_at` | INTEGER | epoch seconds |
| `finished_at` | INTEGER NULL | epoch seconds |
| `expires_at` | INTEGER NULL | `finished_at + job_ttl_sec`; drives the sweep |
| `total_frames` | INTEGER | |
| `analyzed_frames` | INTEGER | |
| `input_ext` | TEXT | extension of the raw upload, for path reconstruction |
| `result_json` | TEXT NULL | full `AnalysisResult` (`model_dump_json`) — keeps the `contact_method` recompute working from cached `frame_angles` |
| `error` | TEXT NULL | |
| `has_video` | INTEGER | 0/1 |

**Progress is NOT persisted.** Writing every frame-batch tick to SQLite would
cause write amplification, and progress only matters for an in-flight job in
this single-worker process. Progress lives in a small in-memory dict keyed by
`job_id`; `get_job` overlays it onto the durable row when the job is
processing.

### Concurrency

One SQLite connection opened with `check_same_thread=False`, WAL mode, guarded
by a single `threading.Lock` around all DB operations (mirrors the existing
lock-based design). The thread-pool worker writes status/result; the async API
handlers read. Throughput is low, so a single lock is sufficient and simplest.

## `JobManager` interface (refactored, same callers)

Existing methods keep their signatures so `routes_analyze.py` /
`routes_health.py` change minimally:

- `create_job(input_ext) -> _Job` — allocate id, `mkdir jobs/<id>/`, `INSERT
  status=queued`, return a `_Job` read-model with `input_path`/`output_path`
  derived from the job dir.
- `get_job(job_id) -> _Job | None` — `SELECT` row (404 if absent), overlay live
  progress; **does not** parse `result_json` (cheap for frequent status polls).
- `mark_processing(job_id, total_frames)`
- `update_progress(job_id, done, total)` — in-memory only.
- `mark_completed(job_id, result)` — `UPDATE` status/result_json/finished_at/
  `expires_at`/has_video; delete `input.<ext>`; clear in-memory progress.
- `mark_failed(job_id, error)` — `UPDATE`; delete input + partial output.
- `count_unfinished() -> int`
- `cleanup_stale() -> int` — `SELECT` then `DELETE` rows where
  `expires_at < now`; `rm -rf` their dirs.

New methods:

- `get_result(job_id) -> AnalysisResult | None` — parse `result_json` (used
  only by the result + notebook endpoints).
- `delete_job(job_id) -> bool` — `DELETE` row + `rm -rf jobs/<id>` (manual
  delete).
- `recover_on_startup()` — see below.
- `shutdown()` — **close the connection only. Must NOT delete the volume**
  (today's `shutil.rmtree` is removed).

## Crash recovery

`recover_on_startup()` runs in the lifespan startup hook:

1. Any row still `queued`/`processing` is orphaned (single worker → nothing
   survived the restart) → mark `failed`, `error="Analysis interrupted by a
   server restart. Please try again."`, set `finished_at`/`expires_at`, delete
   its input/partial files.
2. Purge expired rows (`expires_at < now`) and their dirs.
3. Remove orphan `jobs/<id>/` dirs with no matching DB row.

Effect: after an OOM/restart, a poll returns a clean `422 failed` ("please
retry") instead of a `404` or an infinite-pending hang.

The periodic `_cleanup_loop` continues to call `cleanup_stale()` on its
interval.

## Data flow

1. **POST** → validate → `create_job(ext)` → save upload to `job.input_path` →
   dispatch to thread pool → return `job_id` (`202`).
2. **Worker** → `mark_processing`; run pipeline (writes `output.mp4`); on
   success `mark_completed` (+ delete input); on failure `mark_failed`
   (+ delete input & partial output).
3. **GET `/status`** → `get_job`; SSE (unchanged shape).
4. **GET `/result`** → `get_job` for state, `get_result` for payload;
   `contact_method` recompute unchanged.
5. **GET `/video`** → stream `jobs/<id>/output.mp4` via `FileResponse` (Range
   support unchanged).
6. **DELETE `/api/analyze-video/{id}`** (new) → `delete_job`, return `204`.

Expired/missing → `404` (unguessable IDs mean we needn't distinguish
"expired" from "never existed", which avoids leaking existence).

## Config & deploy

- `core/config.py`: add `data_dir` (env `PACE_DATA_DIR`, default `/data`;
  falls back to a temp dir when `/data` is not writable so local `--reload`
  works), bump `job_ttl_sec` default to `86400` (24h).
- Railway: attach a volume mounted at `/data`; `Dockerfile` sets
  `ENV PACE_DATA_DIR=/data`. Size for ~(videos/day × avg MP4 size); 24h TTL +
  existing `max_active_jobs` admission control keep usage bounded.

## Frontend (small, can follow)

The `/results/[id]` page is now durably shareable for 24h. Add a "Delete now"
button (calls `DELETE`) and optionally an "available until …" line. Not
required for the backend change to land.

## Testing

- **Unit:** `JobManager` CRUD against a temp DB; expiry query; orphaned
  `queued`/`processing` → `failed` recovery; `delete_job` removes row + dir;
  `get_result` round-trips an `AnalysisResult`.
- **Integration:** submit → status → result → video → delete on a tiny fixture
  video; simulate restart by opening a fresh `JobManager` over the same DB and
  asserting orphan→failed + expired purged.

## Follow-up (out of scope)

The likely **OOM crash** itself is not addressed here — durable storage makes a
crash *survivable* (job → failed, user retries) rather than a silent 404. If
crashes persist, address memory separately: lower MediaPipe `model_complexity`
/ switch off the heavy model, cap detection resolution, or raise the Railway
plan's memory.
