"""
PaceVision — Webcam Pose Prototype (MediaPipe Tasks API)
=========================================================
Standalone script for experimenting with MediaPipe Pose detection live from webcam.
Draws the full body skeleton, landmark indices, FPS, and a right-side XYZ table.

WHY TASKS API (not mp.solutions):
  MediaPipe 0.10.21+ dropped the legacy `mp.solutions` namespace entirely.
  The current package (0.10.35) only exposes `mediapipe.tasks`.
  The Tasks API is also the production-ready path for PaceVision.

FIRST RUN — MODEL DOWNLOAD:
  The script auto-downloads pose_landmarker_heavy.task (~25 MB) on first run
  and saves it next to this file. Subsequent runs use the cached file.

SETUP:
    cd backend
    venv\\Scripts\\activate        (Windows)
    python prototype/webcam_pose.py

    Press Q to quit.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW MEDIAPIPE TASKS POSE WORKS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The Tasks API replaces the legacy solutions API with a file-based model loader.

  Running modes:
    IMAGE       — single frame, no temporal context
    VIDEO       — frame sequence with monotonic timestamps (we use this)
    LIVE_STREAM — callback-based async, for highest throughput

  We use VIDEO mode: each frame is stamped with elapsed milliseconds so the
  model can apply temporal smoothing across frames.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COORDINATE SYSTEMS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  result.pose_landmarks[0]        — NormalizedLandmark list
    x, y : [0.0, 1.0] relative to frame width / height
    z    : depth relative to hip midpoint (not metric, not used for angles)
    visibility, presence : [0.0, 1.0] confidence scores

  result.pose_world_landmarks[0]  — Landmark list  (WHAT WE USE FOR ANGLES)
    x, y, z : real-world metric coordinates (meters)
    origin   = midpoint between hips
    +x right  |  +y downward  |  +z away from camera

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LIVE FRAME PROCESSING PIPELINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  webcam BGR frame
    → flip horizontally (mirror)
    → convert BGR → RGB
    → wrap in mp.Image(SRGB)
    → landmarker.detect_for_video(mp_image, timestamp_ms)
         ├── result.pose_landmarks[0]       → draw skeleton + indices on frame
         └── result.pose_world_landmarks[0] → render XYZ table on side panel
    → combine frame + table panel (np.hstack)
    → cv2.imshow
"""

import os
import sys
import time
import urllib.request
from pathlib import Path

# Redirect C-level fd 2 to /dev/null during library init.
# Qt (QFontDatabase) and abseil/GLOG write directly to fd 2 before any
# Python logging configuration is possible, so os.environ tricks don't help.
_saved_stderr = os.dup(2)
_devnull = os.open(os.devnull, os.O_WRONLY)
os.dup2(_devnull, 2)
os.close(_devnull)

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

os.dup2(_saved_stderr, 2)  # restore stderr for runtime errors
os.close(_saved_stderr)

# ── Model file ────────────────────────────────────────────────────────────────
# The heavy model matches PaceVision's production accuracy requirement.
# Swap to pose_landmarker_lite.task or pose_landmarker_full.task for faster FPS.
MODEL_FILENAME = "pose_landmarker_heavy.task"
MODEL_PATH     = Path(__file__).parent / MODEL_FILENAME
MODEL_URL      = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_heavy/float16/latest/"
    "pose_landmarker_heavy.task"
)

# ── MediaPipe 33 landmark map (reference) ────────────────────────────────────
#
#  Face
#   0  nose              1  left_eye_inner     2  left_eye
#   3  left_eye_outer    4  right_eye_inner    5  right_eye
#   6  right_eye_outer   7  left_ear           8  right_ear
#   9  mouth_left       10  mouth_right
#
#  Upper body
#  11  left_shoulder    12  right_shoulder    13  left_elbow
#  14  right_elbow      15  left_wrist        16  right_wrist
#  17  left_pinky       18  right_pinky       19  left_index
#  20  right_index      21  left_thumb        22  right_thumb
#
#  Lower body
#  23  left_hip         24  right_hip         25  left_knee
#  26  right_knee       27  left_ankle        28  right_ankle
#  29  left_heel        30  right_heel        31  left_foot_index
#  32  right_foot_index

