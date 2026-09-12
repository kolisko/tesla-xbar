"""Failures expressed without a transport protocol."""
from enum import Enum

class AppError(Exception):
    """Safe, user-facing application failure."""

class Failure(str, Enum):
    REMOTE = "remote"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"

class RemoteError(AppError):
    def __init__(self, reason: Failure, message: str, retry_after: float = 0):
        self.reason = reason
        self.retry_after = retry_after
        super().__init__(message)
