"""
PaceVision — Webcam Pose Prototype
====================================
Standalone script for experimenting with MediaPipe Pose detection live from webcam.
Draws the full body skeleton, landmark indices, FPS, and a right-side XYZ table.

SETUP:
    cd backend
    venv\\Scripts\\activate        (Windows)
    python prototype/webcam_pose.py

    Press Q to quit.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW MEDIAPIPE POSE WORKS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MediaPipe Pose runs a two-stage ML pipeline on each frame:

  Stage 1 — BlazePose Detector
    Finds the person and produces a tight bounding box + key anchor points.
    Only runs when tracking is lost; otherwise Stage 2 runs alone (fast path).

  Stage 2 — BlazePose Landmark Model
    Takes the cropped body region and regresses 33 3D landmark positions.
    model_complexity controls the model size:
      0 = Lite  (fastest, least accurate)
      1 = Full
      2 = Heavy (slowest, most accurate) ← PaceVision spec uses this

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COORDINATE SYSTEMS — Two representations returned per frame
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. pose_landmarks  (NORMALIZED IMAGE COORDS)
     Each landmark: x, y in [0.0, 1.0] relative to frame width/height
                    z = depth relative to hip midpoint (rough, not metric)
     Usage: multiply x*frame_w, y*frame_h → pixel position for drawing

  2. pose_world_landmarks  (WORLD COORDS — meters)
     Each landmark: x, y, z in real-world metric coordinates
     Origin = midpoint between the two hips
       +x = subject's right
       +y = downward
       +z = away from camera (into the screen)
     Usage: angle calculations — this is what PaceVision's angle_engine.py will use

  Each landmark also has a visibility field [0.0–1.0]:
    1.0 = fully visible, confident
    0.0 = occluded or out of frame

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LIVE FRAME PROCESSING PIPELINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  webcam BGR frame
    → flip horizontally (mirror so your left = screen left)
    → convert BGR → RGB  (MediaPipe expects RGB)
    → pose.process(rgb)  → results
         ├── results.pose_landmarks        → draw skeleton + indices on frame
         └── results.pose_world_landmarks  → render XYZ table on side panel
    → combine frame + table panel (np.hstack)
    → cv2.imshow
"""

import time

import cv2
import mediapipe as mp
import numpy as np

# ── MediaPipe setup ────────────────────────────────────────────────────────────
mp_pose          = mp.solutions.pose
mp_drawing       = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles

# ── MediaPipe 33 landmark map (full reference) ────────────────────────────────
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

# Joints shown in the XYZ table — focused on what PaceVision's angle engine needs:
# ears (trunk lean), shoulders (arm swing / trunk lean), elbows & wrists (arm swing),
# hips (hip flexion), knees (knee flexion), ankles + heels + foot (ankle dorsiflexion,
# overstriding detection).
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
TABLE_W       = 345   # Width of the right-side table panel (pixels)
ROW_H         = 22    # Height per data row
HEADER_H      = 52    # Space reserved above the data rows (title + column headers)

# Column X positions inside the table panel
COL_IDX   =   6
COL_NAME  =  34
COL_X     = 148
COL_Y     = 218
COL_Z     = 288

# Colors (BGR)
C_TITLE    = (210, 210, 210)
C_SUBTEXT  = (100, 100, 100)
C_COLHEAD  = (180, 180, 180)
C_DIVIDER  = (60,  60,  60)
C_ROW_A    = (46,  46,  46)
C_ROW_B    = (32,  32,  32)
C_IDX      = (90, 160, 255)
C_LABEL    = (180, 220, 255)
C_VALUE    = (130, 255, 130)
C_DIM      = (70,  70, 110)   # Low-visibility landmarks
C_FPS      = (0,  220, 100)
C_WARN     = (60,  60,  60)

FONT  = cv2.FONT_HERSHEY_SIMPLEX
AA    = cv2.LINE_AA


# ── Drawing helpers ────────────────────────────────────────────────────────────

