"""Lightweight in-process rate limiting for abuse-prone endpoints.

Sliding-window counters keyed by caller (client IP for unauthenticated
endpoints, account id for authenticated ones). State is per-process — the
same scope limitation as the scheduler's cancel flags — which is fine for
the current single-process deployment; move to Postgres/Redis if the API
ever runs multi-worker.
"""
import threading
import time

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, max_calls: int, per_seconds: float, name: str):
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self.name = name
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Record a hit for `key`; raise 429 once the window is exhausted."""
        now = time.monotonic()
        cutoff = now - self.per_seconds
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(hits) >= self.max_calls:
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many {self.name} requests — try again later",
                )
            hits.append(now)
            self._hits[key] = hits
            # Opportunistic cleanup so dead keys don't accumulate forever.
            if len(self._hits) > 10_000:
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > cutoff}


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# Shared limiter instances (per-process).
login_limiter = RateLimiter(max_calls=10, per_seconds=60, name="login")
# Account creation and reset emails are abuse magnets — keep both tight per IP.
signup_limiter = RateLimiter(max_calls=5, per_seconds=3600, name="signup")
password_reset_limiter = RateLimiter(max_calls=5, per_seconds=3600, name="password reset")
import_limiter = RateLimiter(max_calls=20, per_seconds=3600, name="import")
# Receipt OCR calls cost money per request — cap per account.
receipt_scan_limiter = RateLimiter(max_calls=60, per_seconds=3600, name="receipt scan")
pipeline_run_limiter = RateLimiter(max_calls=10, per_seconds=3600, name="pipeline run")
public_quote_limiter = RateLimiter(max_calls=30, per_seconds=60, name="public quote")
public_pay_limiter = RateLimiter(max_calls=30, per_seconds=60, name="public payment")
public_intake_limiter = RateLimiter(max_calls=30, per_seconds=60, name="website intake")
# Landing/preview email capture — browser-facing and unauthenticated, keep tight.
prospect_limiter = RateLimiter(max_calls=5, per_seconds=3600, name="prospect signup")
