"""Custom exceptions for PaceVision backend."""


class PaceVisionError(Exception):
    """Base exception for all PaceVision errors."""


class DetectionError(PaceVisionError):
    """MediaPipe pose detection failed or returned no results."""


class JobNotFound(PaceVisionError):
    """Requested analysis job ID does not exist."""


class VideoProcessingError(PaceVisionError):
    """Something went wrong during video analysis."""
