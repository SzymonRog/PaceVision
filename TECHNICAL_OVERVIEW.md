# PaceVision — Technical Overview

> A presentation- and education-oriented walkthrough of the PaceVision
> backend: the architecture, the algorithms, the biomechanics concepts,
> and the design decisions behind them.
>
> **Audience:** engineers, reviewers, and anyone presenting or learning how
> the system works. You do not need a computer-vision or biomechanics
> background — the concepts are introduced from first principles.

---

## 1. What PaceVision Does

PaceVision analyzes **running form** from a single **side-view video**.

```
Runner films themselves from the side  →  upload video  →
  pose estimation  →  joint angles  →  stride detection  →
  form-fault detection  →  annotated video + coaching feedback
```

The output is three things:

1. **An annotated MP4** — the original clip with a skeleton overlay, live joint
   angles, a gait-phase bar, and on-screen problem banners.
2. **A JSON report** — per-frame angles, per-angle summaries, detected stride
   events, cadence, and a list of detected form problems with coaching tips.
3. **A Jupyter notebook** — the same data as reproducible plots, openable
   offline with no backend.

The core idea: **biomechanics is geometry over time.** If you can reliably
locate a runner's joints in each frame, joint angles are simple vector math,
and "good form" becomes a set of thresholds on those angles measured *at the
right moment in the stride*.

---

## 2. The Two Big Architectural Ideas

### Idea 1 — Separate the *expensive* CV pass from the *cheap* analysis

Pose estimation (running MediaPipe on every frame) is by far the most
expensive step. Everything after it — angles, stride detection, form
analysis — is **pure math on a small per-frame data structure** and runs in
milliseconds.

This split drives the whole design:

- The CV pass runs **once** and produces `frame_angles` (a compact per-frame
  record of angles + the handful of landmarks we need).
- Stride detection and form analysis are **pure functions of `frame_angles`**.
  They can be re-run instantly with different parameters *without touching the
  video again*.

A concrete payoff: the `GET /result?contact_method=…` endpoint lets the user
switch the initial-contact detection strategy and get fully recomputed
strides, ratings, and form problems **with no re-upload and no re-processing** —
because that recompute is just calling the pure analysis functions over cached
data.

### Idea 2 — Two-pass video processing (read the file twice, not into RAM)

Rendering a *rich* overlay needs **forward-looking** information: to draw the
gait-phase bar or a problem banner on frame 40, you must already know the
strides and problems for the whole clip. That information only exists *after*
the full analysis.

Two options to get it:

- **Buffer every decoded frame in memory** → simple, but OOMs on long/high-res
  video and creates heavy garbage-collection pressure.
- **Read the source video twice** → Pass 1 analyzes and stores only the small
  per-frame data; Pass 2 re-decodes the source and draws the now-complete
  overlay.

PaceVision chooses the second. Disk re-reads are cheap; holding thousands of
full-resolution frames is not.

```
            ┌──────────────── Pass 1: ANALYSIS ────────────────┐
 video ───► decode ─► MediaPipe ─► landmarks ─► smooth ─► angles ─► frame_angles[]
            └───────────────────────────────────────────────────┘
                                   │
                       strides + form analysis  (pure math)
                                   │
            ┌──────────────── Pass 2: RENDER ──────────────────┐
 video ───► decode ─► draw rich overlay (using full results) ─► H.264 MP4
            └───────────────────────────────────────────────────┘
```

---

## 3. The Pipeline, Stage by Stage

### 3.1 Pose Estimation — `pose/detector.py`

- **Model:** MediaPipe **PoseLandmarker (Tasks API)**, `pose_landmarker_heavy`.
  The "heavy" variant is the most accurate of the three; form analysis lives or
  dies on landmark quality, so accuracy beats speed here (this is an offline
  batch job, not a game loop).
- **Running mode: `VIDEO`.** MediaPipe offers IMAGE, VIDEO, and LIVE_STREAM
  modes. VIDEO mode carries temporal tracking state between frames (smoother,
  more stable landmarks than treating each frame independently) and is
  synchronous, which fits a batch pipeline. It requires **monotonically
  increasing timestamps**, which we supply.
