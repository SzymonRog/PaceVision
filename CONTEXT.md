# PaceIQ — Project Context

## What it is
Running form analyzer. User uploads a side-view video → MediaPipe extracts body landmarks → Python calculates joint angles → scores against biomechanics thresholds → Next.js dashboard shows charts + coaching feedback.

## Stack
- **Frontend:** Next.js 14 (App Router), TypeScript, Tailwind, shadcn/ui, Recharts
- **Backend:** FastAPI, Python 3.11, MediaPipe 0.10.x, OpenCV, NumPy, SciPy
- **Deploy:** Vercel (frontend), Railway (backend)

## Structure
```
paceiq/
├── frontend/
│   ├── app/page.tsx                  # upload UI
│   ├── app/results/[id]/page.tsx     # dashboard
│   └── components/                   # AngleChart, ScoreCard, FeedbackPanel
├── backend/
│   ├── main.py                       # FastAPI + /analyze endpoint
│   ├── mediapipe_processor.py        # video → landmarks per frame
│   ├── angle_engine.py               # 5 joint angle calculations
│   ├── stride_detector.py            # cadence + overstriding detection
│   ├── scorer.py                     # threshold comparison → scores
│   └── thresholds.py                 # all biomechanics constants
└── docker-compose.yml
```

## Key Rules
- Side-view camera only
- Use `WorldLandmarks` (not normalized) for angle math
- `model_complexity=2`, min confidence `0.9`
- Always apply Savitzky-Golay smoothing (`window=7, poly=2`) before analysis
- Ankle landmark is noisy — smooth it, use heel (idx 29/30) as fallback

## 5 Angles Measured
| Angle | Landmarks (a→b→c) |
|---|---|
| Knee flexion | hip → knee → ankle |
| Hip flexion | shoulder → hip → knee |
| Trunk lean | ear → shoulder → hip |
| Ankle dorsiflexion | knee → ankle → foot_index |
| Arm swing | shoulder → elbow → wrist |

## Thresholds (degrees / SPM)
```python
knee_flexion_at_contact: 25–45
hip_flexion_max:         60–70
trunk_lean_mean:          5–12
ankle_dorsiflexion_mid:  18–25
cadence_spm:            170–185
```

## Stride Detection
- Ground contacts = local minima in knee flexion time-series (`scipy.find_peaks`)
- Cadence = `(num_contacts / duration_sec) * 60`
- Overstriding = `ankle.x > hip.x + 0.15` at contact frame

## API
`POST /analyze` — multipart video file → JSON with `angles`, `stride_events`, `scores`, `feedback[]`