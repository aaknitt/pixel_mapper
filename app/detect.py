"""Find the lit pixel in each captured frame.

Each frame is compared to a background (the all-off frame, or the median of neighboring
frames), masked by the polygon, and the brightest blob is located. Frames with no blob or
with a competing blob are flagged for review instead of blocking.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import project as pj
from .jobs import Job


@dataclass
class DetectParams:
    min_peak: int = 40          # minimum brightness rise (0-255) to count as a lit pixel
    min_area: int = 3           # minimum blob size in image pixels
    ambiguity: float = 0.6      # a second blob at least this bright relative to the first is ambiguous
    merge_radius: float = 15.0  # blobs closer than this to the main one are the same light
    blur: int = 5
    background: str = "all_off"  # or "neighbors"


@dataclass
class Detection:
    x: float | None
    y: float | None
    confidence: float
    status: str

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "confidence": self.confidence, "status": self.status}


def load_gray(path: Path) -> np.ndarray | None:
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    return img


def build_mask(shape: tuple[int, int], polygon: list[list[int]] | None) -> np.ndarray | None:
    if not polygon:
        return None
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.array(polygon, np.int32)], 255)
    return mask


def difference(gray: np.ndarray, background: np.ndarray, mask: np.ndarray | None, blur: int) -> np.ndarray:
    """Brightness increase only; areas that got darker are ignored."""
    diff = cv2.subtract(gray, background)
    if mask is not None:
        diff = cv2.bitwise_and(diff, mask)
    if blur and blur > 1:
        k = blur if blur % 2 else blur + 1
        diff = cv2.GaussianBlur(diff, (k, k), 0)
    return diff


def detect_frame(
    gray: np.ndarray, background: np.ndarray, mask: np.ndarray | None, params: DetectParams
) -> Detection:
    diff = difference(gray, background, mask, params.blur)
    _, peak, _, peak_loc = cv2.minMaxLoc(diff)
    if peak < params.min_peak:
        return Detection(None, None, 0.0, "none")
    level = max(params.min_peak / 2.0, peak * 0.5)
    _, binary = cv2.threshold(diff, level, 255, cv2.THRESH_BINARY)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary.astype(np.uint8), connectivity=8)
    main = labels[peak_loc[1], peak_loc[0]]
    if main == 0 or stats[main, cv2.CC_STAT_AREA] < params.min_area:
        return Detection(None, None, 0.0, "none")

    x0, y0, w, h = stats[main, :4]
    roi_labels = labels[y0 : y0 + h, x0 : x0 + w] == main
    weights = diff[y0 : y0 + h, x0 : x0 + w].astype(np.float32) * roi_labels
    total = float(weights.sum())
    ys, xs = np.mgrid[y0 : y0 + h, x0 : x0 + w]
    cx = float((weights * xs).sum() / total)
    cy = float((weights * ys).sum() / total)

    second = 0.0
    candidates = [
        lbl for lbl in range(1, n) if lbl != main and stats[lbl, cv2.CC_STAT_AREA] >= params.min_area
    ]
    candidates.sort(key=lambda lbl: stats[lbl, cv2.CC_STAT_AREA], reverse=True)
    for lbl in candidates[:25]:
        bx, by, bw, bh = stats[lbl, :4]
        sub = labels[by : by + bh, bx : bx + bw] == lbl
        sub_diff = diff[by : by + bh, bx : bx + bw]
        ly, lx = np.nonzero(sub)
        if np.hypot(lx.mean() + bx - cx, ly.mean() + by - cy) < params.merge_radius:
            continue
        second = max(second, float(sub_diff[sub].max()))

    confidence = (peak / 255.0) * (1.0 - second / peak)
    status = "ambiguous" if second >= params.ambiguity * peak else "ok"
    return Detection(round(cx, 2), round(cy, 2), round(max(0.0, min(1.0, confidence)), 3), status)


class FrameCache:
    """Small LRU of decoded grayscale frames for the neighbor-median background."""

    def __init__(self, project: str, prop: str, cam: int, size: int = 12):
        self.project, self.prop, self.cam = project, prop, cam
        self.size = size
        self._data: OrderedDict[int, np.ndarray | None] = OrderedDict()

    def get(self, index: int) -> np.ndarray | None:
        if index in self._data:
            self._data.move_to_end(index)
            return self._data[index]
        img = load_gray(pj.frame_path(self.project, self.prop, self.cam, index))
        self._data[index] = img
        if len(self._data) > self.size:
            self._data.popitem(last=False)
        return img


def neighbor_background(cache: FrameCache, index: int, total: int, reach: int = 2) -> np.ndarray | None:
    """Median of nearby frames. Adjacent pixels are skipped because on a tight wrap they sit
    close enough to overlap this pixel's blob and would cancel part of it."""
    frames = []
    for offset in range(2, reach + 4):
        for j in (index - offset, index + offset):
            if 0 <= j < total and len(frames) < 2 * reach:
                img = cache.get(j)
                if img is not None:
                    frames.append(img)
    if len(frames) < 2:
        return None
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def run_detection(job: Job, project: str, prop: str, cam: int, keep_manual: bool, params: DetectParams) -> dict:
    settings = pj.get_prop(project, prop)
    cam = pj.check_cam(settings, cam)
    total = pj.total_pixels(settings)
    d = pj.cam_dir(project, prop, cam)
    off = load_gray(d / "all_off.jpg")
    if off is None and params.background == "all_off":
        raise RuntimeError("all_off.jpg is missing for this camera; capture first or use the neighbor background.")
    captured = pj.captured_indices(project, prop, cam)
    if not captured:
        raise RuntimeError("No captured frames for this camera.")
    sample = load_gray(pj.frame_path(project, prop, cam, min(captured)))
    mask = build_mask(sample.shape, pj.read_polygon(project, prop, cam))

    existing = pj.read_detections(project, prop, cam)
    results: dict[int, dict] = {}
    cache = FrameCache(project, prop, cam)
    job.update(progress=0, total=total, message="Detecting")
    for index in range(total):
        job.check_cancel()
        prev = existing.get(index)
        if keep_manual and prev and prev["status"] in ("manual", "hidden"):
            results[index] = prev
        elif index not in captured:
            results[index] = Detection(None, None, 0.0, "none").to_dict()
        else:
            gray = cache.get(index)
            background = off
            if params.background == "neighbors":
                background = neighbor_background(cache, index, total)
                if background is None:
                    background = off
            if gray is None or background is None:
                results[index] = Detection(None, None, 0.0, "none").to_dict()
            else:
                results[index] = detect_frame(gray, background, mask, params).to_dict()
        if index % 50 == 49:
            pj.write_detections(project, prop, cam, {**existing, **results})
        job.update(progress=index + 1, message=f"Pixel {index + 1} of {total}")
    pj.write_detections(project, prop, cam, results)
    summary = pj.detection_summary(results, total)
    job.update(message=f"{summary['ok']} found, {summary['ambiguous']} ambiguous, {summary['none']} not found")
    return summary


def diff_preview(project: str, prop: str, cam: int, index: int, background: str = "all_off") -> bytes | None:
    """Brightness-rise image (amplified, false-colored) to make a dim pixel easy to click."""
    settings = pj.get_prop(project, prop)
    total = pj.total_pixels(settings)
    gray = load_gray(pj.frame_path(project, prop, cam, index))
    if gray is None:
        return None
    if background == "neighbors":
        bg = neighbor_background(FrameCache(project, prop, cam), index, total)
    else:
        bg = load_gray(pj.cam_dir(project, prop, cam) / "all_off.jpg")
    if bg is None:
        return None
    mask = build_mask(gray.shape, pj.read_polygon(project, prop, cam))
    diff = difference(gray, bg, mask, 3)
    boosted = cv2.convertScaleAbs(diff, alpha=4.0)
    colored = cv2.applyColorMap(boosted, cv2.COLORMAP_INFERNO)
    ok, buf = cv2.imencode(".jpg", colored, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else None
