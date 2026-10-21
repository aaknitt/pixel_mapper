"""Model exports: xLights custom model (.xmodel), points CSV, and PLY point cloud.

xLights custom model string: layers separated by "|", rows by ";", columns by ",", each
cell holding a 1-based pixel number or empty. Row 0 is the top and layer 0 is the front.
Pixels that are not placed are simply absent; xLights still derives each node's channel
from its number, so the remaining pixels keep their correct channels.
"""

from __future__ import annotations

import itertools
from xml.sax.saxutils import quoteattr

import numpy as np

SOURCE_VERSION = "2024.01"
# xLights warns that a custom model wider, higher or deeper than this slows rendering.
XLIGHTS_MAX_SIDE = 300
# Automatic sizing keeps the grid under this many cells. The .xmodel is about one byte per
# cell, and xLights renders effects on a buffer with one pixel per cell.
AUTO_MAX_CELLS = 2_000_000
# Automatic sizing separates all but this fraction of the closest neighbor pairs.
AUTO_SPACING_PERCENTILE = 10


def grid_cells_default(mode: str) -> int:
    return 120 if mode == "3d" else 200


def _placed(points: np.ndarray, dims: int) -> list[int]:
    return [i for i in range(len(points)) if not np.isnan(points[i, :dims]).any()]


def nearest_neighbor_distances(coords: np.ndarray, block: int = 256) -> np.ndarray:
    n = len(coords)
    out = np.full(n, np.inf)
    if n < 2:
        return out
    sq = (coords**2).sum(axis=1)
    for start in range(0, n, block):
        part = coords[start : start + block]
        d2 = sq[start : start + block, None] + sq[None, :] - 2.0 * part @ coords.T
        rows = np.arange(len(part))
        d2[rows, rows + start] = np.inf
        out[start : start + len(part)] = d2.min(axis=1)
    return np.sqrt(np.clip(out, 0.0, None))


def _grid_cell_count(spans: np.ndarray, step: float) -> float:
    return float(np.prod(np.rint(spans / step) + 1))


def auto_step(coords: np.ndarray, mode: str) -> tuple[float, str]:
    """Pick a step small enough that neighboring pixels get their own cells.

    Two points share a cell only if they are closer than step * sqrt(dims), so the step is
    the typical closest-neighbor distance divided by sqrt(dims). It is never coarser than
    the old fixed default, and never finer than the xLights side limit or the file-size limit.
    """
    spans = coords.max(axis=0) - coords.min(axis=0)
    span = float(spans.max())
    if span <= 0:
        return 1.0, "auto"
    coarse = span / (grid_cells_default(mode) - 1)
    nn = nearest_neighbor_distances(coords)
    nn = nn[np.isfinite(nn) & (nn > span * 1e-6)]
    if not len(nn):
        return coarse, f"auto, {grid_cells_default(mode)} cells on the longest side"
    spacing = float(np.percentile(nn, AUTO_SPACING_PERCENTILE)) / np.sqrt(coords.shape[1])
    if spacing >= coarse:
        return coarse, f"auto, {grid_cells_default(mode)} cells on the longest side"
    floor = max(span / (XLIGHTS_MAX_SIDE - 1), spacing)
    if _grid_cell_count(spans, floor) <= AUTO_MAX_CELLS:
        return floor, "auto from pixel spacing" if floor == spacing else "auto, limited by xLights size"
    lo, hi = floor, coarse
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if _grid_cell_count(spans, mid) <= AUTO_MAX_CELLS else (mid, hi)
    return hi, "auto, limited by model size"


def grid_sizing(
    points: np.ndarray, mode: str, grid_cells: int | None = None, scale_factor: float | None = None
) -> tuple[float, str]:
    """Model units per grid cell, and how that value was chosen.

    A scale factor is used as-is, the same as xLights_output_scale_factor in the old scripts
    (3D units are the camera-distance units; 2D units are camera image pixels). Grid cells set
    the number of cells on the longest side. With neither, the step comes from pixel spacing.
    """
    if scale_factor:
        return float(scale_factor), "scale factor"
    dims = 3 if mode == "3d" else 2
    placed = _placed(points, dims)
    if not placed:
        return 1.0, "auto"
    coords = points[placed, :dims]
    if not grid_cells:
        return auto_step(coords, mode)
    span = float((coords.max(axis=0) - coords.min(axis=0)).max())
    step = span / max(grid_cells - 1, 1) if span > 0 else 1.0
    return step, f"{grid_cells} cells on the longest side"


def grid_step(points: np.ndarray, mode: str, grid_cells: int | None = None, scale_factor: float | None = None) -> float:
    return grid_sizing(points, mode, grid_cells, scale_factor)[0]


