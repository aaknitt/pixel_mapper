"""Synthetic prop: a helix seen from three camera spots, rendered as capture frames."""

from __future__ import annotations

import math

import cv2
import numpy as np

from app import reconstruct as rc

W, H = 960, 540
FOV = [65.0, 53.0]
DISTANCE = 370.0
DPP_H = FOV[0] / W
DPP_V = DPP_H * (FOV[1] / H) / (FOV[0] / W)


def helix(n: int) -> np.ndarray:
    t = np.linspace(0, 1, n)
    z = -120 + 250 * t
    r = 70 * (1 - t) + 10
    a = t * 2 * math.pi * 6
    return np.stack([r * np.cos(a), r * np.sin(a), z], axis=1)


def project(points: np.ndarray, cam: int) -> np.ndarray:
    """Image (u, v) for each 3D point seen from camera cam (1-based)."""
    pos = rc.camera_positions(DISTANCE)[cam - 1]
    out = np.zeros((len(points), 2))
    for i, (x, y, z) in enumerate(points):
        dx, dy = x - pos[0], y - pos[1]
        heading = math.degrees(math.atan2(dy, dx))
        theta = (rc.CAMERA_ANGLES_DEG[cam - 1] + 180.0 - heading + 180.0) % 360.0 - 180.0
        dist = math.hypot(dx, dy)
        phi = math.degrees(math.atan2(z, dist))
        out[i] = (W / 2 + theta / DPP_H, H / 2 - phi / DPP_V)
    return out


def guides() -> dict:
    half = rc.GUIDE_SPAN_DEG / 2 / DPP_H
    return {"left_x": W / 2 - half, "right_x": W / 2 + half}


def background(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = rng.integers(10, 30, (H, W, 3), dtype=np.uint8)
    cv2.circle(img, (60, 60), 12, (250, 250, 250), -1)  # a porch light outside the mask
    return img


def frame_with_pixel(bg: np.ndarray, uv, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = (bg.astype(np.int16) + rng.integers(-3, 4, bg.shape)).astype(np.int16)
    if uv is not None:
        cv2.circle(img, (int(round(uv[0])), int(round(uv[1]))), 4, (230, 230, 230), -1)
    img = cv2.GaussianBlur(np.clip(img, 0, 255).astype(np.uint8), (5, 5), 0)
    return img
