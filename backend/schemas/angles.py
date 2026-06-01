"""Pydantic schemas for angle calculation results."""

from pydantic import BaseModel


class AngleResult(BaseModel):
    """Result of a single joint-angle calculation."""

    name: str                          # e.g. "knee_flexion"
    value_deg: float                   # calculated angle in degrees
    min_threshold: float | None = None # deprecated — was optimal range lower bound
    max_threshold: float | None = None # deprecated — was optimal range upper bound
    rating: str | None = None          # deprecated — was "optimal" | "warning" | "poor"
    landmarks_used: tuple[int, int, int]  # the 3 landmark indices (a, b, c)


class AngleFrame(BaseModel):
    """All computed angles for a single frame."""

    timestamp_ms: int
    angles: dict[str, AngleResult]
