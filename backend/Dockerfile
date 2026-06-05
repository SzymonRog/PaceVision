# PaceVision backend — production image
# Build context: the backend/ directory.
FROM python:3.11-slim AS base

# OpenCV / MediaPipe runtime libraries.
# MediaPipe 0.10.x's C bindings dlopen GLES + EGL at runtime, so libgl1 alone
# is not enough — without libgles2/libegl1 you get:
#   OSError: libGLESv2.so.2: cannot open shared object file
# ffmpeg: OpenCV can only write mp4v (not browser-playable), so the pipeline
# transcodes to H.264. The bundled imageio-ffmpeg binary is unreliable on this
# slim image, so install a real system ffmpeg (preferred by the transcoder).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgles2 \
        libegl1 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Bake the MediaPipe pose model into the image so there is no blocking
# download (or network dependency) on the first request.
ARG MODEL_URL="https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task"
RUN mkdir -p prototype && \
    python -c "import urllib.request, os; urllib.request.urlretrieve(os.environ.get('MODEL_URL') or '${MODEL_URL}', 'prototype/pose_landmarker_heavy.task')"

# Application code.
COPY . .

# Railway/most PaaS inject $PORT; default to 8000 locally.
ENV PORT=8000

# Durable job state + annotated videos live here. Attach a Railway Volume
# mounted at /data (via the dashboard — Railway does not support the Docker
# VOLUME instruction) so they survive restarts; without a mount this is
# ephemeral container disk and state is lost on redeploy.
ENV PACE_DATA_DIR=/data

EXPOSE 8000

# Pin to a single worker: job state + annotated videos live in this
# process's memory / local temp dir, so multiple workers (or a stray
# WEB_CONCURRENCY) would split jobs across processes and cause 404s on
# /status and /result. Horizontal scaling requires externalized state first.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