# Skeleton connections — same 35 bone pairs as the legacy solutions API
POSE_CONNECTIONS = frozenset([
    # Face
    (0, 1), (1, 2), (2, 3), (3, 7),
    (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10),
    # Shoulders
    (11, 12),
    # Left arm
    (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    # Right arm
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    # Torso
    (11, 23), (12, 24), (23, 24),
    # Left leg
    (23, 25), (25, 27), (27, 29), (27, 31), (29, 31),
    # Right leg
    (24, 26), (26, 28), (28, 30), (28, 32), (30, 32),
])

# Joints shown in the XYZ table — PaceVision angle engine landmarks
KEY_JOINTS: dict[int, str] = {
    0:  "Nose",
    7:  "L Ear",
    8:  "R Ear",
    11: "L Shoulder",
    12: "R Shoulder",
    13: "L Elbow",
    14: "R Elbow",
    15: "L Wrist",
    16: "R Wrist",
    23: "L Hip",
    24: "R Hip",
    25: "L Knee",
    26: "R Knee",
    27: "L Ankle",
    28: "R Ankle",
    29: "L Heel",
    30: "R Heel",
    31: "L Foot",
    32: "R Foot",
}

# ── Layout ─────────────────────────────────────────────────────────────────────
TABLE_W   = 345
ROW_H     = 22
HEADER_H  = 52
COL_IDX   =   6
COL_NAME  =  34
COL_X     = 148
COL_Y     = 218
COL_Z     = 288

# Colors (BGR)
C_TITLE   = (210, 210, 210)
C_SUBTEXT = (100, 100, 100)
C_COLHEAD = (180, 180, 180)
C_DIVIDER = (60,  60,  60)
C_ROW_A   = (46,  46,  46)
C_ROW_B   = (32,  32,  32)
C_IDX     = (90, 160, 255)
C_LABEL   = (180, 220, 255)
C_VALUE   = (130, 255, 130)
C_DIM     = (70,  70, 110)
C_FPS     = (0,  220, 100)
C_BONE    = (0,  200,  80)
C_JOINT   = (0,  255, 255)
C_WARN    = (60,  60,  60)

FONT = cv2.FONT_HERSHEY_SIMPLEX
AA   = cv2.LINE_AA


# ── Model bootstrap ────────────────────────────────────────────────────────────

def ensure_model() -> None:
    """Download the pose landmarker model file if not already present."""
    if MODEL_PATH.exists():
        return
    print(f"Downloading {MODEL_FILENAME} (~25 MB) — one-time setup...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print(f"Saved to {MODEL_PATH}")


# ── Camera bootstrap ───────────────────────────────────────────────────────────

CAPTURE_W = 1280
CAPTURE_H = 720


def _frame_is_live(frame: np.ndarray) -> bool:
    """Reject all-black frames that some V4L2 nodes (metadata devices) emit."""
    return frame is not None and frame.size > 0 and float(frame.mean()) > 3.0


def open_camera() -> cv2.VideoCapture:
    """Return the first webcam index that actually delivers live frames.

    On Linux, multiple /dev/videoN nodes can exist per physical camera
    (image, metadata, sensor controls).  Only one streams real pixels;
    the others return all-black buffers.  We probe each index, force
    MJPG + 1280x720 (compatible with virtually every USB webcam), then
    verify the frame is not solid black before accepting it.

    Also: only one V4L2 consumer can read a camera at a time.  If a
    previous run is still hanging on to /dev/videoN, every read here
    will fail — kill the leaked python process and retry.
    """
    last_error = None
    for idx in range(5):
        for backend in (cv2.CAP_V4L2, cv2.CAP_ANY):
            cap = cv2.VideoCapture(idx, backend)
            if not cap.isOpened():
                cap.release()
                continue
            # MJPG is the most widely supported USB-cam fourcc and avoids
            # bandwidth issues that cause black frames at higher resolutions.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAPTURE_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_H)

            # Discard warm-up frames — many cameras send black for the first ~10.
            for _ in range(10):
                cap.read()
            ret, frame = cap.read()
            if ret and _frame_is_live(frame):
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                print(f"Camera opened: index={idx}  {w}x{h}  backend={backend}")
                return cap
            last_error = (
                f"index={idx} backend={backend}: "
                f"ret={ret} mean={float(frame.mean()) if frame is not None else 'n/a'}"
            )
            cap.release()
    raise RuntimeError(
        "No working webcam found (tried indices 0-4 with V4L2 and auto backends).\n"
        f"Last attempt: {last_error}\n"
        "Common causes on Linux Mint:\n"
        "  • Another process is holding the camera (Cheese, browser, a leaked\n"
        "    python from a previous run).  Run: pgrep -af webcam_pose  and kill.\n"
        "  • Run: lsof /dev/video0   to see who has it open."
    )


# ── Drawing helpers ────────────────────────────────────────────────────────────

def draw_skeleton(
    frame: np.ndarray,
    norm_lms,           # result.pose_landmarks[0]  — normalized image coords
    frame_w: int,
    frame_h: int,
) -> None:
    """
    Draw skeleton connections and landmark dots on the video frame.

    norm_lms: list of NormalizedLandmark — x,y in [0,1] relative to frame size.
    Joints with visibility < 0.4 are skipped to reduce noise from occluded points.
    """
    # Convert all landmarks to pixel coords once
    pts = [
        (int(lm.x * frame_w), int(lm.y * frame_h))
        for lm in norm_lms
    ]

    # Draw bone connections
    for (a, b) in POSE_CONNECTIONS:
        if norm_lms[a].visibility < 0.4 or norm_lms[b].visibility < 0.4:
            continue
        cv2.line(frame, pts[a], pts[b], C_BONE, 2, AA)

    # Draw joint circles + index labels
    for idx, lm in enumerate(norm_lms):
        if lm.visibility < 0.4:
            continue
        cv2.circle(frame, pts[idx], 4, C_JOINT, -1, AA)
        cv2.putText(frame, str(idx), (pts[idx][0] + 5, pts[idx][1] - 5),
                    FONT, 0.30, (255, 255, 0), 1, AA)


def draw_table(panel: np.ndarray, world_lms) -> None:
    """
    Render the world-coordinate XYZ table onto the right-side panel.

    world_lms: result.pose_world_landmarks[0] — Landmark list (meters, hip origin).
    Rows dim when visibility < 0.5 (landmark occluded or uncertain).
    """
    h = panel.shape[0]

    # Header
    cv2.putText(panel, "WORLD LANDMARKS (meters)", (6, 18),
                FONT, 0.40, C_TITLE, 1, AA)
    cv2.putText(panel, "origin=hip midpoint  +x right  +y down  +z back",
                (6, 34), FONT, 0.27, C_SUBTEXT, 1, AA)

    # Column headers
    cv2.line(panel, (0, HEADER_H - 10), (TABLE_W, HEADER_H - 10), C_DIVIDER, 1)
    cv2.putText(panel, "IDX",   (COL_IDX,  HEADER_H), FONT, 0.36, C_COLHEAD, 1, AA)
    cv2.putText(panel, "JOINT", (COL_NAME, HEADER_H), FONT, 0.36, C_COLHEAD, 1, AA)
    cv2.putText(panel, "X",     (COL_X,    HEADER_H), FONT, 0.36, C_COLHEAD, 1, AA)
    cv2.putText(panel, "Y",     (COL_Y,    HEADER_H), FONT, 0.36, C_COLHEAD, 1, AA)
    cv2.putText(panel, "Z",     (COL_Z,    HEADER_H), FONT, 0.36, C_COLHEAD, 1, AA)
    cv2.line(panel, (0, HEADER_H + 6), (TABLE_W, HEADER_H + 6), C_DIVIDER, 1)

    # Data rows
    for row_i, (idx, name) in enumerate(KEY_JOINTS.items()):
        text_y  = HEADER_H + 8 + row_i * ROW_H + ROW_H - 5
        rect_y0 = HEADER_H + 8 + row_i * ROW_H
        rect_y1 = rect_y0 + ROW_H
        if rect_y1 > h:
            break

        bg = C_ROW_A if row_i % 2 == 0 else C_ROW_B
        cv2.rectangle(panel, (0, rect_y0), (TABLE_W, rect_y1), bg, -1)

        lm      = world_lms[idx]
        low_vis = lm.visibility < 0.5
        c_i     = C_DIM if low_vis else C_IDX
        c_l     = C_DIM if low_vis else C_LABEL
        c_v     = C_DIM if low_vis else C_VALUE

        cv2.putText(panel, f"{idx:2d}",     (COL_IDX,  text_y), FONT, 0.36, c_i, 1, AA)
        cv2.putText(panel, name,            (COL_NAME, text_y), FONT, 0.36, c_l, 1, AA)
        cv2.putText(panel, f"{lm.x:+.3f}", (COL_X,    text_y), FONT, 0.36, c_v, 1, AA)
        cv2.putText(panel, f"{lm.y:+.3f}", (COL_Y,    text_y), FONT, 0.36, c_v, 1, AA)
        cv2.putText(panel, f"{lm.z:+.3f}", (COL_Z,    text_y), FONT, 0.36, c_v, 1, AA)


def draw_fps(frame: np.ndarray, fps: float) -> None:
    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), FONT, 0.55, C_FPS, 2, AA)


