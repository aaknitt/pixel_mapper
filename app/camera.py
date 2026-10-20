"""USB (UVC) or network camera through OpenCV, read continuously on a background thread.

Reading continuously keeps the driver buffer drained so a frame grabbed after a light change
really was exposed after that change.
"""

from __future__ import annotations

import sys
import threading
import time

import cv2
import numpy as np

if sys.platform.startswith("win"):
    INDEX_BACKEND = cv2.CAP_DSHOW
    AUTO_EXPOSURE_VALUES = (0.75, 0.25)
elif sys.platform.startswith("linux"):
    INDEX_BACKEND = cv2.CAP_V4L2
    AUTO_EXPOSURE_VALUES = (3, 1)
else:
    INDEX_BACKEND = cv2.CAP_ANY
    AUTO_EXPOSURE_VALUES = (0.75, 0.25)


def _open_capture(source: str) -> cv2.VideoCapture:
    source = str(source).strip()
    if source.isdigit():
        return cv2.VideoCapture(int(source), INDEX_BACKEND)
    return cv2.VideoCapture(source)


def probe(max_index: int = 6) -> list[int]:
    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, INDEX_BACKEND)
        ok = cap.isOpened() and cap.read()[0]
        cap.release()
        if ok:
            found.append(i)
    return found


class Camera:
    def __init__(self) -> None:
        self._cap: cv2.VideoCapture | None = None
        self._cap_lock = threading.Lock()
        self._cond = threading.Condition()
        self._frame: np.ndarray | None = None
        self._seq = 0
        self._running = False
        self._thread: threading.Thread | None = None
        self.source: str | None = None
        self.requested_size: tuple[int, int] | None = None
        self.error: str | None = None
        self.exposure_locked = False

    @property
    def is_open(self) -> bool:
        return self._running and self._frame is not None

    def open(self, source: str, size: tuple[int, int] | list[int], timeout: float = 8.0) -> None:
        self.close()
        cap = _open_capture(source)
        if not cap.isOpened():
            self.error = f"Could not open camera '{source}'."
            raise RuntimeError(self.error)
        width, height = int(size[0]), int(size[1])
        if str(source).strip().isdigit():
            # MJPG lets USB 2.0 webcams deliver 1080p at full frame rate instead of a few fps.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap = cap
        self.source = str(source)
        self.requested_size = (width, height)
        self.error = None
        self.exposure_locked = False
        self._frame = None
        self._running = True
        self._thread = threading.Thread(target=self._reader, name="camera-reader", daemon=True)
        self._thread.start()
        deadline = time.time() + timeout
        with self._cond:
            while self._frame is None and time.time() < deadline:
                self._cond.wait(0.2)
        if self._frame is None:
            self.close()
            self.error = f"Camera '{source}' opened but returned no frames."
            raise RuntimeError(self.error)

    def close(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        with self._cap_lock:
            if self._cap is not None:
                self._cap.release()
                self._cap = None
        self._frame = None

    def _reader(self) -> None:
        failures = 0
        while self._running:
            with self._cap_lock:
                cap = self._cap
                ok, frame = cap.read() if cap is not None else (False, None)
            if ok and frame is not None:
                failures = 0
                with self._cond:
                    self._frame = frame
                    self._seq += 1
                    self._cond.notify_all()
            else:
                failures += 1
                if failures > 100:
                    self.error = "Camera stopped delivering frames."
                time.sleep(0.02)

    def latest(self) -> tuple[np.ndarray | None, int]:
        with self._cond:
            return self._frame, self._seq

    def fresh_frame(self, skip: int = 2, timeout: float = 5.0) -> np.ndarray:
        """Wait until `skip` frames have arrived after this call, then return the newest one."""
        with self._cond:
            target = self._seq + skip
            deadline = time.time() + timeout
            while self._seq < target:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise RuntimeError("Timed out waiting for a camera frame.")
                self._cond.wait(remaining)
            return self._frame.copy()

    def frame_size(self) -> tuple[int, int] | None:
        frame = self._frame
        if frame is None:
            return None
        return frame.shape[1], frame.shape[0]

    def jpeg(self, max_width: int | None = None, quality: int = 80) -> bytes | None:
        frame = self._frame
        if frame is None:
            return None
        if max_width and frame.shape[1] > max_width:
            scale = max_width / frame.shape[1]
            frame = cv2.resize(frame, (max_width, int(round(frame.shape[0] * scale))), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes() if ok else None

    def set_auto_exposure(self, auto: bool) -> bool:
        """Best effort: not every camera or backend honors this. Returns True if accepted."""
        value = AUTO_EXPOSURE_VALUES[0] if auto else AUTO_EXPOSURE_VALUES[1]
        with self._cap_lock:
            if self._cap is None:
                return False
            ok = bool(self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, value))
            if not auto:
                self._cap.set(cv2.CAP_PROP_AUTO_WB, 0)
            else:
                self._cap.set(cv2.CAP_PROP_AUTO_WB, 1)
        self.exposure_locked = ok and not auto
        return ok

    def status(self) -> dict:
        size = self.frame_size()
        return {
            "open": self.is_open,
            "source": self.source,
            "frame_size": list(size) if size else None,
            "requested_size": list(self.requested_size) if self.requested_size else None,
            "error": self.error,
            "exposure_locked": self.exposure_locked,
        }
