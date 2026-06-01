# PaceVision API

Base URL: `http://localhost:8000`

---

## Health

### `GET /health`
```json
{ "status": "ok", "jobs_active": 1 }
```

### `GET /debug/config`
Returns current runtime settings (confidences, smoothing params, job limits).

---

## Angles Reference

All bilateral angles are computed for **both sides** independently.
Keys are prefixed: `left_knee_flexion`, `right_knee_flexion`, etc.

Angles are the **geometric angle at the vertex** (straight limb ≈ 180°).

| Base key | Triplet | Optimal range (geometric) | Clinical equivalent |
|----------|---------|:-------------------------:|:-------------------:|
| `knee_flexion` | hip → knee → ankle | 135–155° | 25–45° flexion |
| `hip_flexion` | shoulder → hip → knee | 110–120° | 60–70° flexion |
| `trunk_lean` | ear → shoulder → hip | 168–175° | 5–12° lean |
| `ankle_dorsiflexion` | knee → ankle → foot | 65–72° | 18–25° from neutral |
| `arm_swing` | shoulder → elbow → wrist | — | — |

Ratings: `"optimal"` · `"warning"` (within 10°) · `"poor"` (>10° outside)

---

## Video Analysis (Offline)

Upload a video for batch pose analysis. Returns an annotated MP4 with skeleton overlay and a JSON table of per-frame angles with summary statistics.

### `POST /api/analyze-video`

Upload a video file to start analysis. Processing runs asynchronously.

**Content-Type:** `multipart/form-data`

**Form fields:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | file | (required) | Video file (.mp4, .mov, .avi, .mkv, .webm). Max 500 MB |
| `skip_frames` | int | `1` | Process every Nth frame (1–10). Higher = faster but less granular |
| `detection_height` | int | (none) | Resize height for detection (240–1080). None = original resolution |

**Response `202`**

```json
{
  "job_id": "b7e2f41a9c03",
  "status": "queued",
  "created_at": "2026-05-25T14:00:00Z"
}
```

**Errors:** `400` invalid file type · `413` file too large

---

### `GET /api/analyze-video/{job_id}/status`

Server-Sent Events (SSE) stream of progress updates (every 500ms).

```
data: {"job_id":"b7e2f41a9c03","status":"processing","progress_pct":45.2,"frames_processed":135,"total_frames":300,"error":null}

data: {"job_id":"b7e2f41a9c03","status":"completed","progress_pct":100.0,"frames_processed":300,"total_frames":300,"error":null}
```

Stream closes automatically when the job completes or fails.

**Errors:** `404` job not found

---

### `GET /api/analyze-video/{job_id}/result`

Full analysis results (available after job completes).

**Response `200`**
```json
{
  "job_id": "b7e2f41a9c03",
  "status": "completed",
  "duration_sec": 12.34,
  "total_frames": 300,
  "analyzed_frames": 280,
  "video_fps": 30.0,
  "frame_angles": [
    {
      "frame_number": 0,
      "timestamp_ms": 0,
      "angles": {
        "left_knee_flexion": {
          "name": "left_knee_flexion",
          "value_deg": 148.5,
          "landmarks_used": [23, 25, 27]
        },
        "right_knee_flexion": {
          "name": "right_knee_flexion",
          "value_deg": 142.3,
          "landmarks_used": [24, 26, 28]
        }
      },
      "landmarks": {
        "23": [0.0, -0.45, 0.01],
        "25": [0.05, -0.15, 0.02]
      }
    }
  ],
  "summary": [
    {
      "name": "left_knee_flexion",
      "mean_deg": 147.8,
      "min_deg": 131.3,
      "max_deg": 157.9,
      "std_deg": 5.3,
      "min_threshold": 135.0,
      "max_threshold": 155.0,
      "overall_rating": "optimal"
    }
  ],
  "stride_events": [
    {
      "phase": "initial_contact",
      "side": "left",
      "frame_number": 45,
      "timestamp_ms": 1500
    },
    {
      "phase": "toe_off",
      "side": "left",
      "frame_number": 72,
      "timestamp_ms": 2400
    }
  ],
  "stride_summary": [
    {
      "side": "left",
      "num_contacts": 5,
      "num_strides": 4,
      "cadence_spm": 176.2,
      "cadence_rating": "optimal"
    },
    {
      "side": "right",
      "num_contacts": 5,
      "num_strides": 4,
      "cadence_spm": 174.8,
      "cadence_rating": "optimal"
    }
  ],
  "form_analysis": {
    "problems": [
      {
        "problem_id": "overstriding",
        "display_name": "Overstriding",
        "severity": "moderate",
        "confidence": 0.85,
        "side": "left",
        "phase": "initial_contact",
        "description": "Left foot lands 22cm ahead of hips at ground contact",
        "recommendation": "Focus on landing with your foot closer to beneath your hips.",
        "occurrences": 3,
        "total_strides": 4,
        "occurrence_pct": 75.0,
        "frames": [45, 78, 112],
        "metric_value": 0.22,
        "threshold": 0.15,
        "metric_unit": "meters"
      }
    ],
    "strike_pattern": "midfoot",
    "asymmetry_index": {"knee_flexion": 4.2, "hip_flexion": 2.1},
    "overall_form_score": 78.0
  },
  "has_video": true
}
```

