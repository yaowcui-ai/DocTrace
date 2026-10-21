"""Best-effort bounded console output; request threads never wait for a terminal."""
import logging
import sys
from queue import Empty, Full, Queue
from threading import Event, Thread
from time import monotonic


class BufferedConsoleHandler(logging.Handler):
    def __init__(self, stream=None, *, capacity=256):
        if type(capacity) is not int or capacity < 1:
            raise ValueError('Console queue capacity must be a positive integer.')
        super().__init__()
        self.stream = sys.stderr if stream is None else stream
        self._queue = Queue(maxsize=capacity)
        self._stopping = Event()
        self.dropped_count = 0
        self._worker = Thread(target=self._write_console, name='doctrace-console', daemon=True)
        self._worker.start()

    @property
    def pending_count(self):
        return self._queue.qsize()

    def emit(self, record):
        if self._stopping.is_set():
            return
        try:
            # Freeze formatted text while producer context and args are current.
            self._queue.put_nowait((self.stream, self.format(record) + '\n'))
        except Full:
            # Console is optional; file logging remains an independent handler.
            self.dropped_count += 1
        except Exception:
            # Do not report an output error back through the same broken console.
            self.dropped_count += 1

    def _write_console(self):
        while True:
            if self._stopping.is_set() and self._queue.empty():
                return
            try:
                stream, message = self._queue.get(timeout=0.05)
            except Empty:
                continue
            try:
                stream.write(message)
                stream.flush()
            except Exception:
                self.dropped_count += 1
            finally:
                self._queue.task_done()

    def setStream(self, stream):
        # Unlike StreamHandler.setStream, never flush the potentially frozen old stream.
        previous = self.stream
        self.stream = stream
        return previous

    def wait_for_idle(self, timeout=1.0):
        """Bounded drain for tests/diagnostics only, never for a request or shutdown."""
        deadline = monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._queue.all_tasks_done.wait(remaining)
        return True

    def close(self):
        # Do not join/flush a worker whose OS console write may never return.
        self._stopping.set()
        super().close()


def protect_server_console():
    """Wrap Uvicorn's existing console sinks, retaining its formatting and levels."""
    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
        logger = logging.getLogger(name)
        for original in tuple(logger.handlers):
            if not isinstance(original, logging.StreamHandler) or isinstance(original, logging.FileHandler):
                continue
            handler = BufferedConsoleHandler(original.stream)
            handler.setLevel(original.level)
            handler.setFormatter(original.formatter)
            for filter_ in original.filters:
                handler.addFilter(filter_)
            handler.set_name(original.name)
            # No original.close/flush: the old stream might already be blocked.
            logger.removeHandler(original)
            logger.addHandler(handler)
