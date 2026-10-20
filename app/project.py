"""Project folders on disk.

Layout::

    <projects root>/<project>/project.json
    <projects root>/<project>/<prop>/cam1/   meta.json, polygon.json, all_on.jpg, all_off.jpg, 0000.jpg ...
    <projects root>/<project>/<prop>/detections/cam1.csv
    <projects root>/<project>/<prop>/model/<prop>.xmodel, points.csv, <prop>.ply, result.json

A project folder is self-contained so it can be copied from the Pi to another computer.
"""

from __future__ import annotations

import copy
import csv
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = APP_DIR / "projects"

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}$")
FRAME_RE = re.compile(r"^(\d{4,6})\.jpg$")

DETECTION_STATUSES = ("ok", "ambiguous", "none", "manual", "hidden")

DEFAULT_MODEL_OPTIONS: dict[str, Any] = {
    "fill_short_gaps_only": True,
    "max_gap": 5,
    "grid_cells": None,
    "scale_factor": None,
    "min_ray_angle": 15.0,
    "outlier_fraction": 0.08,
    "use_ambiguous": False,
}

DEFAULT_PROP: dict[str, Any] = {
    "mode": "3d",
    "controller_ip": "",
    "universes": [{"universe": 2000, "channels": 510}],
    "image_size": [1920, 1080],
    "distance": 370.0,
    "fov": [65.0, 53.0],
    "on_color": [255, 255, 255],
    "settle_ms": 250,
    "reference_start": None,
    "reference_count": 4,
    "model": DEFAULT_MODEL_OPTIONS,
}

_lock = threading.RLock()
_root = Path(os.environ.get("PIXEL_MAPPER_PROJECTS", DEFAULT_ROOT))


class ProjectError(ValueError):
    pass


def set_root(path: str | Path) -> None:
    global _root
    _root = Path(path).expanduser().resolve()
    _root.mkdir(parents=True, exist_ok=True)


def root() -> Path:
    _root.mkdir(parents=True, exist_ok=True)
    return _root


def check_name(name: str, what: str = "name") -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name) or ".." in name:
        raise ProjectError(
            f"Invalid {what} '{name}'. Use letters, numbers, spaces, dot, dash, or underscore."
        )
    return name


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return copy.deepcopy(default)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


# ----------------------------------------------------------------------------- projects

def project_dir(project: str) -> Path:
    return root() / check_name(project, "project name")


def list_projects() -> list[str]:
    return sorted(
        p.name for p in root().iterdir() if p.is_dir() and (p / "project.json").exists()
    )


def create_project(project: str) -> dict:
    with _lock:
        d = project_dir(project)
        if (d / "project.json").exists():
            raise ProjectError(f"Project '{project}' already exists.")
        data = {"name": project, "props": {}}
        write_json(d / "project.json", data)
        return data


def load_project(project: str) -> dict:
    path = project_dir(project) / "project.json"
    data = read_json(path)
    if data is None:
        raise ProjectError(f"Project '{project}' not found.")
    data.setdefault("props", {})
    return data


def save_project(project: str, data: dict) -> None:
    with _lock:
        write_json(project_dir(project) / "project.json", data)


# ----------------------------------------------------------------------------- props

def normalize_prop(settings: dict) -> dict:
    """Merge user settings over defaults and coerce types."""
    out = copy.deepcopy(DEFAULT_PROP)
    for key, value in (settings or {}).items():
        if key == "model":
            out["model"] = {**DEFAULT_MODEL_OPTIONS, **(value or {})}
        elif key in out:
            out[key] = value
    if out["mode"] not in ("2d", "3d"):
        raise ProjectError("mode must be '2d' or '3d'.")
    universes = []
    for u in out["universes"]:
        uni = int(u["universe"])
        ch = int(u["channels"])
        if not 1 <= uni <= 63999:
            raise ProjectError(f"Universe {uni} is out of range 1-63999.")
        if not 3 <= ch <= 512:
            raise ProjectError(f"Universe {uni}: channel count must be 3-512.")
        universes.append({"universe": uni, "channels": ch})
    if not universes:
        raise ProjectError("At least one universe is required.")
    out["universes"] = universes
    out["controller_ip"] = (out["controller_ip"] or "").strip()
    out["image_size"] = [int(v) for v in out["image_size"]]
    out["fov"] = [float(v) for v in out["fov"]]
    out["distance"] = float(out["distance"])
    out["on_color"] = [max(0, min(255, int(v))) for v in out["on_color"]]
    out["settle_ms"] = max(0, int(out["settle_ms"]))
    out["reference_count"] = max(3, min(5, int(out["reference_count"])))
    if out["reference_start"] is not None:
        out["reference_start"] = int(out["reference_start"])
    model = out["model"]
    model["grid_cells"] = int(model["grid_cells"]) if model.get("grid_cells") else None
    if model["grid_cells"] is not None and model["grid_cells"] < 10:
        raise ProjectError("Grid cells must be at least 10.")
    model["scale_factor"] = float(model["scale_factor"]) if model.get("scale_factor") else None
    if model["scale_factor"] is not None and model["scale_factor"] <= 0:
        raise ProjectError("Scale factor must be greater than 0.")
    return out


def get_prop(project: str, prop: str) -> dict:
    data = load_project(project)
    prop = check_name(prop, "prop name")
    if prop not in data["props"]:
        raise ProjectError(f"Prop '{prop}' not found in project '{project}'.")
    return normalize_prop(data["props"][prop])


