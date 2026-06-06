# PaceVision

**AI-powered running form analysis from a single side-view video.**

Upload a clip, get an annotated video with a skeleton overlay, per-frame joint angles charted over time, detected stride events, cadence, and coaching feedback — all grounded in sports-biomechanics research.

**Live:** [pace-vision.vercel.app](https://pace-vision.vercel.app)



## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Getting Started (Local)](#getting-started-local)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Biomechanics Model](#biomechanics-model)
- [Deployment](#deployment)
- [Project Structure](#project-structure)
- [Limitations](#limitations)

---

## Features

- **Pose estimation** — MediaPipe PoseLandmarker (heavy model, VIDEO mode) extracts 33 body landmarks per frame in 3D world coordinates.
- **6 joint angles** — knee flexion, hip flexion, ankle dorsiflexion, trunk lean, arm swing, and arm drive, computed bilaterally.
- **Phase-aware stride detection** — forward-reach (Zeni 2008) algorithm with autocorrelation-based period estimation. Detects initial contact, mid-stance, and toe-off for each leg.
- **Form-fault detection** — 5 flagged problems (overstriding, heel strike, trunk lean, cadence, vertical oscillation) with self-calibration and speed-adaptive thresholds. False positives suppressed by hybrid occurrence gating.
- **Overall form score** — 0–100 composite; 100 means no problems detected.
- **Annotated video** — skeleton overlay, live joint angles, gait-phase bar, and problem banners. Served with HTTP Range so the browser can scrub.
- **Jupyter notebook** — downloadable offline analysis with per-angle plots, stride markers, and summary tables.
- **Async job model** — upload returns immediately (`202`); progress streams via SSE; results and video survive independently.
- **Real-time progress** — Server-Sent Events stream during analysis.
- **Contact method selector** — recompute strides and form analysis client-side using a different initial-contact strategy without re-uploading.

---

## Tech Stack

### Frontend

| Technology | Version | Role |
|---|---|---|
| Next.js | 14 (App Router) | React framework, SSR/SSG |
| TypeScript | 5 | Type safety |
| Tailwind CSS | 3 | Utility styling |
| shadcn/ui | — | Accessible component primitives |
| Recharts | 3 | Joint angle time-series charts |
| Zustand | 5 | Client-side analysis result store |
| Lucide React | — | Icons |

**Deployed on:** Vercel

### Backend

| Technology | Version | Role |
|---|---|---|
| Python | 3.11 | Runtime |
| FastAPI | 0.136 | REST API framework |
| MediaPipe | 0.10.35 | Pose estimation |
| OpenCV | 4.13 | Video decode/encode |
| NumPy | 2 | Array math |
| SciPy | 1.17 | Signal processing (Savitzky-Golay, peak finding) |
| Pydantic | 2 | Schema validation |
| uvicorn | 0.47 | ASGI server |
| nbformat + Jupyter | — | Notebook generation |

**Deployed on:** Railway (Docker)

---

## Architecture

### Analysis Pipeline

```
Side-view video
      │
      ▼
┌─────────────────── Pass 1: ANALYSIS ───────────────────┐
│  decode frames → MediaPipe PoseLandmarker (VIDEO mode)  │
│  → world landmarks → Savitzky-Golay smooth              │
│  → 6 joint angles per frame → FrameAngles[]             │
└──────────────────────────────────────────────────────────┘
      │
      ▼
stride detection (Zeni forward-reach + autocorrelation)
      │
      ▼
form-fault detection (phase-aware, speed-adaptive, self-calibrated)
      │
      ▼
┌─────────────────── Pass 2: RENDER ─────────────────────┐
│  re-decode video → draw skeleton + angles + phase bar   │
│  → mp4v → ffmpeg transcode → H.264 (browser-playable)  │
└──────────────────────────────────────────────────────────┘
      │
      ▼
JSON result + annotated MP4 + Jupyter notebook
```

**Why two passes?** The rich overlay (gait-phase bar, problem banners) needs forward-looking information available only after the full analysis. Buffering all decoded frames in memory causes OOM on long clips; reading the source file twice is cheap.

**Why separate the CV pass from analysis?** Pose estimation is the bottleneck — everything after it is fast math. The separation lets you change the contact-detection strategy and re-run strides + form analysis instantly, without touching the video again.

### Job Lifecycle

```
POST /api/analyze-video  →  202 { job_id }
                                    │
                         ThreadPoolExecutor worker
                                    │
GET  /api/analyze-video/{id}/status  ← SSE (every 500 ms)
GET  /api/analyze-video/{id}/result  ← JSON (after completed)
GET  /api/analyze-video/{id}/video   ← MP4 with HTTP Range
GET  /api/analyze-video/{id}/notebook ← Jupyter notebook
```

- Jobs are bounded by `PACE_MAX_ACTIVE_JOBS` (admission control → 429 when full).
- Completed jobs and their temp files are reclaimed after `PACE_JOB_TTL_SEC` (default: 1 hour).
- Job IDs are 128-bit UUIDs — unguessable, preventing enumeration (IDOR protection).

---

## Getting Started (Local)

### Prerequisites

| Tool | Version |
|---|---|
| Python | 3.11+ |
| Node.js | 20+ |
| npm | 10+ |
| ffmpeg | any recent (optional; bundled fallback via imageio-ffmpeg) |

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/PaceVision.git
cd PaceVision
```

### 2. Backend Setup

```bash
cd backend

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate          # Windows PowerShell

# Install dependencies (pinned for reproducibility)
pip install -r requirements.txt
```

**Download the MediaPipe model** (one-time, ~25 MB):

```bash
mkdir -p prototype
python - <<'EOF'
import urllib.request
url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task"
urllib.request.urlretrieve(url, "prototype/pose_landmarker_heavy.task")
print("Model downloaded.")
EOF
```

> In the Docker image this download is baked in at build time, so it never blocks the first request. Locally it runs once and is gitignored.

**Copy the environment file:**

```bash
cp .env.example .env
# All defaults work for local development — no edits needed.
```

**Start the backend:**

```bash
uvicorn main:app --reload
# → http://localhost:8000
# → http://localhost:8000/docs  (interactive Swagger UI)
```

### 3. Frontend Setup

```bash
cd frontend

npm install

# Copy environment file
cp .env.example .env.local
# NEXT_PUBLIC_API_URL=http://127.0.0.1:8000  (default, no change needed)

npm run dev
# → http://localhost:3000
```

### 4. Verify

Open [http://localhost:3000](http://localhost:3000), upload a short side-view running clip (MP4/MOV/AVI/MKV/WEBM, ≤500 MB), and watch the progress bar fill. Results appear at `/results/[id]`.

### Full-Stack with Docker Compose

```bash
# From the repo root (requires Docker)
docker-compose up
# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
```

---

## Environment Variables

### Backend (`backend/.env`)

All variables use the `PACE_` prefix.

| Variable | Default | Description |
|---|---|---|
| `PACE_CORS_ORIGINS` | `http://localhost:3000,...` | Comma-separated allowed frontend origins |
| `PACE_MAX_UPLOAD_MB` | `500` | Max video upload size in MB |
| `PACE_ANALYSIS_WORKERS` | `2` | Thread pool size (CPU-bound; keep small) |
| `PACE_MAX_ACTIVE_JOBS` | `8` | Max queued/processing jobs (admission control) |
| `PACE_JOB_TTL_SEC` | `3600` | Retention for finished jobs before cleanup (seconds) |
| `PACE_CLEANUP_INTERVAL_SEC` | `300` | Background cleanup sweep interval (seconds) |
| `PACE_MODEL_DOWNLOAD_TIMEOUT_SEC` | `120` | Timeout for the one-time model download (seconds) |
| `PACE_MIN_DETECTION_CONFIDENCE` | `0.7` | MediaPipe detection threshold |
| `PACE_MIN_PRESENCE_CONFIDENCE` | `0.7` | MediaPipe presence threshold |
| `PACE_MIN_TRACKING_CONFIDENCE` | `0.7` | MediaPipe tracking threshold |
| `PACE_DATA_DIR` | `/data` | Directory for job state SQLite DB and temp files |

**Production minimum:**

```bash
PACE_CORS_ORIGINS=https://your-frontend.vercel.app
PACE_DATA_DIR=/data  # Mount a persistent volume at this path
```

### Frontend (`frontend/.env.local`)

| Variable | Description | Example |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Backend base URL (no trailing slash) | `https://your-backend.railway.app` |

---

## API Reference

Base URL: `http://localhost:8000` (local) / your Railway URL (production)

### Health

```
GET /health
```
```json
{ "status": "ok", "jobs_active": 1 }
```

```
GET /debug/config
```
Returns current runtime settings (confidences, smoothing params, job limits).

---

### Video Analysis

#### Upload a video

```
POST /api/analyze-video
Content-Type: multipart/form-data
```

| Field | Type | Default | Description |
|---|---|---|---|
| `file` | file | required | Video file (.mp4, .mov, .avi, .mkv, .webm). Max 500 MB |
| `skip_frames` | int | `1` | Process every Nth frame (1–10). Higher = faster, less granular |
| `detection_height` | int | none | Resize height for detection (240–1080). `None` = original resolution |

**Response `202`**
```json
{
  "job_id": "b7e2f41a9c03...",
  "status": "queued",
  "created_at": "2026-05-25T14:00:00Z"
}
```

**Errors:** `400` invalid file type · `413` file too large · `429` server at capacity

---

#### Stream progress

```
GET /api/analyze-video/{job_id}/status
```

Server-Sent Events stream (every 500 ms):

```
data: {"job_id":"...","status":"processing","progress_pct":45.2,"frames_processed":135,"total_frames":300,"error":null}

data: {"job_id":"...","status":"completed","progress_pct":100.0,...}
```

Stream closes automatically on completion or failure.

---

#### Fetch results

```
GET /api/analyze-video/{job_id}/result
```

Returns the full JSON report: `frame_angles`, `summary`, `stride_events`, `stride_summary`, `form_analysis` (problems + score + strike pattern + asymmetry index), and a `has_video` flag.

**Errors:** `404` not found · `409` still processing · `422` analysis failed

---

#### Download annotated video

```
GET /api/analyze-video/{job_id}/video
```

Streams the H.264 MP4 with HTTP Range support (browser seek/scrub works).

---

#### Download Jupyter notebook

```
GET /api/analyze-video/{job_id}/notebook
```

Self-contained notebook with per-angle plots, optimal-range shading, stride markers, and summary tables. No backend required to open.

---

### Error Format

All errors return a JSON body:

```json
{ "detail": "Job 'abc123' not found" }
```

| Code | When |
|---|---|
| `400` | Invalid file type or missing filename |
| `404` | Job ID does not exist |
| `409` | Job still in progress |
| `413` | File exceeds size limit |
| `422` | Analysis failed (video could not be processed) |
| `429` | `PACE_MAX_ACTIVE_JOBS` reached |
| `500` | Internal server error |

---

## Biomechanics Model

### Angles Measured

All bilateral angles are computed independently for left and right sides. Angles are **geometric at the vertex** (straight limb ≈ 180°) — the clinical equivalent is `clinical = 180° − geometric`.

| Angle | Landmark triplet | Optimal range (geometric) | Clinical equivalent |
|---|---|---|---|
| Knee flexion | hip → knee → ankle | 135–155° | 25–45° flexion |
| Hip flexion | shoulder → hip → knee | 110–120° | 60–70° flexion |
| Ankle dorsiflexion | knee → ankle → foot_index | 65–72° | 18–25° from neutral |
| Trunk lean | midline shoulders → midline hips vs. vertical | — | 4–12° forward |
| Arm swing | shoulder → elbow → wrist | — | data only |
| Arm drive | hip → shoulder → elbow | — | data only |

**Trunk lean** uses the midline method: averaged L/R shoulders → averaged L/R hips, measured in 2D (sagittal XY plane) against vertical. This cancels left/right asymmetry and drops the noisy z-axis.

### Speed-Adaptive Thresholds

Cadence proxies for running speed. Thresholds automatically tighten or loosen:

| Band | Cadence (total SPM) | Effect |
|---|---|---|
| Slow | < 165 | +15% wider ranges, more lenient detector thresholds |
| Moderate | 165–185 | Default values |
| Fast | > 185 | −10% tighter ranges, stricter thresholds |

### Form Problems Flagged

A problem must appear in ≥15% of strides **or** 2+ consecutive strides to be raised. Each is tiered: **consistent** (>30%), **intermittent** (15–30% or consecutive), **isolated** (<15%).

| Problem | Gait phase | Signal |
|---|---|---|
| Overstriding | initial contact | `(ankle_x − hip_x) / leg_length > 0.25` (body-proportion normalized) |
| Heel strike | initial contact | `heel.y > foot_index.y + 0.02 m` |
| Excessive trunk lean | initial contact | midline lean > 15° clinical |
| Insufficient trunk lean | initial contact | midline lean < 2° clinical |
| Cadence low/high | overall | < 170 or > 195 SPM total |
| Vertical oscillation | stride cycle | midline hip-y amplitude > 8 cm |

**Not detectable from a side view:** knee valgus, arm crossover (frontal-plane phenomena).

### Self-Calibration

A stride is flagged only if it exceeds the population threshold **and** either:
- the runner's own mean also exceeds it (consistent issue), or
- the stride is a z > 1.5 personal outlier (occasional breakdown).

This suppresses false positives for runners whose biomechanics are borderline-but-consistent.

---

## Deployment

### Frontend — Vercel

The `frontend/vercel.json` is already configured. Connect the `frontend/` directory to a Vercel project and set:

```
NEXT_PUBLIC_API_URL=https://your-railway-backend.railway.app
```

### Backend — Railway (Docker)

The `backend/Dockerfile` builds a self-contained image with:
- All Python dependencies
- OpenGL runtime libraries for MediaPipe
- System ffmpeg for H.264 transcoding
- MediaPipe heavy model baked in (no first-request download)

**Deploy steps:**

1. Create a new Railway project and connect the repo.
2. Set the root directory to `backend/`.
3. Add a **Volume** mounted at `/data` — this persists job state and annotated videos across restarts.
4. Set environment variables:

```bash
PACE_CORS_ORIGINS=https://your-frontend.vercel.app
PACE_DATA_DIR=/data
```

Railway injects `$PORT`; the `CMD` in the Dockerfile reads it automatically.

> **Single-worker constraint.** The Dockerfile pins `--workers 1`. Job state and video files live on a single process's disk/memory. Horizontal scaling requires externalizing state first (e.g., a Redis job registry + object storage for videos).

### Backend — Manual / Any Docker Host

```bash
cd backend

docker build -t pacevision-backend .

docker run -p 8000:8000 \
  -v /your/data:/data \
  -e PACE_CORS_ORIGINS=https://your-frontend.com \
  -e PACE_DATA_DIR=/data \
  pacevision-backend
```

---

## Project Structure

```
PaceVision/
├── backend/
│   ├── main.py                    # FastAPI app entry point + lifespan hooks
│   ├── requirements.txt           # Pinned Python dependencies
│   ├── Dockerfile                 # Production image (includes MediaPipe model)
│   ├── .env.example               # All configurable environment variables
│   ├── API.md                     # Full API endpoint + schema reference
│   ├── TECHNICAL_OVERVIEW.md      # Deep-dive into algorithms and design decisions
│   │
│   ├── analysis/
│   │   ├── angles.py              # 6 joint angle calculations (pure math)
│   │   ├── thresholds.py          # Biomechanics constants + speed-band estimation
│   │   ├── filtering.py           # MAD-based outlier rejection for stride metrics
│   │   ├── form_problems.py       # Phase-aware form-fault detection (5 detectors)
│   │   ├── stride_detector.py     # Zeni forward-reach stride detection + autocorrelation
│   │   ├── notebook_generator.py  # Jupyter notebook generation from results
│   │   └── video_pipeline.py      # Two-pass video processing orchestration
│   │
│   ├── pose/
│   │   ├── detector.py            # MediaPipe PoseLandmarker wrapper
│   │   ├── landmarks.py           # Landmark extraction + ankle/heel fallback
│   │   └── smoothing.py           # Savitzky-Golay temporal smoothing
│   │
│   ├── rendering/
│   │   └── overlay.py             # Skeleton + angle overlay drawing
│   │
│   ├── jobs/
│   │   └── manager.py             # Thread-safe async job registry + SQLite persistence
│   │
│   ├── api/
│   │   ├── routes_analyze.py      # /api/analyze-video endpoints
│   │   └── routes_health.py       # /health + /debug/config
│   │
│   ├── core/
│   │   └── config.py              # Pydantic-settings config (PACE_* env vars)
│   │
│   └── schemas/                   # Pydantic request/response schemas
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx                     # Upload UI
│   │   │   ├── processing/[id]/page.tsx     # SSE progress page
│   │   │   └── results/[id]/page.tsx        # Results dashboard
│   │   │
│   │   ├── components/
│   │   │   ├── results/
│   │   │   │   ├── results-view.tsx         # Main results layout
│   │   │   │   ├── video-panel.tsx          # Sticky annotated video player
│   │   │   │   ├── angle-charts.tsx         # Recharts time-series charts
│   │   │   │   ├── form-problems.tsx        # Problem cards with coaching tips
│   │   │   │   ├── score-summary.tsx        # Overall form score
│   │   │   │   ├── stride-timeline.tsx      # Gait event timeline
│   │   │   │   ├── asymmetry.tsx            # L/R asymmetry index
│   │   │   │   ├── contact-method-select.tsx # Contact method switcher
│   │   │   │   └── downloads.tsx            # Video + notebook download buttons
│   │   │   └── upload/
│   │   │       └── upload-form.tsx          # Drag-and-drop upload
│   │   │
│   │   ├── lib/
│   │   │   ├── api.ts                       # Typed API client
│   │   │   ├── types.ts                     # Shared TypeScript types
│   │   │   ├── data.ts                      # Data transformation helpers
│   │   │   └── format.ts                    # Display formatting (degrees, SPM, etc.)
│   │   │
│   │   └── store/
│   │       └── useAnalysis.ts               # Zustand store for analysis results
│   │
│   ├── package.json
│   ├── tailwind.config.ts
│   ├── next.config.mjs
│   └── vercel.json
│
├── CLAUDE.md                      # AI assistant instructions
├── TECHNICAL_OVERVIEW.md          # Algorithm deep-dive (mirrors backend/)
└── README.md                      # This file
```

---

## Limitations

| Limitation | Details |
|---|---|
| Side view required | Frontal-plane problems (knee valgus, arm crossover) are physically invisible from the side and are not detectable. |
| Single runner | `num_poses = 1`. Multiple people in frame will cause unpredictable results. |
| Real-time footage | Slow-motion clips are detected (implausible cadence) and cadence flags are suppressed; spatial metrics (angles, overstride, trunk lean) still apply. |
| Minimum strides | Fewer than 7 strides per side triggers a `low_confidence_warning` — not enough data for stable statistics. |
| Occluded-side depth | The z-axis for the far side of the body is unreliable from a single camera. Trunk lean uses a 2D midline method; foot fore/aft uses XY only. |
| In-memory job state | Without an attached volume, job results are lost on restart. With a Railway volume at `/data`, state persists across restarts via SQLite. |
| Single-process only | Horizontal scaling requires externalizing job state and video storage before adding workers. |

---

## License

MIT — see [LICENSE](LICENSE) for details.
