from __future__ import annotations

import time
from dataclasses import dataclass


FAIL_LIMIT = 10
COOLDOWN_S = 60.0


@dataclass
class _Bucket:
    failures: int = 0
    blocked_until: float = 0.0


class AdminAuthLimiter:
    def __init__(self, *, fail_limit: int = FAIL_LIMIT, cooldown_s: float = COOLDOWN_S) -> None:
        self.fail_limit = fail_limit
        self.cooldown_s = cooldown_s
        self._buckets: dict[str, _Bucket] = {}

    def is_blocked(self, ip: str, *, now: float | None = None) -> bool:
        bucket = self._buckets.get(ip or "")
        if bucket is None:
            return False
        stamp = time.monotonic() if now is None else now
        if bucket.blocked_until and stamp >= bucket.blocked_until:
            self._buckets.pop(ip, None)
            return False
        return bool(bucket.blocked_until and stamp < bucket.blocked_until)

    def note_failure(self, ip: str, *, now: float | None = None) -> None:
        stamp = time.monotonic() if now is None else now
        key = ip or ""
        bucket = self._buckets.setdefault(key, _Bucket())
        if bucket.blocked_until and stamp >= bucket.blocked_until:
            bucket.failures = 0
            bucket.blocked_until = 0.0
        bucket.failures += 1
        if bucket.failures >= self.fail_limit:
            bucket.blocked_until = stamp + self.cooldown_s

    def note_success(self, ip: str) -> None:
        self._buckets.pop(ip or "", None)
