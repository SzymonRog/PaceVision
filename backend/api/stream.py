"""MJPEG stream endpoint — serves annotated camera frames as a browser-viewable stream."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from core.exceptions import SessionNotFound

router = APIRouter(tags=["stream"])

_BOUNDARY = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"


@router.get(
    "/api/sessions/{session_id}/stream",
    summary="MJPEG camera stream with skeleton overlay",
    responses={
        200: {"content": {"multipart/x-mixed-replace": {}}},
        404: {"description": "Session not found"},
    },
)
async def mjpeg_stream(session_id: str, request: Request) -> StreamingResponse:
    """Stream live annotated camera frames as MJPEG.

    Open in a browser or embed as an ``<img>`` tag — no JavaScript needed::

        <img src="http://localhost:8000/api/sessions/{session_id}/stream">

    The stream runs until the session stops or the client disconnects.
    Skeleton joints are colour-coded by angle rating:
    green = optimal, yellow = warning, red = poor.
    """
    manager = request.app.state.session_manager

    try:
        session = manager.get_session(session_id)
    except SessionNotFound:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    async def generate():
        while True:
            if await request.is_disconnected():
                break

            if session.status in ("stopped", "error"):
                break

            try:
                jpeg = await asyncio.wait_for(session.video_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            yield _BOUNDARY + jpeg + b"\r\n"

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