- **World landmarks, not normalized landmarks.** MediaPipe returns two sets:
  - *Normalized* landmarks: pixel coordinates in `[0,1]` — good for drawing.
  - *World* landmarks: **3D metric coordinates in meters**, origin at the
    **midpoint of the hips**, with a **y-down** axis (larger y = closer to the
    ground).
  All angle math uses **world** landmarks, because angles must be in real 3D
  space, not distorted by perspective/pixel scaling.
- **Confidence ~0.7** for detection/presence/tracking — a balance that keeps
  occluded-side joints rather than dropping them.

> **Teaching point — the pelvis-centered origin.** Because the origin is the
> hips, the hip landmark sits at ≈ `(0,0,0)` *every frame*. The runner never
> appears to "move forward" in world coordinates. This is why we can't use hip
> displacement to find the running direction — we use foot anatomy instead
> (Section 3.5).

### 3.2 Landmark Extraction & Cleaning — `pose/landmarks.py`

MediaPipe returns **33 landmarks** (face, hands, body). PaceVision keeps only
the **~18 it actually needs** for angles (ears, shoulders, elbows, wrists, hips,
knees, ankles, heels, foot indices). Dropping face/hand landmarks saves ~42% of
the downstream smoothing work for zero loss of information.

**Ankle/heel fallback.** The ankle landmark (27/28) is notoriously noisy in
MediaPipe. When its `visibility` drops below the threshold (0.5), the processor
substitutes the **heel** landmark (29/30), which tracks more stably. This is a
small but important robustness decision for foot-contact detection.

### 3.3 Temporal Smoothing — `pose/smoothing.py`

Raw per-frame landmarks jitter. A noisy coordinate becomes a *very* noisy angle
(and an even noisier angle *derivative*, which we rely on for toe-off). So every
coordinate stream is smoothed with a **Savitzky–Golay filter** (`window=7`,
`poly=2`).

**Why Savitzky–Golay instead of a moving average?** A moving average smooths by
flattening — it blunts the *peaks and valleys*, which are exactly the features
stride detection needs. Savitzky–Golay fits a low-order polynomial to a sliding
window (least-squares), so it removes high-frequency noise **while preserving
the shape, height, and timing of peaks**. For gait signals, that peak fidelity
is the whole point.

Implementation details worth noting:

- **Sparse, on-demand buffers.** A rolling `deque(maxlen=window)` is allocated
  per landmark coordinate only when that landmark first appears — filtered-out
  landmarks never cost memory.
- **Warm-up pass-through.** Until `window` frames have accumulated, values pass
  through **unsmoothed** and are tagged `smoothed=False`. The window is forced
  odd (a `savgol_filter` requirement).

### 3.4 Joint Angles — `analysis/angles.py`

The angle at vertex **B** formed by points **A–B–C** is the classic
dot-product formula:

```
BA = A − B
BC = C − B
cos(θ) = (BA · BC) / (|BA| · |BC|)
θ     = arccos( clamp(cos(θ), −1, +1) )   →  degrees
```

The `clamp(·, −1, +1)` guards against floating-point drift pushing the cosine
slightly outside `[−1, 1]`, which would make `arccos` return `NaN`. A tiny
`+1e-10` in the denominator avoids divide-by-zero on coincident points.

**Two flavors:**

- **3D angles** (`angle_3d`) for the limbs — knee, hip, ankle, arm — using full
  `(x,y,z)`.
- **2D sagittal-plane angles** (`angle_2d`, XY only) where the z-axis is
  unreliable. The side-view camera sees the sagittal plane cleanly but the
  depth (z) of the *occluded* side is guesswork.

**The six measured angles** (bilateral ones computed independently L/R):

| Angle | Triplet (landmarks) | Plane | Sampled at |
|-------|--------------------|-------|------------|
| Knee flexion | hip → knee → ankle | 3D | initial contact |
| Hip flexion | shoulder → hip → knee | 3D | max flexion |
| Ankle dorsiflexion | knee → ankle → foot_index | 3D | mid-stance |
| Arm swing | shoulder → elbow → wrist | 3D | continuous |
| Arm drive | hip → shoulder → elbow | 3D | continuous |
| **Trunk lean** | midline shoulders → midline hips vs vertical | **2D** | continuous (mean) |

