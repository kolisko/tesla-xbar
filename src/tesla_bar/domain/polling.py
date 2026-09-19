"""Retry timing rules; xBar remains the scheduler."""
from .errors import Failure
from .models import READ_ERROR_THRESHOLD, consecutive_read_errors, number, read_error_alert


def read_retry_delay(cache):
    """Three failed refreshes: 15 minutes, then 30, then at most hourly."""
    failures = consecutive_read_errors(cache)
    if failures < READ_ERROR_THRESHOLD:
        return 0
    return (15 * 60, 30 * 60, 60 * 60)[min(failures - READ_ERROR_THRESHOLD, 2)]


def retry_not_before(cache, *, manual=False):
    """Honor the later of local error backoff and Tesla's rate-limit deadline."""
    deadlines = [0]
    if not manual and read_error_alert(cache):
        value = cache.get("read_retry_at")
        if number(value) and value > 0:
            deadlines.append(value)
    if cache.get("retry_reason") == Failure.RATE_LIMITED:
        value = cache.get("retry_at")
        if number(value) and value > 0:
            deadlines.append(value)
    return max(deadlines)


def reuse_manual_refresh(cache, *, now):
    """xBar redraws after the action; briefly reuse that result, without polling twice."""
    stamp = cache.get("manual_refresh_completed_at")
    return number(stamp) and 0 <= now - stamp < 5