# ── Main loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    ensure_model()

    cap = open_camera()

    # WINDOW_NORMAL lets the user resize freely; we also set a generous initial size.
    window_name = "PaceVision — Pose Prototype  |  Q to quit"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, CAPTURE_W + TABLE_W, CAPTURE_H)

    print("PaceVision Pose Prototype running — press Q to quit")

    # ── Tasks API — PoseLandmarker ─────────────────────────────────────────────
    # RunningMode.VIDEO: frames are processed in order with monotonic timestamps.
    # This enables temporal smoothing across frames inside the model.
    # num_poses=1: we track a single runner (extend to >1 for multi-person).
    base_options = mp_tasks.BaseOptions(model_asset_path=str(MODEL_PATH))
    options = mp_vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=mp_vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.7,   # set to 0.9 for production
        min_pose_presence_confidence=0.7,
        min_tracking_confidence=0.7,          # set to 0.9 for production
    )

    start_ms   = int(time.perf_counter() * 1000)
    prev_time  = time.perf_counter()

    try:
        with mp_vision.PoseLandmarker.create_from_options(options) as landmarker:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    print("Empty frame — camera disconnected?")
                    break

                frame = cv2.flip(frame, 1)
                frame_h, frame_w = frame.shape[:2]

                # ── MediaPipe inference ────────────────────────────────────────────
                # Tasks API requires an mp.Image wrapper around the RGB numpy array.
                # timestamp_ms must be strictly monotonically increasing for VIDEO mode.
                rgb         = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image    = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                timestamp_ms = int(time.perf_counter() * 1000) - start_ms
                result      = landmarker.detect_for_video(mp_image, timestamp_ms)

                # ── Draw skeleton ──────────────────────────────────────────────────
                # result.pose_landmarks is a list (one entry per detected person).
                # [0] = first (and only) person when num_poses=1.
                if result.pose_landmarks:
                    draw_skeleton(frame, result.pose_landmarks[0], frame_w, frame_h)

                # ── FPS ────────────────────────────────────────────────────────────
                now       = time.perf_counter()
                fps       = 1.0 / max(now - prev_time, 1e-9)
                prev_time = now
                draw_fps(frame, fps)

                # ── Table panel ────────────────────────────────────────────────────
                # pose_world_landmarks[0] has the same index as pose_landmarks[0].
                table_panel = np.full((frame_h, TABLE_W, 3), 28, dtype=np.uint8)

                if result.pose_world_landmarks:
                    draw_table(table_panel, result.pose_world_landmarks[0])
                else:
                    cv2.putText(table_panel, "No pose detected",
                                (10, frame_h // 2), FONT, 0.5, C_WARN, 1, AA)
                    cv2.putText(table_panel, "Make sure your full body is visible",
                                (10, frame_h // 2 + 22), FONT, 0.35, C_WARN, 1, AA)

                # ── Display ────────────────────────────────────────────────────────
                combined = np.hstack([frame, table_panel])
                cv2.imshow(window_name, combined)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("Done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted — exiting.")