def save_prop(project: str, prop: str, settings: dict, merge: bool = True) -> dict:
    prop = check_name(prop, "prop name")
    with _lock:
        data = load_project(project)
        current = data["props"].get(prop, {}) if merge else {}
        merged = {**current, **settings}
        if merge and "model" in settings and "model" in current:
            merged["model"] = {**current["model"], **settings["model"]}
        normalized = normalize_prop(merged)
        data["props"][prop] = normalized
        save_project(project, data)
        prop_dir(project, prop).mkdir(parents=True, exist_ok=True)
        return normalized


def delete_prop(project: str, prop: str) -> None:
    with _lock:
        data = load_project(project)
        data["props"].pop(check_name(prop, "prop name"), None)
        save_project(project, data)


def prop_dir(project: str, prop: str) -> Path:
    return project_dir(project) / check_name(prop, "prop name")


def camera_count(settings: dict) -> int:
    return 3 if settings["mode"] == "3d" else 1


def check_cam(settings: dict, cam: int) -> int:
    cam = int(cam)
    if not 1 <= cam <= camera_count(settings):
        raise ProjectError(f"Camera {cam} is not valid for a {settings['mode']} prop.")
    return cam


def cam_dir(project: str, prop: str, cam: int) -> Path:
    return prop_dir(project, prop) / f"cam{int(cam)}"


def universe_layout(settings: dict) -> list[dict]:
    """Pixels are numbered in order across universes; a universe holds channels // 3 pixels."""
    layout = []
    first = 0
    for u in settings["universes"]:
        count = u["channels"] // 3
        layout.append({**u, "first_pixel": first, "pixels": count})
        first += count
    return layout


def total_pixels(settings: dict) -> int:
    return sum(u["channels"] // 3 for u in settings["universes"])


def frame_path(project: str, prop: str, cam: int, index: int) -> Path:
    return cam_dir(project, prop, cam) / f"{index:04d}.jpg"


def captured_indices(project: str, prop: str, cam: int) -> set[int]:
    d = cam_dir(project, prop, cam)
    if not d.exists():
        return set()
    out = set()
    for p in d.iterdir():
        m = FRAME_RE.match(p.name)
        if m:
            out.add(int(m.group(1)))
    return out


def read_cam_meta(project: str, prop: str, cam: int) -> dict:
    return read_json(cam_dir(project, prop, cam) / "meta.json", {}) or {}


def update_cam_meta(project: str, prop: str, cam: int, **changes: Any) -> dict:
    with _lock:
        path = cam_dir(project, prop, cam) / "meta.json"
        meta = read_json(path, {}) or {}
        meta.update(changes)
        write_json(path, meta)
        return meta


def read_polygon(project: str, prop: str, cam: int) -> list[list[int]] | None:
    data = read_json(cam_dir(project, prop, cam) / "polygon.json")
    if not data or len(data) < 3:
        return None
    return [[int(round(x)), int(round(y))] for x, y in data]


def write_polygon(project: str, prop: str, cam: int, points: list) -> None:
    if points and len(points) < 3:
        raise ProjectError("A mask polygon needs at least 3 points.")
    write_json(cam_dir(project, prop, cam) / "polygon.json", points or [])


# ----------------------------------------------------------------------------- detections

def detections_path(project: str, prop: str, cam: int) -> Path:
    return prop_dir(project, prop) / "detections" / f"cam{int(cam)}.csv"


def read_detections(project: str, prop: str, cam: int) -> dict[int, dict]:
    """Return {index: {x, y, confidence, status}}; x and y are None when unknown."""
    path = detections_path(project, prop, cam)
    out: dict[int, dict] = {}
    if not path.exists():
        return out
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                idx = int(row["index"])
            except (KeyError, ValueError):
                continue
            x = row.get("x") or ""
            y = row.get("y") or ""
            out[idx] = {
                "x": float(x) if x != "" else None,
                "y": float(y) if y != "" else None,
                "confidence": float(row.get("confidence") or 0),
                "status": row.get("status") or "none",
            }
    return out


def write_detections(project: str, prop: str, cam: int, detections: dict[int, dict]) -> None:
    path = detections_path(project, prop, cam)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with _lock:
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["index", "x", "y", "confidence", "status"])
            for idx in sorted(detections):
                d = detections[idx]
                x = "" if d.get("x") is None else f"{d['x']:.2f}"
                y = "" if d.get("y") is None else f"{d['y']:.2f}"
                w.writerow([idx, x, y, f"{d.get('confidence', 0):.3f}", d.get("status", "none")])
        os.replace(tmp, path)


def detection_summary(detections: dict[int, dict], total: int) -> dict:
    counts = {s: 0 for s in DETECTION_STATUSES}
    for i in range(total):
        status = detections.get(i, {}).get("status", "none")
        counts[status] = counts.get(status, 0) + 1
    counts["total"] = total
    counts["located"] = counts["ok"] + counts["manual"] + counts["ambiguous"]
    return counts


# ----------------------------------------------------------------------------- status

def prop_status(project: str, prop: str) -> dict:
    settings = get_prop(project, prop)
    total = total_pixels(settings)
    cams = []
    for cam in range(1, camera_count(settings) + 1):
        d = cam_dir(project, prop, cam)
        dets = read_detections(project, prop, cam)
        cams.append(
            {
                "cam": cam,
                "captured": len(captured_indices(project, prop, cam)),
                "has_all_on": (d / "all_on.jpg").exists(),
                "has_all_off": (d / "all_off.jpg").exists(),
                "has_align": (d / "align.jpg").exists(),
                "polygon": read_polygon(project, prop, cam),
                "meta": read_cam_meta(project, prop, cam),
                "detections": detection_summary(dets, total) if dets else None,
            }
        )
    model_dir = prop_dir(project, prop) / "model"
    return {
        "settings": settings,
        "total_pixels": total,
        "layout": universe_layout(settings),
        "cams": cams,
        "has_model": (model_dir / "result.json").exists(),
    }
