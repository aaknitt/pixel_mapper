"""HTTP API and static UI."""

from __future__ import annotations

import platform
import time
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import cv2

from . import detect as dt
from . import model as md
from . import project as pj
from .camera import Camera, probe
from .capture import run_capture
from .jobs import JobRunner
from .sacn import Lights

STATIC_DIR = pj.APP_DIR / "static"
LOCAL_SETTINGS = pj.APP_DIR / "local_settings.json"

app = FastAPI(title="Pixel Mapper")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

jobs = JobRunner()
_camera = Camera()
_lights: Lights | None = None


def camera() -> Camera:
    return _camera


def lights() -> Lights:
    global _lights
    if _lights is None:
        _lights = Lights()
    return _lights


@app.exception_handler(pj.ProjectError)
async def project_error(_: Request, exc: pj.ProjectError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(RuntimeError)
async def runtime_error(_: Request, exc: RuntimeError):
    return JSONResponse({"detail": str(exc)}, status_code=409)


def local_settings() -> dict:
    return pj.read_json(LOCAL_SETTINGS, {"camera_source": "0"}) or {"camera_source": "0"}


# ----------------------------------------------------------------------------- general

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/info")
def info():
    return {
        "platform": platform.system(),
        "machine": platform.machine(),
        "projects_root": str(pj.root()),
        "settings": local_settings(),
    }


@app.put("/api/settings")
def put_settings(body: dict = Body(...)):
    settings = {**local_settings(), **body}
    pj.write_json(LOCAL_SETTINGS, settings)
    return settings


# ----------------------------------------------------------------------------- projects

@app.get("/api/projects")
def list_projects():
    return pj.list_projects()


@app.post("/api/projects")
def create_project(body: dict = Body(...)):
    return pj.create_project(pj.check_name(body.get("name", ""), "project name"))


@app.get("/api/projects/{project}")
def get_project(project: str):
    return pj.load_project(project)


@app.put("/api/projects/{project}/props/{prop}")
def put_prop(project: str, prop: str, body: dict = Body(...)):
    return pj.save_prop(project, prop, body)


@app.delete("/api/projects/{project}/props/{prop}")
def delete_prop(project: str, prop: str):
    pj.delete_prop(project, prop)
    return {"ok": True}


@app.get("/api/projects/{project}/props/{prop}")
def get_prop(project: str, prop: str):
    return pj.prop_status(project, prop)


# ----------------------------------------------------------------------------- lights

@app.post("/api/projects/{project}/props/{prop}/lights")
def set_lights(project: str, prop: str, body: dict = Body(...)):
    if jobs.busy() and jobs.current().kind == "capture":
        raise RuntimeError("Lights are in use by the running capture.")
    settings = pj.get_prop(project, prop)
    lt = lights()
    lt.configure(settings)
    total = pj.total_pixels(settings)
    color = settings["on_color"]
    action = body.get("action")
    if action == "off":
        lt.all_off()
    elif action == "on":
        lt.all_on(color)
    elif action in ("pixel", "range"):
        start = max(0, min(int(body.get("start", 0)), total - 1))
        count = 1 if action == "pixel" else max(1, min(int(body.get("count", 1)), 5))
        indices = list(range(start, min(start + count, total)))
        label = f"pixel {start}" if count == 1 else f"pixels {indices[0]}-{indices[-1]}"
        lt.show(indices, color, label)
    else:
        raise pj.ProjectError("action must be off, on, pixel, or range")
    return {"state": lt.state, "error": lt.last_error}


@app.post("/api/projects/{project}/props/{prop}/reference")
def set_reference(project: str, prop: str, body: dict = Body(...)):
    """Lock (or clear with start=null) the vertical reference run used at every camera spot."""
    start = body.get("start")
    changes: dict[str, Any] = {"reference_start": None if start is None else int(start)}
    if body.get("count") is not None:
        changes["reference_count"] = int(body["count"])
    return pj.save_prop(project, prop, changes)


# ----------------------------------------------------------------------------- camera

@app.get("/api/camera")
def camera_status():
    return camera().status()


@app.get("/api/camera/probe")
def camera_probe():
    if camera().is_open:
        raise RuntimeError("Close the camera before scanning for others.")
    return probe()


@app.post("/api/camera/open")
def camera_open(body: dict = Body(...)):
    source = str(body.get("source", local_settings().get("camera_source", "0")))
    size = body.get("size") or [1920, 1080]
    camera().open(source, size)
    pj.write_json(LOCAL_SETTINGS, {**local_settings(), "camera_source": source})
    return camera().status()


@app.post("/api/camera/close")
def camera_close():
    if jobs.busy() and jobs.current().kind == "capture":
        raise RuntimeError("Capture is running.")
    camera().close()
    return camera().status()


@app.get("/api/camera/stream")
def camera_stream(w: int = 960, fps: float = 8.0):
    cam = camera()
    if not cam.is_open:
        raise HTTPException(503, "Camera is not open.")
    period = 1.0 / max(1.0, min(fps, 20.0))

    def frames():
        last_seq = -1
        while cam.is_open:
            _, seq = cam.latest()
            if seq != last_seq:
                data = cam.jpeg(max_width=w, quality=70)
                last_seq = seq
                if data:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n"
            time.sleep(period)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/camera/snapshot.jpg")
def camera_snapshot(w: int | None = None):
    data = camera().jpeg(max_width=w, quality=90)
    if data is None:
        raise HTTPException(503, "Camera is not open.")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ----------------------------------------------------------------------------- align / mask

@app.put("/api/projects/{project}/props/{prop}/cams/{cam}/align")
def save_align(project: str, prop: str, cam: int, body: dict = Body(...)):
    settings = pj.get_prop(project, prop)
    cam = pj.check_cam(settings, cam)
    guides = {"left_x": float(body["left_x"]), "right_x": float(body["right_x"])}
    if guides["right_x"] - guides["left_x"] < 10:
        raise pj.ProjectError("The two guide lines must be at least 10 pixels apart.")
    changes: dict[str, Any] = {"guides": guides, "aligned_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    changes["reference"] = (
        [settings["reference_start"], settings["reference_count"]] if settings["reference_start"] is not None else None
    )
    cam_obj = camera()
    if cam_obj.is_open:
        frame, _ = cam_obj.latest()
        out = pj.cam_dir(project, prop, cam)
        out.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out / "align.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        changes["image_size"] = [frame.shape[1], frame.shape[0]]
    return pj.update_cam_meta(project, prop, cam, **changes)


@app.put("/api/projects/{project}/props/{prop}/cams/{cam}/polygon")
def save_polygon(project: str, prop: str, cam: int, body: dict = Body(...)):
    settings = pj.get_prop(project, prop)
    cam = pj.check_cam(settings, cam)
    pj.write_polygon(project, prop, cam, body.get("points") or [])
    return {"polygon": pj.read_polygon(project, prop, cam)}


# ----------------------------------------------------------------------------- jobs

@app.get("/api/job")
def get_job():
    job = jobs.current()
    return job.to_dict() if job else None


@app.post("/api/job/cancel")
def cancel_job():
    return {"cancelled": jobs.cancel()}


@app.post("/api/projects/{project}/props/{prop}/cams/{cam}/capture")
def start_capture(project: str, prop: str, cam: int, body: dict = Body(default={})):
    settings = pj.get_prop(project, prop)
    cam = pj.check_cam(settings, cam)
    resume = bool(body.get("resume", False))
    cam_obj, lt = camera(), lights()
    job = jobs.start(
        "capture",
        f"Capture {prop} camera {cam}",
        lambda j: run_capture(j, cam_obj, lt, project, prop, cam, resume),
    )
    return job.to_dict()


@app.post("/api/projects/{project}/props/{prop}/cams/{cam}/detect")
def start_detect(project: str, prop: str, cam: int, body: dict = Body(default={})):
    settings = pj.get_prop(project, prop)
    cam = pj.check_cam(settings, cam)
    params = dt.DetectParams(
        min_peak=int(body.get("min_peak", 40)),
        background=body.get("background", "all_off"),
    )
    keep = bool(body.get("keep_manual", True))
    job = jobs.start(
        "detect",
        f"Detect {prop} camera {cam}",
        lambda j: dt.run_detection(j, project, prop, cam, keep, params),
    )
    return job.to_dict()


# ----------------------------------------------------------------------------- review

@app.get("/api/projects/{project}/props/{prop}/cams/{cam}/detections")
def get_detections(project: str, prop: str, cam: int):
    settings = pj.get_prop(project, prop)
    cam = pj.check_cam(settings, cam)
    total = pj.total_pixels(settings)
    dets = pj.read_detections(project, prop, cam)
    captured = pj.captured_indices(project, prop, cam)
    items = []
    for i in range(total):
        d = dets.get(i, {"x": None, "y": None, "confidence": 0.0, "status": "none"})
        items.append({"index": i, **d, "captured": i in captured})
    return {
        "total": total,
        "detected": bool(dets),
        "items": items,
        "summary": pj.detection_summary(dets, total),
        "meta": pj.read_cam_meta(project, prop, cam),
        "polygon": pj.read_polygon(project, prop, cam),
    }


@app.put("/api/projects/{project}/props/{prop}/cams/{cam}/detections/{index}")
def put_detection(project: str, prop: str, cam: int, index: int, body: dict = Body(...)):
    settings = pj.get_prop(project, prop)
    cam = pj.check_cam(settings, cam)
    total = pj.total_pixels(settings)
    if not 0 <= index < total:
        raise pj.ProjectError("Pixel index out of range.")
    status = body.get("status")
    if status not in ("manual", "hidden", "ok", "none"):
        raise pj.ProjectError("status must be manual, hidden, ok, or none")
    dets = pj.read_detections(project, prop, cam)
    current = dets.get(index, {"x": None, "y": None, "confidence": 0.0, "status": "none"})
    if status == "manual":
        current = {"x": float(body["x"]), "y": float(body["y"]), "confidence": 1.0, "status": "manual"}
    elif status == "hidden":
        current = {"x": None, "y": None, "confidence": 0.0, "status": "hidden"}
    elif status == "ok":
        if current.get("x") is None:
            raise pj.ProjectError("Nothing to accept: this pixel has no detected position.")
        current = {**current, "status": "ok"}
    else:
        current = {"x": None, "y": None, "confidence": 0.0, "status": "none"}
    dets[index] = current
    pj.write_detections(project, prop, cam, dets)
    return {"index": index, **current}


@app.get("/api/projects/{project}/props/{prop}/cams/{cam}/image/{name}")
def get_image(project: str, prop: str, cam: int, name: str, diff: bool = False, background: str = "all_off"):
    settings = pj.get_prop(project, prop)
    cam = pj.check_cam(settings, cam)
    headers = {"Cache-Control": "no-cache"}
    if name in ("all_on", "all_off", "align"):
        path = pj.cam_dir(project, prop, cam) / f"{name}.jpg"
        if not path.exists():
            raise HTTPException(404, f"{name}.jpg not found")
        return FileResponse(path, media_type="image/jpeg", headers=headers)
    if not name.isdigit():
        raise HTTPException(404, "Unknown image")
    index = int(name)
    if diff:
        data = dt.diff_preview(project, prop, cam, index, background)
        if data is None:
            raise HTTPException(404, "Frame or background missing")
        return Response(data, media_type="image/jpeg", headers=headers)
    path = pj.frame_path(project, prop, cam, index)
    if not path.exists():
        raise HTTPException(404, "Frame not captured")
    return FileResponse(path, media_type="image/jpeg", headers=headers)


# ----------------------------------------------------------------------------- model

@app.post("/api/projects/{project}/props/{prop}/model")
def build_model(project: str, prop: str, body: dict = Body(default={})):
    return md.build(project, prop, body or None)


@app.get("/api/projects/{project}/props/{prop}/model")
def get_model(project: str, prop: str):
    pj.get_prop(project, prop)
    return md.load_result(project, prop)


@app.get("/api/projects/{project}/props/{prop}/model/download/{kind}")
def download_model(project: str, prop: str, kind: str):
    paths = md.model_paths(project, prop)
    if kind not in ("xmodel", "csv", "ply"):
        raise HTTPException(404, "Unknown download")
    path = paths[kind]
    if not path.exists():
        raise HTTPException(404, "Build the model first.")
    filename = path.name if kind != "csv" else f"{prop}_points.csv"
    return FileResponse(path, filename=filename, media_type="application/octet-stream")
