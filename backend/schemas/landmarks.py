"""Pydantic schemas for landmark data flowing through the pipeline."""

from pydantic import BaseModel, Field


class RawLandmark(BaseModel):
    """Single landmark straight from MediaPipe, before smoothing."""

    index: int
    name: str
    x: float  # world coords in meters (hip-midpoint origin)
    y: float
    z: float
    visibility: float = Field(ge=0.0, le=1.0)
    presence: float = Field(ge=0.0, le=1.0)


class ProcessedLandmark(BaseModel):
    """Landmark after Savitzky-Golay smoothing."""

    index: int
    name: str
    x: float
    y: float
    z: float
    visibility: float = Field(ge=0.0, le=1.0)
    smoothed: bool = False  # True once the SG buffer is full


class LandmarkFrame(BaseModel):
    """All landmarks for a single video frame."""

    timestamp_ms: int
    landmarks: list[ProcessedLandmark]
    raw_count: int  # how many landmarks passed the visibility threshold
