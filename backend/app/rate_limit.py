from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import Request


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class SlidingWindowRateLimiter:
    """进程内滑动窗口限流。

    单进程部署（本项目默认）足够；多 worker 部署时每个进程独立计数，
    如需严格全局限流应在反向代理层实现。
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> int:
        """返回 0 表示放行，否则返回建议的 Retry-After 秒数。"""

        if limit <= 0:
            return 0
        now = time.monotonic()
        with self._lock:
            self._cleanup_if_needed(now, window_seconds)
            hits = self._hits.setdefault(key, deque())
            cutoff = now - window_seconds
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, int(window_seconds - (now - hits[0])) + 1)
            hits.append(now)
            return 0

    def _cleanup_if_needed(self, now: float, window_seconds: int) -> None:
        if now - self._last_cleanup < 300:
            return
        cutoff = now - max(window_seconds, 300)
        for key in list(self._hits):
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if not hits:
                del self._hits[key]
        self._last_cleanup = now


rate_limiter = SlidingWindowRateLimiter()
