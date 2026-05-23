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
Video Upload → MediaPipe Processing → Angle Calculation → Stride Detection → Scoring → Feedback
```

### Backend modules
| File | Responsibility |
|------|---------------|
| `main.py` | FastAPI app, `POST /analyze` endpoint |
| `mediapipe_processor.py` | Video → per-frame WorldLandmarks |
| `angle_engine.py` | 5 joint angle calculations |
| `stride_detector.py` | Cadence and overstriding detection |
| `scorer.py` | Threshold comparison → scores |
| `thresholds.py` | All biomechanics constants |

### Frontend routes
| Path | Purpose |
|------|---------|
| `app/page.tsx` | Upload UI |
| `app/results/[id]/page.tsx` | Results dashboard |

## API Contract

`POST /analyze` — multipart video file → JSON:
```json
{
  "angles": {},
  "stride_events": {},
  "scores": {},
  "feedback": []
}
```

## MediaPipe Rules

- **Side-view camera only** — frontal views not supported
- Use `WorldLandmarks` (3D world coords), not normalized landmarks, for all angle math
- `model_complexity=2`, minimum confidence `0.9`
- Apply Savitzky-Golay smoothing (`window=7, poly=2`) to all coordinates before analysis
- Ankle landmark is noisy — smooth it and fall back to heel landmarks (indices 29/30) when needed

## 5 Angles Measured

| Angle | Landmarks (a→b→c) | Measured at |
|-------|------------------|-------------|
| Knee flexion | hip → knee → ankle | ground contact frame |
| Hip flexion | shoulder → hip → knee | maximum during stride |
| Trunk lean | ear → shoulder → hip | mean over stride |
| Ankle dorsiflexion | knee → ankle → foot_index | mid-stance |
| Arm swing | shoulder → elbow → wrist | range of motion |

## Biomechanics Thresholds

```python
knee_flexion_at_contact: 25–45°
hip_flexion_max:         60–70°
trunk_lean_mean:          5–12°
ankle_dorsiflexion_mid:  18–25°
cadence_spm:            170–185 SPM
```

## Stride Detection Logic

- Ground contacts = local minima in knee flexion time-series (`scipy.find_peaks`)
- Cadence = `(num_contacts / duration_sec) * 60`
- Overstriding = `ankle.x > hip.x + 0.15` at contact frame