**Errors:** `404` job not found · `409` still processing · `422` analysis failed

---

### `GET /api/analyze-video/{job_id}/video`

Download the annotated MP4 with skeleton overlay.

**Response:** `video/mp4` file download.

**Errors:** `404` job/video not found · `409` not yet completed

---

### `GET /api/analyze-video/{job_id}/notebook`

Download a self-contained Jupyter notebook with analysis plots and data.

The notebook embeds all angle data as JSON so it can be opened offline with no backend dependency. Includes:
- Per-angle time-series plots (left vs right on same axes)
- Optimal-range shading on every plot
- Stride phase markers (vertical lines at contact / toe-off)
- Summary statistics table
- Cadence report

**Response:** `application/x-ipynb+json` file download.

**Errors:** `404` job not found · `409` not yet completed

---

## Typical Flow — Video Analysis

```
POST /api/analyze-video                         →  { job_id }
GET  /api/analyze-video/{job_id}/status         →  SSE progress stream
GET  /api/analyze-video/{job_id}/result         →  JSON angles + summary + strides
GET  /api/analyze-video/{job_id}/video          →  download annotated MP4
GET  /api/analyze-video/{job_id}/notebook       →  download Jupyter notebook
```

---

## Data Schemas

### `ProcessedLandmark`
One body joint after Savitzky-Golay smoothing.

| Field | Type | Description |
|-------|------|-------------|
| `index` | int | MediaPipe landmark index (0–32) |
| `name` | string | Human-readable name e.g. `"left_knee"` |
| `x` | float | World X in meters (right = positive) |
| `y` | float | World Y in meters (down = positive) |
| `z` | float | World Z in meters (away from camera = positive) |
| `visibility` | float 0–1 | Confidence that landmark is visible |
| `smoothed` | bool | `false` for the first 6 frames while buffer fills |

Origin of the coordinate system is the **midpoint between the hips**.

---

### `AngleResult`

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Angle key e.g. `"left_knee_flexion"` |
| `value_deg` | float | Calculated angle in degrees (geometric at vertex) |
| `landmarks_used` | [int, int, int] | Triplet indices `[a, vertex, c]` |
| `min_threshold` | float? | *(deprecated)* Was optimal range lower bound |
| `max_threshold` | float? | *(deprecated)* Was optimal range upper bound |
| `rating` | string? | *(deprecated)* Was static per-frame rating. Use `form_analysis` instead |

---

### `FormProblem`

| Field | Type | Description |
|-------|------|-------------|
| `problem_id` | string | ID like `"overstriding"`, `"heel_strike"`, `"excessive_trunk_lean"` |
| `display_name` | string | Human-readable name |
| `severity` | string | `"mild"` \| `"moderate"` \| `"severe"` |
| `confidence` | float | 0.0–1.0 detection confidence |
| `side` | string? | `"left"` \| `"right"` \| null (bilateral) |
| `phase` | string | Stride phase where detected |
| `description` | string | Human-readable explanation |
| `recommendation` | string | Coaching tip |
| `occurrences` | int | Number of strides showing this problem |
| `total_strides` | int | Total strides analyzed |
| `occurrence_pct` | float | Percentage of strides affected |
| `frames` | int[] | Frame numbers where detected |
| `metric_value` | float | The measured value |
| `threshold` | float | The threshold that was exceeded |
| `metric_unit` | string | `"meters"`, `"degrees"`, `"spm"`, `"percent"`, etc. |