def draw_table(panel: np.ndarray, world_lms) -> None:
    """
    Render the world-coordinate XYZ table onto `panel`.

    Parameters
    ----------
    panel : np.ndarray  — the right-side canvas (height × TABLE_W × 3, uint8)
    world_lms          — results.pose_world_landmarks.landmark (list of 33 items)
                         Each item: .x .y .z (meters) and .visibility (0–1)
    """
    h = panel.shape[0]

    # ── Panel header ──────────────────────────────────────────────────────────
    cv2.putText(panel, "WORLD LANDMARKS (meters)", (6, 18),
                FONT, 0.40, C_TITLE, 1, AA)
    cv2.putText(panel, "origin=hip midpoint  +x right  +y down  +z back",
                (6, 34), FONT, 0.27, C_SUBTEXT, 1, AA)

    # ── Column headers ────────────────────────────────────────────────────────
    cv2.line(panel, (0, HEADER_H - 10), (TABLE_W, HEADER_H - 10), C_DIVIDER, 1)
    cv2.putText(panel, "IDX", (COL_IDX,  HEADER_H),     FONT, 0.36, C_COLHEAD, 1, AA)
    cv2.putText(panel, "JOINT",  (COL_NAME, HEADER_H),  FONT, 0.36, C_COLHEAD, 1, AA)
    cv2.putText(panel, "X",      (COL_X,    HEADER_H),  FONT, 0.36, C_COLHEAD, 1, AA)
    cv2.putText(panel, "Y",      (COL_Y,    HEADER_H),  FONT, 0.36, C_COLHEAD, 1, AA)
    cv2.putText(panel, "Z",      (COL_Z,    HEADER_H),  FONT, 0.36, C_COLHEAD, 1, AA)
    cv2.line(panel, (0, HEADER_H + 6), (TABLE_W, HEADER_H + 6), C_DIVIDER, 1)

    # ── Data rows ─────────────────────────────────────────────────────────────
    for row_i, (idx, name) in enumerate(KEY_JOINTS.items()):
        text_y  = HEADER_H + 8 + row_i * ROW_H + ROW_H - 5   # baseline
        rect_y0 = HEADER_H + 8 + row_i * ROW_H
        rect_y1 = rect_y0 + ROW_H

        if rect_y1 > h:
            break   # out of panel bounds

        # Alternating row background
        bg = C_ROW_A if row_i % 2 == 0 else C_ROW_B
        cv2.rectangle(panel, (0, rect_y0), (TABLE_W, rect_y1), bg, -1)

        lm      = world_lms[idx]
        low_vis = lm.visibility < 0.5
        c_idx   = C_DIM if low_vis else C_IDX
        c_lbl   = C_DIM if low_vis else C_LABEL
        c_val   = C_DIM if low_vis else C_VALUE

        cv2.putText(panel, f"{idx:2d}",      (COL_IDX,  text_y), FONT, 0.36, c_idx, 1, AA)
        cv2.putText(panel, name,             (COL_NAME, text_y), FONT, 0.36, c_lbl, 1, AA)
        cv2.putText(panel, f"{lm.x:+.3f}",  (COL_X,    text_y), FONT, 0.36, c_val, 1, AA)
        cv2.putText(panel, f"{lm.y:+.3f}",  (COL_Y,    text_y), FONT, 0.36, c_val, 1, AA)
        cv2.putText(panel, f"{lm.z:+.3f}",  (COL_Z,    text_y), FONT, 0.36, c_val, 1, AA)


def draw_indices(frame: np.ndarray, pose_lms, w: int, h: int) -> None:
    """
    Draw each landmark's index number just above its joint dot on the video frame.

    Uses pose_landmarks (normalized image coords) — converted to pixels by
    multiplying x * frame_width and y * frame_height.

    Skips landmarks with visibility < 0.4 to avoid cluttering occluded joints.
    """
    for idx, lm in enumerate(pose_lms.landmark):
        if lm.visibility < 0.4:
            continue
        px = int(lm.x * w)
        py = int(lm.y * h)
        cv2.putText(frame, str(idx), (px + 5, py - 5),
                    FONT, 0.30, (255, 255, 0), 1, AA)


