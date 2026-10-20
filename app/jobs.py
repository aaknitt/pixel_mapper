"""One background job at a time (capture or detection), polled by the browser."""

from __future__ import annotations

import itertools
import threading
import time
import traceback
from typing import Any, Callable


class JobCancelled(Exception):
    pass


class Job:
    _ids = itertools.count(1)

    def __init__(self, kind: str, label: str):
        self.id = next(self._ids)
        self.kind = kind
        self.label = label
        self.state = "running"
        self.progress = 0
        self.total = 0
        self.message = ""
        self.error: str | None = None
        self.result: Any = None
        self.started = time.time()
        self.finished: float | None = None
        self._cancel = threading.Event()

    def update(self, progress: int | None = None, total: int | None = None, message: str | None = None) -> None:
        if progress is not None:
            self.progress = progress
        if total is not None:
            self.total = total
        if message is not None:
            self.message = message

    def check_cancel(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "state": self.state,
            "progress": self.progress,
            "total": self.total,
            "message": self.message,
            "error": self.error,
            "result": self.result,
            "started": self.started,
            "finished": self.finished,
        }


class JobRunner:
    def __init__(self) -> None:
        self._job: Job | None = None
        self._lock = threading.Lock()

    def busy(self) -> bool:
        return self._job is not None and self._job.state == "running"

    def start(self, kind: str, label: str, fn: Callable[[Job], Any]) -> Job:
        with self._lock:
            if self.busy():
                raise RuntimeError(f"Another job is running: {self._job.label}")
            job = Job(kind, label)
            self._job = job

        def run() -> None:
            try:
                job.result = fn(job)
                job.state = "done"
            except JobCancelled:
                job.state = "cancelled"
                job.message = "Cancelled"
            except Exception as exc:  # surfaced in the UI
                job.state = "error"
                job.error = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
            finally:
                job.finished = time.time()

        threading.Thread(target=run, name=f"job-{job.id}", daemon=True).start()
        return job

    def current(self) -> Job | None:
        return self._job

    def cancel(self) -> bool:
        job = self._job
        if job and job.state == "running":
            job._cancel.set()
            return True
        return False
