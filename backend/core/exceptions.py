"""Custom exceptions for PaceVision backend."""


class PaceVisionError(Exception):
    """Base exception for all PaceVision errors."""


class CameraError(PaceVisionError):
    """Failed to open, read from, or configure a camera device."""


class DetectionError(PaceVisionError):
    """MediaPipe pose detection failed or returned no results."""


class SessionNotFound(PaceVisionError):
    """Requested session ID does not exist in the registry."""


class SessionLimitReached(PaceVisionError):
    """Cannot create another session — max_sessions cap hit."""
