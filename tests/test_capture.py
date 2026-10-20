"""Capture loop with a fake camera and fake lights."""

import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from app import capture
from app import project as pj
from app.jobs import Job, JobCancelled


class FakeLights:
    def __init__(self):
        self.lit: list[int] | None = None
        self.calls = []

    def configure(self, settings):
        pass

    def all_on(self, color):
        self.lit = None
        self.calls.append("on")

    def all_off(self):
        self.lit = []
        self.calls.append("off")

    def show(self, indices, color, label=None):
        self.lit = list(indices)
        self.calls.append(tuple(indices))


class FakeCamera:
    is_open = True

    def __init__(self, lights, cancel_after=None, job=None):
        self.lights = lights
        self.frames = 0
        self.cancel_after = cancel_after
        self.job = job
        self.exposure = []

    def fresh_frame(self, skip=2, timeout=5.0):
        self.frames += 1
        if self.cancel_after and self.frames > self.cancel_after:
            self.job._cancel.set()
        img = np.zeros((60, 80, 3), np.uint8)
        if self.lights.lit:
            img[5, self.lights.lit[0] % 80] = 255
        return img

    def set_auto_exposure(self, auto):
        self.exposure.append(auto)
        return True


class CaptureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pm_cap_"))
        pj.set_root(self.tmp)
        pj.create_project("p")
        pj.save_prop("p", "bush", {"mode": "2d", "universes": [{"universe": 1, "channels": 30}], "settle_ms": 0})
        capture.WARMUP_SECONDS = 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_capture_then_resume(self):
        lights = FakeLights()
        cam = FakeCamera(lights)
        job = Job("capture", "test")
        result = capture.run_capture(job, cam, lights, "p", "bush", 1, resume=False)
        self.assertEqual(result["captured"], 10)
        self.assertEqual(pj.captured_indices("p", "bush", 1), set(range(10)))
        d = pj.cam_dir("p", "bush", 1)
        self.assertTrue((d / "all_on.jpg").exists() and (d / "all_off.jpg").exists())
        meta = pj.read_cam_meta("p", "bush", 1)
        self.assertTrue(meta["capture_complete"])
        self.assertEqual(meta["image_size"], [80, 60])
        self.assertEqual(cam.exposure, [False, True])  # locked for the walk, released after
        self.assertEqual(lights.calls[-1], "off")

        pj.frame_path("p", "bush", 1, 4).unlink()
        lights.calls.clear()
        capture.run_capture(Job("capture", "resume"), cam, lights, "p", "bush", 1, resume=True)
        self.assertEqual([c for c in lights.calls if isinstance(c, tuple)], [(4,)])
        self.assertEqual(pj.captured_indices("p", "bush", 1), set(range(10)))

    def test_cancel_leaves_lights_off_and_partial_frames(self):
        lights = FakeLights()
        job = Job("capture", "test")
        cam = FakeCamera(lights, cancel_after=5, job=job)
        with self.assertRaises(JobCancelled):
            capture.run_capture(job, cam, lights, "p", "bush", 1, resume=False)
        self.assertEqual(lights.calls[-1], "off")
        self.assertEqual(cam.exposure[-1], True)
        n = len(pj.captured_indices("p", "bush", 1))
        self.assertTrue(0 < n < 10)
        self.assertFalse(pj.read_cam_meta("p", "bush", 1)["capture_complete"])


if __name__ == "__main__":
    unittest.main()