> **Geometric vs. clinical degrees — a crucial convention.** The code returns
> the **geometric angle at the vertex**: a *straight* limb ≈ **180°**. Coaches
> speak in **clinical flexion**: a straight limb = **0°**. The two are
> supplements: `flexion = 180° − geometric`. So "knee flexion 135–155°
> geometric" *is* "25–45° clinical." Keeping the math in geometric degrees and
> converting only for display avoids sign-convention bugs.

**Trunk lean is special — the "midline" method.** Instead of a bilateral
ear→shoulder→hip angle (which depends on the noisy occluded-side z), trunk lean
is computed as the angle between:

- the **midline trunk vector** = (average of L/R shoulders) → (average of L/R
  hips), and
- **true vertical** `[0, 1]`,

measured in **2D (XY)** and reported directly in **clinical forward-lean
degrees** (0° = perfectly upright, positive = leaning forward). Averaging the
two sides cancels left/right asymmetry, and dropping z removes the dominant
noise source. This mirrors the gait-lab convention of a C7–L4 midline relative
to gravity.

### 3.5 Stride Detection — `analysis/stride_detector.py`

This is the algorithmic heart of the system. Goal: from the angle/landmark time
series, find the gait events for **each leg**:

```
   initial_contact  →  mid_stance  →  toe_off  →  (swing)  →  initial_contact …
```

**Step A — running direction (pelvis-invariant).** Because world coordinates
are hip-centered, we infer "forward" from anatomy: the **toe (foot_index) sits
ahead of the heel** in the direction of travel. Averaging `toe_x − heel_x` over
all frames gives a robust forward sign (+1 or −1) that doesn't depend on the
origin.

**Step B — the forward-reach signal (Zeni et al., 2008).** For each leg, build
the signal:

```
forward(t) = direction × ( foot_x(t) − hip_x(t) )
```

This peaks when the foot is **furthest ahead of the hip** (the reaching, about-
to-land leg) and troughs when it's furthest behind (push-off). The peaks are
candidate **initial contacts**. This coordinate-based event detection is a
well-cited gait-analysis method and is far more reliable than the older
approach of looking for knee-flexion minima.

> **Why not knee-flexion minima?** The knee flexes twice per stride (stance
> absorption *and* swing), so a naive minima detector double-counts and reports
> roughly **2× the true cadence**. The forward-reach peak occurs exactly once
> per stride per leg.

**Step C — robust stride period via autocorrelation.** Rather than trust raw
peak spacing (sensitive to amplitude noise), we estimate the dominant
**stride period** by autocorrelating the forward signal and finding the lag of
maximum self-similarity, constrained to a *plausible per-leg cadence band*
(30–120 steps/min, wide enough to tolerate slow-motion footage). A minimum
autocorrelation of 0.3 is required to trust the period at all.

**Step D — peak picking.** With a trusted period, `scipy.signal.find_peaks`
extracts contacts using:
- `distance = 0.6 × period` (one contact per stride; prevents double-picks),
- `prominence = 0.15 × signal span` (rejects ripple).

Per-leg cadence comes from the **median** inter-peak interval (median = robust
to a stray miss). **Total cadence ≈ per-leg × 2**, matching the 170–185 SPM
total-cadence reference used downstream.

**Step E — selectable contact placement (`contact_method`).** The Zeni
forward-reach peak fires in *late swing*, a few frames *before* the foot
actually plants — sampling a slightly-too-extended leg. Three strategies let
the user pick what best matches their footage; each only ever shifts the event
**forward**, snapped onto a real analyzed frame:

| Method | What it does |
|--------|--------------|
| `foot_plant` *(default)* | Snap forward to where the foot is physically lowest (max world-y) within a short window — the true ground contact. |
| `forward_peak_delayed` | Shift the peak forward by a fixed ~30 ms. |
| `forward_peak` | Raw Zeni peak, no refinement. |

**Step F — mid-stance and toe-off (between consecutive contacts):**

- **Mid-stance** = the frame of **minimum ankle dorsiflexion** between two
  contacts (foot flattest/most loaded).
