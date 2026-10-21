"""Build a prop's model from its detections and write the downloads."""

from __future__ import annotations

import time

import numpy as np

from . import project as pj
from . import reconstruct as rc
from . import xlights as xl

USABLE = {"ok", "manual"}
# Roughly one byte of .xmodel per grid cell.
LARGE_GRID_CELLS = 5_000_000
MAX_GRID_CELLS = 60_000_000


def detections_array(project: str, prop: str, cam: int, total: int, use_ambiguous: bool) -> np.ndarray:
    usable = USABLE | ({"ambiguous"} if use_ambiguous else set())
    arr = np.full((total, 2), np.nan)
    for idx, d in pj.read_detections(project, prop, cam).items():
        if 0 <= idx < total and d["status"] in usable and d["x"] is not None:
            arr[idx] = (d["x"], d["y"])
    return arr


def model_paths(project: str, prop: str) -> dict:
    d = pj.prop_dir(project, prop) / "model"
    return {
        "dir": d,
        "xmodel": d / f"{prop}.xmodel",
        "csv": d / "points.csv",
        "ply": d / f"{prop}.ply",
        "result": d / "result.json",
    }


def build(project: str, prop: str, options: dict | None = None) -> dict:
    settings = pj.save_prop(project, prop, {"model": options or {}}) if options else pj.get_prop(project, prop)
    opts = settings["model"]
    mode = settings["mode"]
    total = pj.total_pixels(settings)
    ncam = pj.camera_count(settings)

    dets = [detections_array(project, prop, c, total, opts["use_ambiguous"]) for c in range(1, ncam + 1)]
    missing_cams = [c for c in range(1, ncam + 1) if not pj.detections_path(project, prop, c).exists()]
    if missing_cams:
        raise pj.ProjectError(f"Run detection for camera(s) {missing_cams} first.")

    warnings: list[str] = []
    stats: dict = {}
    if mode == "3d":
        scales = []
        for c in range(1, ncam + 1):
            meta = pj.read_cam_meta(project, prop, c)
            size = meta.get("image_size") or settings["image_size"]
            scale = rc.camera_scale(size, settings["fov"], meta.get("guides"))
            if not scale.from_guides:
                warnings.append(f"Camera {c} has no saved alignment guides; using the full-frame FOV instead.")
            scales.append(scale)
        points, notes, stats = rc.solve_3d(
            dets, scales, settings["distance"], opts["min_ray_angle"], opts["outlier_fraction"]
        )
        dims = 3
    else:
        meta = pj.read_cam_meta(project, prop, 1)
        size = meta.get("image_size") or settings["image_size"]
        points, notes = rc.solve_2d(dets[0], size)
        dims = 2

    measured = int((~np.isnan(points[:, :dims]).any(axis=1)).sum())
    max_gap = int(opts["max_gap"]) if opts["fill_short_gaps_only"] else None
    points, filled, empty_runs = rc.fill_gaps(points, dims, max_gap)
    for i in np.nonzero(filled)[0]:
        notes[i] = "filled"

    grid_cells = int(opts["grid_cells"]) if opts["grid_cells"] else None
    step, sized_by = xl.grid_sizing(points, mode, grid_cells, opts["scale_factor"])
    cells, shape, nudged = xl.to_grid(points, mode, scale_factor=step)
    cell_count = shape[0] * shape[1] * shape[2]
    if cell_count > MAX_GRID_CELLS:
        raise pj.ProjectError(
            f"The xLights grid would be {shape[2]} x {shape[1]} x {shape[0]} cells, too large to write. "
            "Use a larger scale factor or fewer grid cells."
        )
    if cell_count > LARGE_GRID_CELLS:
        warnings.append(
            f"The .xmodel is large (about {cell_count / 1e6:.0f} MB). "
            "A larger scale factor or fewer grid cells makes it smaller."
        )

    paths = model_paths(project, prop)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    paths["xmodel"].write_text(xl.xmodel_xml(prop, cells, shape), encoding="utf-8")
    paths["csv"].write_text(xl.points_csv(points, notes, mode), encoding="utf-8")
    paths["ply"].write_text(xl.ply_text(points, mode), encoding="utf-8")

    def clean(v):
        return None if np.isnan(v) else round(float(v), 3)

    result = {
        "built": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "total": total,
        "measured": measured,
        "filled": int(filled.sum()),
        "missing": total - measured - int(filled.sum()),
        "empty_runs": [[int(s), int(e)] for s, e in empty_runs],
        "grid": {
            "layers": shape[0],
            "rows": shape[1],
            "cols": shape[2],
            "units_per_cell": round(step, 4),
            "sized_by": sized_by,
            "nudged": nudged,
            "nodes": len(cells),
        },
        "stats": stats,
        "warnings": warnings,
        "options": opts,
        "points": [[clean(p[0]), clean(p[1]), clean(p[2]) if mode == "3d" else None] for p in points],
        "notes": notes,
    }
    pj.write_json(paths["result"], result)
    return result


def load_result(project: str, prop: str) -> dict | None:
    return pj.read_json(model_paths(project, prop)["result"])
