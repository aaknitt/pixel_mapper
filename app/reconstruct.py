"""Turn per-camera 2D detections into model coordinates.

3D geometry: three cameras on an equilateral triangle, distance D from its center, all
aimed at the center and at the same height. Seen from above, camera 1 is at +X and cameras
2 and 3 follow counter-clockwise (camera 2 is to the right of camera 1 as you face the prop).
Z is up, measured from camera height.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

CAMERA_ANGLES_DEG = (0.0, 120.0, 240.0)
GUIDE_SPAN_DEG = 60.0  # from one corner, the other two corners of an equilateral triangle are 60 degrees apart


@dataclass
class CameraScale:
    cx: float
    cy: float
    deg_per_px_h: float
    deg_per_px_v: float
    from_guides: bool


def camera_scale(image_size: list[int], fov: list[float], guides: dict | None) -> CameraScale:
    """Degrees per image pixel. Uses the saved alignment guides when available."""
    w, h = image_size
    fov_h, fov_v = fov
    left = (guides or {}).get("left_x")
    right = (guides or {}).get("right_x")
    if left is not None and right is not None and right - left > 10:
        cx = (left + right) / 2.0
        dpp_h = GUIDE_SPAN_DEG / (right - left)
        from_guides = True
    else:
        cx = w / 2.0
        dpp_h = fov_h / w
        from_guides = False
    dpp_v = dpp_h * (fov_v / h) / (fov_h / w)
    return CameraScale(cx, h / 2.0, dpp_h, dpp_v, from_guides)


def image_to_angles(uv: np.ndarray, scale: CameraScale) -> tuple[np.ndarray, np.ndarray]:
    """Horizontal angle (positive = right of center) and elevation (positive = up), degrees."""
    theta = (uv[:, 0] - scale.cx) * scale.deg_per_px_h
    phi = (scale.cy - uv[:, 1]) * scale.deg_per_px_v
    return theta, phi


def camera_positions(distance: float) -> np.ndarray:
    a = np.radians(CAMERA_ANGLES_DEG)
    return np.stack([distance * np.cos(a), distance * np.sin(a)], axis=1)


def triangulate_pair(
    p1: np.ndarray, heading1: float, phi1: float,
    p2: np.ndarray, heading2: float, phi2: float,
    min_ray_angle: float,
) -> np.ndarray | None:
    """Intersect two horizontal rays; height is the mean of each camera's elevation estimate."""
    d1 = np.array([math.cos(heading1), math.sin(heading1)])
    d2 = np.array([math.cos(heading2), math.sin(heading2)])
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < math.sin(math.radians(min_ray_angle)):
        return None
    delta = p2 - p1
    t1 = (delta[0] * d2[1] - delta[1] * d2[0]) / cross
    t2 = (delta[0] * d1[1] - delta[1] * d1[0]) / cross
    if t1 <= 0 or t2 <= 0:
        return None
    xy = p1 + t1 * d1
    z = (math.tan(math.radians(phi1)) * t1 + math.tan(math.radians(phi2)) * t2) / 2.0
    return np.array([xy[0], xy[1], z])


def combine_candidates(cands: list[np.ndarray], threshold: float) -> tuple[np.ndarray, str]:
    """Average pair estimates that agree; flag when none agree."""
    if len(cands) == 1:
        return cands[0], "single pair"
    if len(cands) == 2:
        if np.linalg.norm(cands[0] - cands[1]) <= threshold:
            return (cands[0] + cands[1]) / 2.0, "2 pairs"
        return (cands[0] + cands[1]) / 2.0, "disagree"
    best = None
    for i in range(3):
        for j in range(i + 1, 3):
            dist = np.linalg.norm(cands[i] - cands[j])
            if best is None or dist < best[0]:
                best = (dist, i, j)
    dist, i, j = best
    if dist > threshold:
        return np.mean(cands, axis=0), "disagree"
    k = 3 - i - j
    pair_mean = (cands[i] + cands[j]) / 2.0
    if np.linalg.norm(cands[k] - pair_mean) <= threshold:
        return np.mean(cands, axis=0), "3 pairs"
    return pair_mean, "outlier dropped"


def solve_3d(
    detections: list[np.ndarray],
    scales: list[CameraScale],
    distance: float,
    min_ray_angle: float = 15.0,
    outlier_fraction: float = 0.08,
) -> tuple[np.ndarray, list[str], dict]:
    """detections: three (N, 2) arrays of image coordinates, NaN where unknown."""
    n = len(detections[0])
    positions = camera_positions(distance)
    angles = [image_to_angles(d, s) for d, s in zip(detections, scales)]
    threshold = outlier_fraction * distance
    points = np.full((n, 3), np.nan)
    notes = ["missing"] * n
    stats = {"grazing_or_behind": 0, "outlier_dropped": 0, "disagree": 0, "single_pair": 0}

    for i in range(n):
        cands = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            ta, pa = angles[a][0][i], angles[a][1][i]
            tb, pb = angles[b][0][i], angles[b][1][i]
            if np.isnan(ta) or np.isnan(tb):
                continue
            ha = math.radians(CAMERA_ANGLES_DEG[a] + 180.0 - ta)
            hb = math.radians(CAMERA_ANGLES_DEG[b] + 180.0 - tb)
            pt = triangulate_pair(positions[a], ha, pa, positions[b], hb, pb, min_ray_angle)
            if pt is None:
                stats["grazing_or_behind"] += 1
            else:
                cands.append(pt)
        if not cands:
            continue
        point, note = combine_candidates(cands, threshold)
        points[i] = point
        notes[i] = note
        if note == "outlier dropped":
            stats["outlier_dropped"] += 1
        elif note == "disagree":
            stats["disagree"] += 1
        elif note == "single pair":
            stats["single_pair"] += 1
    return points, notes, stats


def solve_2d(detection: np.ndarray, image_size: list[int]) -> tuple[np.ndarray, list[str]]:
    """2D props: image x to the right, image y flipped so up is positive."""
    n = len(detection)
    points = np.full((n, 3), np.nan)
    points[:, 0] = detection[:, 0]
    points[:, 1] = image_size[1] - detection[:, 1]
    notes = ["measured" if not np.isnan(detection[i, 0]) else "missing" for i in range(n)]
    return points, notes


def missing_runs(valid: np.ndarray) -> list[tuple[int, int]]:
    runs = []
    start = None
    for i, ok in enumerate(valid):
        if not ok and start is None:
            start = i
        elif ok and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(valid) - 1))
    return runs


def fill_gaps(
    points: np.ndarray, dims: int, max_gap: int | None
) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]]]:
    """Linear interpolation along the string.

    With max_gap set, only interior runs of at most max_gap missing pixels are filled. With
    max_gap None every run is filled, and runs at either end take the nearest known value.
    Returns (points, filled mask, runs left empty).
    """
    out = points.copy()
    n = len(points)
    valid = ~np.isnan(points[:, :dims]).any(axis=1)
    filled = np.zeros(n, bool)
    runs = missing_runs(valid)
    if valid.sum() < 2:
        return out, filled, runs
    idx = np.arange(n)
    left_empty = []
    for start, end in runs:
        interior = start > 0 and end < n - 1
        if max_gap is None or (interior and end - start + 1 <= max_gap):
            span = idx[start : end + 1]
            for d in range(dims):
                out[start : end + 1, d] = np.interp(span, idx[valid], points[valid, d])
            filled[start : end + 1] = True
        else:
            left_empty.append((start, end))
    return out, filled, left_empty