- **Toe-off** = the **first positive zero-crossing of the hip-flexion
  derivative** — the instant the hip transitions from extending (push-off) to
  flexing (swing). We compute the derivative with `np.gradient` and find the
  first sign change; if none is found, we fall back to the argmin. Using the
  *derivative* (a transition) rather than an absolute value makes the event
  detector insensitive to the runner's overall flexibility.

**Step G — cadence reconciliation across legs.** Both legs share **one true
cadence**, but the occluded leg's estimate is noisier. `reconcile_cadence`:
- if the two per-leg estimates agree within **15%**, average them and mark the
  result **confident**;
- otherwise trust the side with more detected strides and mark it
  **low-confidence** (downstream, the cadence *flag* is suppressed so a noisy
  leg can't raise a false "bad cadence" problem).

### 3.6 Form-Fault Detection — `analysis/form_problems.py`

This stage turns angles + stride events into **coaching feedback**. Its guiding
philosophy is **data-first: prefer showing measurements over raising flags**,
because false positives erode user trust faster than a missed nitpick.

Only **five** problems are *flagged*; everything else (L/R asymmetry index,
strike pattern, arm/hip angles) is **computed and returned as data** but not
raised as a problem.

| Flagged problem | Phase | Signal |
|-----------------|-------|--------|
| Overstriding | initial contact | ankle-ahead-of-hip ÷ leg length |
| Heel strike | initial contact | heel lower than forefoot (world-y) |
| Excessive / insufficient trunk lean | initial contact | midline lean degrees |
| Cadence (low/high) | overall | reconciled total SPM |
| Vertical oscillation | stride cycle | midline-hip-y amplitude |

Four ideas make these detectors trustworthy:

**(a) Body-proportion normalization.** Overstriding isn't an absolute distance —
a tall runner's "neutral" exceeds a short runner's "overstride." So it's
measured as `(ankle_x − hip_x) / leg_length`, a unitless ratio. The detector
also always evaluates the **actually-landing leg** (the foot furthest forward at
that contact), so it's robust even if left/right labeling is imperfect.

**(b) Speed-adaptive thresholds — `analysis/thresholds.py`.** Cadence is used as
a **proxy for running speed**, sorting each clip into a band that adjusts both
the scoring ranges and the detector thresholds:

| Band | Cadence | Scoring ranges | Detector thresholds |
|------|---------|---------------|---------------------|
| slow | < 165 SPM | +15% wider | more lenient (e.g. overstride 0.29) |
| moderate | 165–185 SPM | default | default |
| fast | > 185 SPM | −10% tighter | stricter (e.g. overstride 0.22) |

The same posture that's fine at a jog is a fault at a sprint; fixed thresholds
would mislabel one or the other.

**(c) Self-calibration (per-runner gating).** A stride is flagged only if it
exceeds the **population** threshold **AND** either:
- the **runner's own mean** also exceeds it (a *consistent* issue), or
- the stride is a **z > 1.5 outlier** for this runner (an *occasional*
  breakdown).

This suppresses false positives for someone whose biomechanics are
*borderline-but-consistent*, while still catching genuine one-off breakdowns.
(Requires ≥5 samples to estimate the runner's distribution.)

**(d) Hybrid occurrence gating + tiering.** To avoid flagging a single fluke
frame, a problem must appear in **≥15% of strides OR in 2+ consecutive
strides**. Each surviving problem is tagged with a visibility **tier**:

- `consistent` — > 30% of strides
- `intermittent` — 15–30%, or 2+ consecutive
- `isolated` — < 15% and not consecutive

The "2+ consecutive" rule is important: a fault that recurs back-to-back is
real even if its overall percentage is low.

**Slow-motion guard.** Cadence is the *only* metric tied to real playback rate.
A "cadence" outside a believable running range (120–230 SPM total) almost
always means **slow-motion footage**, not a bad runner — so it's reported as
data but not flagged. Spatial metrics (overstride, trunk lean, angles) are
unaffected by slow motion, so they still apply.

**Reliability warning.** Fewer than **7 strides per side** sets a
`low_confidence_warning` — there simply isn't enough data for stable statistics.

### 3.7 Phase-Aware Angle Summaries — `summarize_angles`

A subtle but central concept: **an angle is only meaningful at a specific moment
in the stride.** Average knee flexion across a whole clip is biomechanical
nonsense; knee flexion *at the instant of ground contact* is what matters.

So each angle is **sampled at its meaningful phase** before it's rated:

| Angle | Phase sampled | How |
|-------|--------------|-----|
| Knee flexion | initial contact | mean over this side's contact frames |
| Hip flexion | max flexion | 10th-percentile (robust "peak") |
| Ankle dorsiflexion | mid-stance | 10th-percentile |
| Trunk lean / arm angles | continuous | mean over the run |

The whole-clip mean/min/max/std are still computed (they drive the charts), but
the **in-range / out-of-range rating** is evaluated *only at the phase value*,
and *only for angles with a trustworthy reference*. Ankle and arm angles have no
universally-agreed optimal range, so they're returned as **data-only**
(`rating = "no_reference"`) rather than given a misleading green/red verdict.

### 3.8 Rendering — `analysis/video_pipeline.py` + `rendering/overlay.py`

Pass 2 draws the rich overlay (color-coded skeleton, hero angle, gait-phase bar,
fading problem banners) using lookups built from the completed analysis. Then a
codec subtlety:

> **The codec problem.** OpenCV on Windows reliably writes only `mp4v`
> (MPEG-4 Part 2), which **no browser can play inline**. So PaceVision renders
> to a temporary `mp4v` file, then **transcodes to H.264 / yuv420p** using the
> static `ffmpeg` binary **bundled with `imageio-ffmpeg`** (no system install
> needed). `-movflags +faststart` moves the metadata to the front so the
> browser can start playing before the full file downloads. If ffmpeg is
> unavailable, the `mp4v` file is kept as a downloadable fallback.

---

## 4. Operational / Production Architecture

This half answers "how does it run as a deployed service?" — distinct from "how
does the analysis work?"

```
            POST /api/analyze-video (multipart)
                       │
        stream upload to disk in 256 KB chunks  (never buffer whole file in RAM)
                       │
            admission control: 429 if too many jobs in flight
                       │
        JobManager.create_job()  →  job_id (full 128-bit UUID)
                       │
        submit to bounded ThreadPoolExecutor  (CPU-bound, small pool)
                       │                                  │
        return 202 {job_id}                    background worker runs the
                                                two-pass pipeline, updating
        GET …/status  (SSE, 0.5s)  ◄───────────  progress in the JobManager
        GET …/result  (cached, recomputable by contact_method)
        GET …/video   (HTTP Range → browser scrubbing)
        GET …/notebook (generated on demand)
```

Key operational decisions:

- **Async job model.** Uploads return `202 {job_id}` immediately; the heavy work
  runs in a **bounded thread pool** (CPU-bound MediaPipe work; the pool size
  caps parallelism so concurrent jobs don't thrash CPU or blow memory).
- **In-memory, thread-safe `JobManager`.** A `dict` of jobs guarded by a lock,
  shared between async handlers and worker threads. Progress, status, results,
  and temp-file paths live here.
- **Admission control.** New uploads are rejected with **429** once
  `max_active_jobs` are queued/processing — bounding disk and memory under load.
- **Periodic cleanup.** A background task sweeps finished jobs past their TTL
  (default 1 hour), reclaiming both their in-memory results and temp files, so a
  long-running instance doesn't leak.
- **Unguessable job IDs.** Full 128-bit UUIDs so one user can't enumerate
  another's results/video (IDOR protection).
- **Streaming everywhere.** Uploads stream to disk in chunks with a hard size
  cap; the annotated video is served with **HTTP Range** support so the browser
  can seek/scrub; progress is **Server-Sent Events**.
- **Config via environment** (`core/config.py`, `PACE_*` prefix) — CORS origins,
  upload size, worker count, job limits, TTLs, model-download timeout — all
  overridable for production without code changes.
- **Containerized** with the MediaPipe model **baked into the image at build
  time**, so there's no blocking ~25 MB download (or network dependency) on the
  first request.

> **Scope note.** PaceVision is **video-analysis only**. An earlier live-camera
> mode (WebSocket pose stream + MJPEG) was removed — a server has no webcam, and
> the feature added a large surface for no deployed benefit.

---

## 5. Design Decisions at a Glance

| Decision | Why | Trade-off accepted |
|----------|-----|--------------------|
| Side-view only | The sagittal plane (knee/hip/ankle flexion, trunk lean) is cleanly visible from the side | Can't see frontal-plane faults (knee valgus, arm crossover) |
| World (3D metric) landmarks | Angles must be in real space, not perspective-distorted pixels | Occluded-side z is noisy → mitigated by 2D methods where it matters |
| `heavy` MediaPipe model | Form analysis needs maximum landmark accuracy | Slower inference — acceptable for offline batch |
| VIDEO running mode | Temporal tracking → smoother, more stable landmarks | Requires monotonic timestamps |
| Savitzky–Golay smoothing | Removes jitter **without** blunting the peaks stride detection needs | More complex than a moving average |
| Midline 2D trunk lean | Cancels L/R asymmetry and drops the noisy z-axis | Single value, not per-side |
| Forward-reach (Zeni) contacts | One event per stride; avoids the 2× cadence error of knee-minima | Fires slightly before plant → refined by `contact_method` |
| Autocorrelation for stride period | Robust to amplitude noise vs. raw peak spacing | Needs a minimum signal length |
| Derivative zero-crossing for toe-off | Detects a *transition*, insensitive to absolute flexibility | Needs a clean (smoothed) signal |
| Cadence reconciliation | Two legs share one cadence; trust the agreement | Disagreement → cadence reported but not flagged |
| Data-first form analysis (5 flags) | False positives destroy trust faster than misses | Some faults shown as data, not called out |
| Self-calibration + speed bands | "Good form" is relative to the runner and the speed | More parameters to reason about |
| Two-pass video read | Avoids OOM / GC pressure on long clips | Decodes the source twice |
| Separate CV pass from analysis | Re-run analysis (e.g. new `contact_method`) without re-processing | Must cache per-frame data |
| mp4v → H.264 transcode | Browsers can't play OpenCV's mp4v inline | Extra ffmpeg step (bundled, no system install) |
| Async jobs + admission control + cleanup | Bound CPU, memory, and disk under real load | In-memory jobs are lost on restart |

---

## 6. Concept Glossary (the algorithms, briefly)

- **Vector angle (dot product).** `θ = arccos( (BA·BC) / (|BA||BC|) )`. The
  foundation of every joint angle. Clamp the cosine to `[−1,1]` for numerical
  safety.
- **Geometric vs. clinical degrees.** Geometric = angle at the joint vertex
  (straight = 180°). Clinical = flexion from straight (straight = 0°). Related
  by `clinical = 180 − geometric`.
- **Savitzky–Golay filter.** Sliding-window least-squares polynomial fit;
  denoises while preserving peak height/timing. Used on all coordinate streams
  (`window=7`, `poly=2`).
- **Autocorrelation.** Correlating a signal with a time-shifted copy of itself;
  the lag of maximum correlation reveals the dominant period — here, the stride
  period.
- **Zeni event detection (2008).** Detect gait events from the foot's
  fore/aft position relative to the pelvis: max forward = initial contact, max
  back = toe-off.
- **Derivative zero-crossing.** The sign change of a signal's slope marks a
  turning point / transition — used to time toe-off from the hip-flexion
  derivative.
- **Median Absolute Deviation (MAD).** A robust spread measure:
  `MAD = median(|x − median(x)|)`. An outlier is `|x − median| > 2.5 × 1.4826 ×
  MAD` (the `1.4826` rescales MAD to a std-equivalent under normality). MAD
  beats z-score on gait data because the outliers themselves don't poison the
  estimate. *(Provided as a utility in `analysis/filtering.py`; the active
  detectors currently gate via self-calibration below.)*
- **Self-calibration (per-runner z-score).** Flag a stride only if it beats the
  population threshold **and** is either consistent with the runner's mean or a
  `z > 1.5` personal outlier.
- **Speed bands.** Cadence-derived slow/moderate/fast classes that scale all
  thresholds, because correct form is speed-dependent.
- **Hybrid gating & tiering.** A problem must hit ≥15% of strides or 2+
  consecutive strides to flag; it's then tiered consistent / intermittent /
  isolated by how often it recurs.
- **Phase-aware sampling.** Each angle is read at the stride moment where it's
  biomechanically meaningful (knee at contact, hip at peak flexion, ankle at
  mid-stance), never as a whole-clip average.

---

## 7. Data Model (the contract between stages)

The pipeline communicates through a few Pydantic schemas (`schemas/`):

- **`RawLandmark` / `ProcessedLandmark`** — one joint before/after smoothing
  (`index`, `name`, `x/y/z` in meters, `visibility`, `smoothed`).
- **`AngleResult`** — one angle for one frame (`name`, `value_deg` geometric,
  `landmarks_used`).
- **`FrameAngles`** — the per-frame record that *is* the cached analysis output:
  `frame_number`, `timestamp_ms`, `angles`, and the subset of `landmarks`
  needed by detectors. Stride detection and form analysis are pure functions of
  a `list[FrameAngles]`.
- **`StrideEvent`** — one gait event (`phase`, `side`, `frame_number`,
  `timestamp_ms`).
- **`StrideSummary`** — per-side `num_contacts`, `num_strides`, reconciled
  `cadence_spm`, `cadence_rating`.
- **`AngleSummary`** — per-angle whole-clip stats + the phase value + the
  in/out-of-range rating.
- **`FormProblem`** — a flagged fault with `severity`, `confidence`,
  `description`, `recommendation`, occurrence stats, `tier`, and provenance
  flags (`speed_band_adjusted`, `self_cal_applied`).
- **`FormAnalysis`** — the bundle: `problems`, `strike_pattern`,
  `asymmetry_index`, `speed_band`, `estimated_cadence`, and a
  `low_confidence_warning` when strides are too few.
- **`AnalysisResult`** — everything the `/result` endpoint returns.

---

## 8. Assumptions & Limitations (be honest in the presentation)

- **Side view is required.** Frontal-plane problems (knee valgus, arm
  crossover) are physically invisible from the side and are *not* detectable.
- **One runner in frame** (`num_poses = 1`).
- **Occluded-side depth (z) is unreliable** — hence 2D methods for trunk lean
  and foot fore/aft.
- **Cadence assumes real-time playback.** Slow-motion clips are detected
  (implausible cadence) and the cadence flag is suppressed; spatial metrics
  still work.
- **Statistics need data.** < 7 strides per side → results flagged
  low-confidence.
- **In-memory jobs.** A process restart loses job state and results (acceptable
  for a stateless analysis service; a persistent store would be the next step
  for horizontal scaling).

---

## 9. Reference Tables

### Biomechanics thresholds (`analysis/thresholds.py`, moderate band)

| Metric | Geometric optimal | Clinical optimal |
|--------|-------------------|------------------|
| Knee flexion @ contact | 135–155° | 25–45° flexion |
| Hip flexion (max) | 110–120° | 60–70° flexion |
| Ankle dorsiflexion (mid-stance) | 65–72° | 18–25° from neutral |
| Trunk lean (mean) | — | 4–12° forward (clinical, midline) |
| Cadence | — | 170–185 SPM (total) |

### Key MediaPipe landmark indices

| Idx | Name | Idx | Name |
|-----|------|-----|------|
| 7 | left_ear | 8 | right_ear |
| 11 | left_shoulder | 12 | right_shoulder |
| 13 | left_elbow | 14 | right_elbow |
| 15 | left_wrist | 16 | right_wrist |
| 23 | left_hip | 24 | right_hip |
| 25 | left_knee | 26 | right_knee |
| 27 | left_ankle | 28 | right_ankle |
| 29 | left_heel | 30 | right_heel |
| 31 | left_foot_index | 32 | right_foot_index |

> Ankle (27/28) falls back to heel (29/30) when visibility < 0.5.

---

*This document describes the backend as implemented in `backend/`. For the
endpoint reference see `backend/API.md`; for repo conventions see `CLAUDE.md`.*
