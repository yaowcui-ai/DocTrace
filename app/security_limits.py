"""Bounded, process-local abuse protection; not a distributed rate limiter."""
from collections import deque
from contextlib import contextmanager
from math import ceil
from threading import Lock
import time


class SlidingWindowLimiter:
    def __init__(self, *, limit=10, window_seconds=300, capacity=4096):
        if min(limit, window_seconds, capacity) <= 0:
            raise ValueError('Limits must be positive')
        self.limit, self.window, self.capacity = limit, window_seconds, capacity
        self.entries = {}
        self.lock = Lock()

    def check(self, key, *, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            for old_key in list(self.entries):
                queue = self.entries[old_key]
                while queue and queue[0] <= now-self.window:
                    queue.popleft()
                if not queue:
                    del self.entries[old_key]
            if key not in self.entries and len(self.entries) >= self.capacity:
                return ceil(self.window)
            queue = self.entries.setdefault(key, deque())
            if len(queue) >= self.limit:
                return max(1, ceil(queue[0]+self.window-now))
            queue.append(now)
            return None


class QAAdmission:
    """Protect paid work in a single process; replay paths do not occupy a slot."""
    def __init__(self, *, max_concurrent=2, max_per_owner=1):
        self.maximum, self.per_owner = max_concurrent, max_per_owner
        self.active, self.owners, self.lock = 0, {}, Lock()

    @contextmanager
    def slot(self, owner):
        from .lightrag_client import UpstreamError
        with self.lock:
            if self.active >= self.maximum or self.owners.get(owner, 0) >= self.per_owner:
                raise UpstreamError(429, '当前问答任务较多，请等待正在处理的问题完成后再试。', stage='请求准入')
            self.active += 1
            self.owners[owner] = self.owners.get(owner, 0) + 1
        try:
            yield
        finally:
            with self.lock:
                self.active -= 1
                self.owners[owner] -= 1
                if self.owners[owner] == 0:
                    del self.owners[owner]