def draw_fps(frame: np.ndarray, fps: float) -> None:
    """Overlay FPS counter in the top-left corner of the video frame."""
    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), FONT, 0.55, C_FPS, 2, AA)


# ── Main loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    # Index 0 = default system camera. Change to 1, 2 … for external cameras.
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError(
            "Cannot open webcam at index 0.\n"
            "Try changing VideoCapture(0) to VideoCapture(1) or VideoCapture(2)."
        )

    print("PaceVision Pose Prototype running — press Q to quit")
    print(f"Tracking {len(KEY_JOINTS)} key joints in the XYZ table")

    # ── MediaPipe Pose ─────────────────────────────────────────────────────────
    # model_complexity=2  → heaviest model, most accurate (PaceVision spec)
    #                        lower to 0 or 1 if you get < 10 FPS
    #
    # min_detection_confidence → threshold for the person detector (Stage 1)
    # min_tracking_confidence  → threshold for the landmark tracker (Stage 2)
    # PaceVision spec: 0.9 for both. Lowered to 0.7 here for easier prototyping.
    with mp_pose.Pose(
        model_complexity=2,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.7,
        enable_segmentation=False,
        smooth_landmarks=True,   # temporal smoothing across frames (built-in)
    ) as pose:

        prev_time = time.perf_counter()

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                print("Empty frame — camera disconnected?")
                break

            # Mirror so your left side appears on the left of the screen
            frame = cv2.flip(frame, 1)
            frame_h, frame_w = frame.shape[:2]

            # ── MediaPipe inference ────────────────────────────────────────────
            # Convert BGR (OpenCV default) → RGB (MediaPipe expects RGB).
            # Marking the array non-writeable lets MediaPipe skip an internal copy.
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = pose.process(rgb)  # ← the ML inference happens here

            # ── Draw skeleton ──────────────────────────────────────────────────
            # mp_drawing.draw_landmarks renders:
            #   • Colored dots at each of the 33 landmark positions
            #   • Lines along POSE_CONNECTIONS (35 bone pairs)
            # It uses pose_landmarks (normalized [0,1] image coords internally).
            if results.pose_landmarks:
                mp_drawing.draw_landmarks(
                    frame,
                    results.pose_landmarks,
                    mp_pose.POSE_CONNECTIONS,
                    landmark_drawing_spec=mp_drawing_styles.get_default_pose_landmarks_style(),
                )
                draw_indices(frame, results.pose_landmarks, frame_w, frame_h)

            # ── FPS ────────────────────────────────────────────────────────────
            now      = time.perf_counter()
            fps      = 1.0 / max(now - prev_time, 1e-9)
            prev_time = now
            draw_fps(frame, fps)

            # ── Table panel ────────────────────────────────────────────────────
            # Dark background canvas the same height as the video frame
            table_panel = np.full((frame_h, TABLE_W, 3), 28, dtype=np.uint8)

            if results.pose_world_landmarks:
                draw_table(table_panel, results.pose_world_landmarks.landmark)
            else:
                # No person detected — show a placeholder message
                cv2.putText(table_panel, "No pose detected",
                            (10, frame_h // 2), FONT, 0.5, C_WARN, 1, AA)
                cv2.putText(table_panel, "Make sure your full body is visible",
                            (10, frame_h // 2 + 22), FONT, 0.35, C_WARN, 1, AA)

            # ── Combine and display ────────────────────────────────────────────
            # np.hstack places the table panel to the right of the video frame.
            # Both arrays must have the same height (frame_h).
            combined = np.hstack([frame, table_panel])
            cv2.imshow("PaceVision — Pose Prototype  |  Q to quit", combined)

            # waitKey(1) — process OS events, return key code.
            # & 0xFF masks to 8-bit ASCII for cross-platform compatibility.
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    cv2.destroyAllWindows()
    print("Done.")


if __name__ == "__main__":
    main()