def to_grid(
    points: np.ndarray, mode: str, grid_cells: int | None = None, scale_factor: float | None = None
) -> tuple[dict[int, tuple[int, ...]], tuple[int, ...], int]:
    """Map placed pixels to integer cells.

    3D axes: columns = X, rows = Z (top row is highest), layers = Y with layer 0 at min Y,
    which keeps the model right-handed when viewed from the front.
    2D axes: columns = X, rows = Y (top row is highest).
    Returns ({pixel index: cell}, grid shape as (layers, rows, cols), cells nudged).
    """
    dims = 3 if mode == "3d" else 2
    placed = _placed(points, dims)
    if not placed:
        return {}, (1, 1, 1), 0
    coords = points[placed, :dims]
    mins = coords.min(axis=0)
    step = grid_step(points, mode, grid_cells, scale_factor)
    cells = np.rint((coords - mins) / step).astype(int)

    if mode == "3d":
        col = cells[:, 0]
        row = cells[:, 2].max() - cells[:, 2]
        layer = cells[:, 1]
    else:
        col = cells[:, 0]
        row = cells[:, 1].max() - cells[:, 1]
        layer = np.zeros(len(cells), int)

    shape = (int(layer.max()) + 1, int(row.max()) + 1, int(col.max()) + 1)
    occupied: set[tuple[int, int, int]] = set()
    result: dict[int, tuple[int, int, int]] = {}
    nudged = 0
    for k, idx in enumerate(placed):
        cell = (int(layer[k]), int(row[k]), int(col[k]))
        if cell in occupied:
            cell = _nearest_free(cell, occupied, shape, dims)
            nudged += 1
        occupied.add(cell)
        result[idx] = cell
    if nudged:
        shape = tuple(max(shape[a], max(c[a] for c in result.values()) + 1) for a in range(3))
    return result, shape, nudged


def _nearest_free(cell, occupied, shape, dims, max_radius: int = 6):
    for radius in range(1, max_radius + 1):
        best = None
        for dl in (range(-radius, radius + 1) if dims == 3 else (0,)):
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    if max(abs(dl), abs(dr), abs(dc)) != radius:
                        continue
                    cand = (cell[0] + dl, cell[1] + dr, cell[2] + dc)
                    if min(cand) < 0 or cand in occupied:
                        continue
                    dist = dl * dl + dr * dr + dc * dc
                    if best is None or dist < best[0]:
                        best = (dist, cand)
        if best:
            return best[1]
    # Extremely dense cluster: append to the right edge.
    for extra in itertools.count(shape[2]):
        cand = (cell[0], cell[1], extra)
        if cand not in occupied:
            return cand


def custom_model_string(cells: dict[int, tuple[int, int, int]], shape: tuple[int, int, int]) -> str:
    layers, rows, cols = shape
    lookup = {cell: idx + 1 for idx, cell in cells.items()}
    out_layers = []
    for l in range(layers):
        out_rows = []
        for r in range(rows):
            out_rows.append(",".join(str(lookup.get((l, r, c), "")) for c in range(cols)))
        out_layers.append(";".join(out_rows))
    return "|".join(out_layers)


def xmodel_xml(name: str, cells: dict, shape: tuple[int, int, int]) -> str:
    layers, rows, cols = shape
    attrs = {
        "name": name,
        "parm1": str(cols),
        "parm2": str(rows),
        "Depth": str(layers),
        "StringType": "RGB Nodes",
        "Transparency": "0",
        "PixelSize": "2",
        "ModelBrightness": "",
        "Antialias": "1",
        "StrandNames": "",
        "NodeNames": "",
        "CustomModel": custom_model_string(cells, shape),
        "SourceVersion": SOURCE_VERSION,
    }
    body = " ".join(f"{k}={quoteattr(v)}" for k, v in attrs.items())
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<custommodel {body} >\n</custommodel>\n'


def points_csv(points: np.ndarray, notes: list[str], mode: str) -> str:
    lines = ["index,x,y,z,status"]
    for i, p in enumerate(points):
        def fmt(v):
            return "" if np.isnan(v) else f"{v:.3f}"
        z = fmt(p[2]) if mode == "3d" else ""
        lines.append(f"{i},{fmt(p[0])},{fmt(p[1])},{z},{notes[i]}")
    return "\n".join(lines) + "\n"


def _index_color(i: int, n: int) -> tuple[int, int, int]:
    """Blue to red along the string, so wiring order is visible in a viewer."""
    t = i / max(n - 1, 1)
    return int(255 * t), int(80 + 100 * (1 - abs(2 * t - 1))), int(255 * (1 - t))


def ply_text(points: np.ndarray, mode: str) -> str:
    dims = 3 if mode == "3d" else 2
    placed = _placed(points, dims)
    header = [
        "ply",
        "format ascii 1.0",
        "comment pixel_mapper export; pixel = 0-based index along the string",
        f"element vertex {len(placed)}",
        "property float x",
        "property float y",
        "property float z",
        "property int pixel",
        "property uchar red",
        "property uchar green",
        "property uchar blue",
        "end_header",
    ]
    body = []
    n = len(points)
    for i in placed:
        x, y = points[i, 0], points[i, 1]
        z = points[i, 2] if mode == "3d" else 0.0
        r, g, b = _index_color(i, n)
        body.append(f"{x:.3f} {y:.3f} {z:.3f} {i} {r} {g} {b}")
    return "\n".join(header + body) + "\n"
