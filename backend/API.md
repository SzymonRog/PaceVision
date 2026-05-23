# PaceVision API

Base URL: `http://localhost:8000`

---

## Health

### `GET /health`
```json
{ "status": "ok", "sessions_active": 2 }
```

### `GET /debug/config`
Returns current runtime settings (confidences, resolution, smoothing params).

---

## Sessions

### `POST /api/sessions`
Start a new live camera session.

**Body**
```json
{ "device_index": 0 }
```

**Response `201`**
```json
{
  "session_id": "a3f9c12b8e01",
  "status": "running",
  "created_at": "2026-05-23T10:00:00Z"
}
```

**Errors:** `429` max sessions reached · `500` camera failed to open

---

### `GET /api/sessions`
List all active sessions.

**Response `200`**
```json
[
  {
    "session_id": "a3f9c12b8e01",
    "status": "running",
    "created_at": "2026-05-23T10:00:00Z",
    "frame_count": 342,
    "fps": 24.1
  }
]
```

---

### `GET /api/sessions/{session_id}`
Get status of one session.

**Response `200`** — same shape as one item above.  
**Errors:** `404` not found

---

### `DELETE /api/sessions/{session_id}`
Stop and remove a session. Camera is released immediately.

**Response `200`**
```json
{ "stopped": true, "session_id": "a3f9c12b8e01" }
```

**Errors:** `404` not found

---

## MJPEG Camera Stream

### `GET /api/sessions/{session_id}/stream`
Live annotated camera feed — works directly in a browser or `<img>` tag.

```html
<img src="http://localhost:8000/api/sessions/{session_id}/stream">
```

- Returns `multipart/x-mixed-replace` (MJPEG). No JavaScript needed.
- Each JPEG frame has the skeleton overlay drawn on top.
- Joint colours: **green** = optimal · **yellow** = warning · **red** = poor (based on angle ratings).
- Angle values are printed in the top-left corner of each frame.
- Stream ends when the session is stopped or the client disconnects.

**Errors:** `404` session not found

---

## WebSocket Stream

### `WS /ws/{session_id}`
Real-time pose + angle stream. Connect **after** creating a session via REST.

**Server → Client** (one message per frame):
```json
{
  "session_id": "a3f9c12b8e01",
  "timestamp_ms": 1716458400123,
  "frame_number": 342,
  "fps": 24.1,
  "landmarks": [
    { "index": 23, "name": "left_hip", "x": 0.00, "y": 0.00, "z": 0.00, "visibility": 0.98, "smoothed": true }
  ],
  "angles": {
    "knee_flexion": {
      "name": "knee_flexion",
      "value_deg": 32.5,
      "min_threshold": 25.0,
      "max_threshold": 45.0,
      "rating": "optimal",
      "landmarks_used": [23, 25, 27]
    }
  }
}
```

**Client → Server** (optional commands):
```json
{ "command": "pause" }
{ "command": "resume" }
```

**Server → Client** on session end:
```json
{ "event": "session_ended", "reason": "stopped" }
```

**Close codes:** `4004` session not found

---

## Angles Reference

| Key | Triplet | Optimal range |
|-----|---------|:-------------:|
| `knee_flexion` | hip → knee → ankle | 25–45° |
| `hip_flexion` | shoulder → hip → knee | 60–70° |
| `trunk_lean` | ear → shoulder → hip | 5–12° |
| `ankle_dorsiflexion` | knee → ankle → foot | 18–25° |
| `arm_swing` | shoulder → elbow → wrist | — |

Ratings: `"optimal"` · `"warning"` (within 10°) · `"poor"` (>10° outside)

---

## Typical Flow

```
POST /api/sessions                      →  { session_id }
WS   /ws/{session_id}                   →  stream JSON frames (landmarks + angles)
GET  /api/sessions/{session_id}/stream  →  MJPEG video feed (browser/img tag)
DELETE /api/sessions/{id}               →  stop
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
| `name` | string | Angle key e.g. `"knee_flexion"` |
| `value_deg` | float | Calculated angle in degrees |
| `min_threshold` | float | Lower bound of optimal range |
| `max_threshold` | float | Upper bound of optimal range |
| `rating` | string | `"optimal"` \| `"warning"` \| `"poor"` |
| `landmarks_used` | [int, int, int] | Triplet indices `[a, vertex, c]` |

---

### `SessionInfo`

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | 12-char hex ID |
| `status` | string | `"starting"` \| `"running"` \| `"stopped"` \| `"error"` |
| `created_at` | datetime | ISO 8601 UTC |
| `frame_count` | int | Total frames processed |
| `fps` | float | Current frames per second |

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
{ "detail": "Session 'abc123' not found." }
```

| Code | When |
|------|------|
| `404` | Session ID does not exist |
| `429` | `max_sessions` limit reached (default: 4) |
| `500` | Camera failed to open or internal error |
| `4004` | WebSocket — session not found (WS close code) |

---

## Configuration

Environment variables (prefix `PACE_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `PACE_MODEL_PATH` | `prototype/pose_landmarker_heavy.task` | Path to MediaPipe model |
| `PACE_CAPTURE_WIDTH` | `1280` | Camera capture width px |
| `PACE_CAPTURE_HEIGHT` | `720` | Camera capture height px |
| `PACE_MIN_DETECTION_CONFIDENCE` | `0.7` | MediaPipe detection threshold |
| `PACE_MIN_TRACKING_CONFIDENCE` | `0.7` | MediaPipe tracking threshold |
| `PACE_VISIBILITY_THRESHOLD` | `0.5` | Landmark confidence cutoff |
| `PACE_SMOOTHING_WINDOW` | `7` | Savitzky-Golay window size (must be odd) |
| `PACE_SMOOTHING_POLY` | `2` | Savitzky-Golay polynomial order |
| `PACE_MAX_SESSIONS` | `4` | Max concurrent live sessions |

---

## Running Locally

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Interactive docs: `http://localhost:8000/docs`
