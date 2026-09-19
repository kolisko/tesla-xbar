"""Failures expressed without a transport protocol."""
from enum import Enum
from dataclasses import dataclass

class AppError(Exception):
    """Safe, user-facing application failure."""

class Failure(str, Enum):
    REMOTE = "remote"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"

@dataclass(frozen=True)
class RetryAdvice:
    value: str
    received_at: float
    delay: float | None  # None means the server supplied an unparseable value.


class RemoteError(AppError):
    def __init__(self, reason: Failure, message: str, retry_after: float = 0, *, retry_advice: RetryAdvice | None = None):
        self.reason = reason
        self.retry_after = retry_after
        self.retry_advice = retry_advice
        super().__init__(message)
