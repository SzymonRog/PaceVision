"""Pydantic schema for WebSocket frame payload."""

from pydantic import BaseModel

from schemas.angles import AngleResult
from schemas.landmarks import ProcessedLandmark


class WSFrame(BaseModel):
    """Single frame sent over the WebSocket to the client.

    Combines processed landmarks and computed angles for one video frame.
    """

    session_id: str
    timestamp_ms: int
    frame_number: int
    fps: float
    landmarks: list[ProcessedLandmark]
    angles: dict[str, AngleResult]
