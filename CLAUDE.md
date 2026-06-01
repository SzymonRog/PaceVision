# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**PaceVision** (spec refers to it as PaceIQ) is a running form analyzer. Users upload a side-view video → MediaPipe extracts body landmarks → Python calculates joint angles → scores against biomechanics thresholds → Next.js dashboard shows charts and coaching feedback.

## Stack

- **Frontend:** Next.js 14 (App Router), TypeScript, Tailwind CSS, shadcn/ui, Recharts — deployed on Vercel
- **Backend:** FastAPI, Python 3.11, MediaPipe 0.10.x, OpenCV, NumPy, SciPy — deployed on Railway

## Development Commands

### Frontend (`frontend/`)
```bash
npm install
npm run dev       # localhost:3000
npm run build
npm run lint
```

### Backend (`backend/`)
```bash
pip install -r requirements.txt
uvicorn main:app --reload   # localhost:8000
```

### Full stack
```bash
docker-compose up
```

## Architecture

### Analysis Pipeline
```
Video Upload → MediaPipe Processing → Angle Calculation → Stride Detection → Form Analysis → Feedback
```

### Backend modules
| File | Responsibility |
|------|---------------|
| `main.py` | FastAPI app entry point, lifespan hooks |
| `analysis/angles.py` | 6 joint angle calculations (pure math, incl. midline trunk lean + arm drive) |
| `analysis/thresholds.py` | Biomechanics constants, speed-band estimation, per-band detector thresholds |
| `analysis/filtering.py` | MAD-based outlier rejection for stride metrics |
| `analysis/form_problems.py` | Phase-aware form problem detection (8 detectors) with hybrid gating + self-calibration |
| `analysis/stride_detector.py` | Two-pass stride detection with hip-y validation + derivative toe-off |
| `analysis/notebook_generator.py` | Jupyter notebook generation from results |
| `analysis/video_pipeline.py` | Batch video processing (file → annotated video + angles + form) |
| `pose/detector.py` | MediaPipe PoseLandmarker wrapper |
| `pose/landmarks.py` | Landmark extraction, filtering, ankle/heel fallback |
| `pose/smoothing.py` | Savitzky-Golay temporal smoothing |
| `rendering/overlay.py` | Skeleton + angle overlay drawing |
| `jobs/manager.py` | Async video analysis job registry |
| `api/routes_analyze.py` | REST endpoints for video analysis |
| `api/routes_health.py` | Health + debug-config endpoints |

### Frontend routes
| Path | Purpose |
|------|---------|
| `app/page.tsx` | Upload UI |
| `app/results/[id]/page.tsx` | Results dashboard |

## API Contract

### Video Analysis (async batch processing)
- `POST /api/analyze-video` — upload video (multipart), returns `{ job_id }`
- `GET /api/analyze-video/{id}/status` — SSE progress stream
- `GET /api/analyze-video/{id}/result` — JSON angles + summary + form analysis
- `GET /api/analyze-video/{id}/video` — download annotated MP4
- `GET /api/analyze-video/{id}/notebook` — download Jupyter notebook

`POST /api/analyze-video` response:
```json
{
  "job_id": "...",
  "status": "queued",
  "created_at": "..."
}
```

## MediaPipe Rules

- **Side-view camera only** — frontal views not supported
- Use `WorldLandmarks` (3D world coords), not normalized landmarks, for all angle math
- `model_complexity=2`, minimum confidence `0.9`
- Apply Savitzky-Golay smoothing (`window=7, poly=2`) to all coordinates before analysis
- Ankle landmark is noisy — smooth it and fall back to heel landmarks (indices 29/30) when needed

## 6 Angles Measured

Bilateral angles (knee, hip, ankle, arm) are computed for **left and
right sides separately**.  Trunk lean and arm drive are single midline /
shoulder-based values.

| Angle | Landmarks | Type | Measured at |
|-------|-----------|------|-------------|
| Knee flexion | hip → knee → ankle | bilateral | ground contact |
| Hip flexion | shoulder → hip → knee | bilateral | max during stride |
| Trunk lean | midline shoulders → midline hips vs vertical | midline (2D) | mean over stride |
| Ankle dorsiflexion | knee → ankle → foot_index | bilateral | mid-stance |
| Arm swing | shoulder → elbow → wrist | bilateral | elbow bend |
| Arm drive | hip → shoulder → elbow | bilateral | shoulder ROM |

**Trunk lean** uses a midline method: averaged L/R shoulders to averaged
L/R hips, measured in 2D (sagittal plane) relative to vertical.  Returns
clinical degrees (0° = upright, positive = forward lean).  This avoids
z-axis noise on the occluded side in side-view footage.

## Form Analysis (Phase-Aware)

Phase-aware form problem detection with **hybrid gating** to reduce false
positives.  Problems must appear in ≥15% of strides OR 2+ consecutive
strides to be flagged.  Each problem is tiered: consistent (>30%),
intermittent (15-30% or consecutive), isolated (<15%).

**Detectable problems:**
| Problem | Phase | Detection method |
|---------|-------|-----------------|
| Overstriding | initial_contact | ankle-hip dx / leg_length > 0.25 |
| Heel strike | initial_contact | heel.y > foot_index.y + 0.02m |
| Excessive trunk lean | initial_contact | midline lean > 15° clinical |
| Insufficient trunk lean | initial_contact | midline lean < 2° clinical |
| Trunk instability | across strides | trunk_lean std > 4° |
| Insufficient hip extension | toe_off | hip_flexion < 160° geometric |
| Arm swing stiff/excessive | stride_cycle | shoulder ROM < 25° or > 80° |
| Arm swing asymmetry | stride_cycle | L/R shoulder ROM difference > 25% |
| Low/high cadence | overall | < 170 or > 195 SPM |
| L/R asymmetry | initial_contact | asymmetry index > 10% |
| Vertical oscillation | stride_cycle | midline hip y amplitude > 8cm |

**Not detectable from side view:** knee valgus, arm crossover (frontal-plane phenomena).

## Speed-Adaptive Thresholds

Cadence is used as a proxy for running speed.  All scoring ranges and
detector thresholds adjust per speed band:

| Band | Cadence | Scoring ranges | Detector thresholds |
|------|---------|---------------|---------------------|
| slow | < 165 SPM | +15% wider | more lenient (e.g., overstride 0.29, hip ext 155°) |
| moderate | 165–185 SPM | default | default values |
| fast | > 185 SPM | −10% tighter | stricter (e.g., overstride 0.22, hip ext 163°) |

**Self-calibration:** Per-stride metrics are filtered by the runner's own
distribution.  A stride is flagged only if it exceeds the population
threshold AND either (a) the runner's mean also exceeds it, or (b) it is
a z > 1.5 outlier for this runner.  This suppresses false positives for
borderline-but-consistent biomechanics while still catching genuine form
breakdowns.

## Stride Detection Logic

- **Two-pass contact detection:** pass 1 with conservative params estimates cadence, pass 2 uses adaptive `distance` tuned to stride period
- **Multi-signal validation:** knee-flexion peaks cross-checked against midline hip-y local maxima (±3 frames) to reject pose-jitter false contacts
- Cadence = `(num_contacts - 1) / duration_sec * 60`
- Mid-stance = min ankle dorsiflexion between contacts
- **Derivative-based toe-off:** first positive zero-crossing of hip flexion derivative (extension→flexion transition), with argmin fallback
