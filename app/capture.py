"""Walk every pixel and save one still per pixel. No detection happens here."""

from __future__ import annotations

import time

import cv2

from . import project as pj
from .camera import Camera
from .jobs import Job
from .sacn import Lights

JPEG_QUALITY = 92
WARMUP_SECONDS = 2.5


def _save(path, frame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]):
        raise RuntimeError(f"Could not write {path}")


def run_capture(job: Job, camera: Camera, lights: Lights, project: str, prop: str, cam: int, resume: bool) -> dict:
    settings = pj.get_prop(project, prop)
    cam = pj.check_cam(settings, cam)
    if not camera.is_open:
        raise RuntimeError("Open the camera first.")
    lights.configure(settings)

    total = pj.total_pixels(settings)
    out_dir = pj.cam_dir(project, prop, cam)
    out_dir.mkdir(parents=True, exist_ok=True)
    done = pj.captured_indices(project, prop, cam) if resume else set()
    if not resume:
        for p in out_dir.glob("[0-9][0-9][0-9][0-9]*.jpg"):
            p.unlink()
    settle = settings["settle_ms"] / 1000.0
    color = settings["on_color"]
    job.update(progress=len(done), total=total, message="Warming up camera")

    have_refs = (out_dir / "all_on.jpg").exists() and (out_dir / "all_off.jpg").exists()
    exposure_locked = False
    try:
        lights.all_on(color)
        time.sleep(WARMUP_SECONDS)
        job.check_cancel()
        exposure_locked = camera.set_auto_exposure(False)
        time.sleep(0.5)
        if not (resume and have_refs):
            _save(out_dir / "all_on.jpg", camera.fresh_frame(skip=3))
        lights.all_off()
        time.sleep(max(settle, 0.5))
        off_frame = camera.fresh_frame(skip=3)
        if not (resume and have_refs):
            _save(out_dir / "all_off.jpg", off_frame)
        height, width = off_frame.shape[:2]
        pj.update_cam_meta(
            project,
            prop,
            cam,
            image_size=[width, height],
            total_pixels=total,
            exposure_locked=exposure_locked,
            capture_started=time.strftime("%Y-%m-%d %H:%M:%S"),
            capture_complete=False,
        )

        count = len(done)
        started = time.time()
        for index in range(total):
            job.check_cancel()
            if index in done:
                continue
            lights.show([index], color, label=f"capturing pixel {index}")
            time.sleep(settle)
            frame = camera.fresh_frame(skip=2)
            _save(pj.frame_path(project, prop, cam, index), frame)
            count += 1
            elapsed = time.time() - started
            new = count - len(done)
            remaining = (total - count) * elapsed / new if new else 0
            job.update(progress=count, message=f"Pixel {index + 1} of {total}, about {remaining:.0f} s left")
    finally:
        try:
            lights.all_off()
        except Exception:
            pass
        if exposure_locked:
            camera.set_auto_exposure(True)

    pj.update_cam_meta(
        project,
        prop,
        cam,
        capture_complete=True,
        capture_finished=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    job.update(message=f"Captured {total} pixels")
    return {"captured": total}
