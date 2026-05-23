"""WebSocket endpoint for real-time pose + angle streaming."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.exceptions import SessionNotFound

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{session_id}")
async def ws_stream(websocket: WebSocket, session_id: str) -> None:
    """Stream ``WSFrame`` JSON objects for an active session.

    The client connects after creating a session via ``POST /api/sessions``.
    Each message is one JSON frame containing landmarks and angles.

    Client can send:
      - ``{"command": "pause"}``  — stop sending frames (session keeps running)
      - ``{"command": "resume"}`` — resume sending frames

    The server sends ``{"event": "session_ended", "reason": "..."}``
    and closes the connection when the session stops or errors.
    """
    manager = websocket.app.state.session_manager

    try:
        session = manager.get_session(session_id)
    except SessionNotFound:
        await websocket.close(code=4004, reason="Session not found")
        return

    await websocket.accept()
    paused = False

    try:
        while True:
            # Check for incoming commands (non-blocking)
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(), timeout=0.01,
                )
                msg = json.loads(raw)
                cmd = msg.get("command")
                if cmd == "pause":
                    paused = True
                elif cmd == "resume":
                    paused = False
            except asyncio.TimeoutError:
                pass
            except (json.JSONDecodeError, KeyError):
                pass

            # Check session health
            if session.status in ("stopped", "error"):
                await websocket.send_json({
                    "event": "session_ended",
                    "reason": session.status,
                })
                break

            if paused:
                await asyncio.sleep(0.05)
                continue

            # Get next processed frame from the session output queue
            try:
                ws_frame = await asyncio.wait_for(
                    session.output_queue.get(), timeout=0.5,
                )
                await websocket.send_json(ws_frame.model_dump(mode="json"))
            except asyncio.TimeoutError:
                continue  # no frame ready — loop and check session health

    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()
