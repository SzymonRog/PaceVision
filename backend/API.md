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
POST /api/sessions          →  { session_id }
WS   /ws/{session_id}       →  stream frames
DELETE /api/sessions/{id}   →  stop
```
