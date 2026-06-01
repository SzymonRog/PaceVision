# PaceVision backend — production image
# Build context: the backend/ directory.
FROM python:3.11-slim AS base

# OpenCV / MediaPipe runtime libraries (libGL + glib).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
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
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