**Detectable problems:** `overstriding`, `heel_strike`, `excessive_trunk_lean`, `insufficient_trunk_lean`, `trunk_instability`, `insufficient_hip_extension`, `arm_swing_stiff`, `arm_swing_excessive`, `arm_swing_asymmetry`, `cadence_very_low`, `cadence_low`, `cadence_very_high`, `vertical_oscillation`, `asymmetry_*`

---

### `FormAnalysis`

| Field | Type | Description |
|-------|------|-------------|
| `problems` | FormProblem[] | All detected form problems |
| `strike_pattern` | string | `"heel"` \| `"midfoot"` \| `"forefoot"` \| `"mixed"` \| `"unknown"` |
| `asymmetry_index` | object | `{angle_name: ASI%}` — values >10% indicate significant asymmetry |
| `overall_form_score` | float | 0–100 composite score (100 = no problems detected) |

---

### `StrideEvent`

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | `"initial_contact"` \| `"mid_stance"` \| `"toe_off"` |
| `side` | string | `"left"` \| `"right"` |
| `frame_number` | int | Frame index where the event was detected |
| `timestamp_ms` | int | Video timestamp in milliseconds |

---

### `StrideSummary`

| Field | Type | Description |
|-------|------|-------------|
| `side` | string | `"left"` \| `"right"` |
| `num_contacts` | int | Number of ground contacts detected |
| `num_strides` | int | Number of complete strides |
| `cadence_spm` | float | Steps per minute |
| `cadence_rating` | string | `"optimal"` \| `"warning"` \| `"poor"` (170–185 SPM = optimal) |

---

## Landmark Index Reference

Key landmarks used in angle calculations:

| Index | Name | Index | Name |
|-------|------|-------|------|
| 7 | left_ear | 8 | right_ear |
| 11 | left_shoulder | 12 | right_shoulder |
| 13 | left_elbow | 14 | right_elbow |
| 15 | left_wrist | 16 | right_wrist |
| 23 | left_hip | 24 | right_hip |
| 25 | left_knee | 26 | right_knee |
| 27 | left_ankle | 28 | right_ankle |
| 29 | left_heel | 30 | right_heel |
| 31 | left_foot_index | 32 | right_foot_index |

> **Note:** Ankle (27/28) automatically falls back to heel (29/30) when `visibility < 0.5`.

---

## Error Responses

All errors follow standard HTTP + JSON body:

```json
{ "detail": "Job 'abc123' not found" }
```

| Code | When |
|------|------|
| `400` | Invalid file type or missing filename |
| `404` | Job ID does not exist |
| `409` | Analysis still in progress (result/video requested too early) |
| `413` | Uploaded file exceeds the upload size limit |
| `422` | Analysis failed (video could not be processed) |
| `429` | `max_active_jobs` limit reached — server busy (default: 8) |
| `500` | Internal error |

---

## Configuration

Environment variables (prefix `PACE_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `PACE_MODEL_PATH` | `prototype/pose_landmarker_heavy.task` | Path to MediaPipe model |
| `PACE_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated allowed frontend origins |
| `PACE_MIN_DETECTION_CONFIDENCE` | `0.7` | MediaPipe detection threshold |
| `PACE_MIN_TRACKING_CONFIDENCE` | `0.7` | MediaPipe tracking threshold |
| `PACE_VISIBILITY_THRESHOLD` | `0.5` | Landmark confidence cutoff |
| `PACE_SMOOTHING_WINDOW` | `7` | Savitzky-Golay window size (must be odd) |
| `PACE_SMOOTHING_POLY` | `2` | Savitzky-Golay polynomial order |
| `PACE_MAX_UPLOAD_MB` | `500` | Max video upload size in MB |
| `PACE_ANALYSIS_WORKERS` | `2` | Thread pool size for video analysis |
| `PACE_MAX_ACTIVE_JOBS` | `8` | Max jobs queued/processing at once |
| `PACE_JOB_TTL_SEC` | `3600` | Retention for finished jobs before cleanup |
| `PACE_CLEANUP_INTERVAL_SEC` | `300` | Background cleanup sweep interval |

---

## Running Locally

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Interactive docs: `http://localhost:8000/docs`
