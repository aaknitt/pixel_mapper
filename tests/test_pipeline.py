"""End to end without hardware: synthetic frames -> detection -> review edits -> model build."""

import shutil
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app import project as pj
from tests import synthetic as syn

N = 120
GAP_SHORT = range(40, 43)   # missing from every camera, short enough to fill
GAP_LONG = range(80, 90)    # missing from every camera, too long to fill by default
CAM1_ONLY_MISSING = range(10, 14)


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pm_test_"))
        pj.set_root(cls.tmp)
        from app.main import app, jobs

        cls.client = TestClient(app)
        cls.jobs = jobs
        cls.truth = syn.helix(N)
        c = cls.client
        assert c.post("/api/projects", json={"name": "test"}).status_code == 200
        r = c.put("/api/projects/test/props/tree", json={
            "mode": "3d",
            "universes": [{"universe": 1, "channels": 300}, {"universe": 2, "channels": 60}],
            "image_size": [syn.W, syn.H],
            "fov": syn.FOV,
            "distance": syn.DISTANCE,
        })
        assert r.status_code == 200, r.text
        for cam in (1, 2, 3):
            cls._write_frames(cam)
            assert c.put(f"/api/projects/test/props/tree/cams/{cam}/align", json=syn.guides()).status_code == 200
            poly = [[150, 20], [syn.W - 150, 20], [syn.W - 150, syn.H - 20], [150, syn.H - 20]]
            assert c.put(f"/api/projects/test/props/tree/cams/{cam}/polygon", json={"points": poly}).status_code == 200
            cls._run_job(f"/api/projects/test/props/tree/cams/{cam}/detect", {"background": "all_off"})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _write_frames(cls, cam):
        d = pj.cam_dir("test", "tree", cam)
        d.mkdir(parents=True, exist_ok=True)
        bg = syn.background(cam)
        cv2.imwrite(str(d / "all_off.jpg"), bg)
        uv = syn.project(cls.truth, cam)
        for i in range(N):
            hidden = i in GAP_SHORT or i in GAP_LONG or (cam == 1 and i in CAM1_ONLY_MISSING)
            frame = syn.frame_with_pixel(bg, None if hidden else uv[i], seed=cam * 1000 + i)
            cv2.imwrite(str(pj.frame_path("test", "tree", cam, i)), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        pj.update_cam_meta("test", "tree", cam, image_size=[syn.W, syn.H], capture_complete=True)

    @classmethod
    def _run_job(cls, url, body):
        r = cls.client.post(url, json=body)
        assert r.status_code == 200, r.text
        deadline = time.time() + 120
        while cls.jobs.busy() and time.time() < deadline:
            time.sleep(0.05)
        job = cls.jobs.current()
        assert job.state == "done", job.error

    def test_detection_finds_pixels(self):
        data = self.client.get("/api/projects/test/props/tree/cams/2/detections").json()
        uv = syn.project(self.truth, 2)
        errors = []
        for it in data["items"]:
            i = it["index"]
            if i in GAP_SHORT or i in GAP_LONG:
                self.assertEqual(it["status"], "none", i)
            else:
                self.assertEqual(it["status"], "ok", i)
                errors.append(np.hypot(it["x"] - uv[i, 0], it["y"] - uv[i, 1]))
        self.assertLess(max(errors), 1.5)

    def test_review_edits(self):
        url = "/api/projects/test/props/tree/cams/1/detections"
        r = self.client.put(f"{url}/10", json={"status": "manual", "x": 123.5, "y": 77})
        self.assertEqual(r.json()["status"], "manual")
        r = self.client.put(f"{url}/11", json={"status": "hidden"})
        self.assertEqual(r.json()["status"], "hidden")
        self.assertEqual(self.client.put(f"{url}/12", json={"status": "ok"}).status_code, 400)
        items = {it["index"]: it for it in self.client.get(url).json()["items"]}
        self.assertEqual((items[10]["x"], items[10]["status"]), (123.5, "manual"))
        self.assertEqual(items[11]["status"], "hidden")
        # restore so the model test sees the original detections
        self.client.put(f"{url}/10", json={"status": "none"})
        self.client.put(f"{url}/11", json={"status": "none"})

    def test_diff_image(self):
        r = self.client.get("/api/projects/test/props/tree/cams/1/image/5?diff=1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/jpeg")

    def test_model_short_gaps_only(self):
        r = self.client.post("/api/projects/test/props/tree/model", json={"fill_short_gaps_only": True, "max_gap": 5})
        self.assertEqual(r.status_code, 200, r.text)
        res = r.json()
        self.assertEqual(res["total"], N)
        self.assertEqual(res["empty_runs"], [[GAP_LONG.start, GAP_LONG.stop - 1]])
        self.assertEqual(res["filled"], len(GAP_SHORT))
        pts = res["points"]
        errs = [
            np.linalg.norm(np.array(pts[i]) - self.truth[i])
            for i in range(N) if res["notes"][i] not in ("missing", "filled")
        ]
        self.assertLess(float(np.mean(errs)), 2.0)
        self.assertLess(float(np.max(errs)), 6.0)
        for i in CAM1_ONLY_MISSING:
            self.assertEqual(res["notes"][i], "single pair")
        for i in GAP_LONG:
            self.assertIsNone(pts[i][0])
        for kind in ("xmodel", "csv", "ply"):
            d = self.client.get(f"/api/projects/test/props/tree/model/download/{kind}")
            self.assertEqual(d.status_code, 200, kind)
        ply = self.client.get("/api/projects/test/props/tree/model/download/ply").text
        self.assertIn(f"element vertex {N - len(GAP_LONG)}", ply)

    def test_model_scale_factor(self):
        url = "/api/projects/test/props/tree/model"
        res = self.client.post(url, json={"scale_factor": 1.7}).json()
        self.assertEqual(res["grid"]["units_per_cell"], 1.7)
        self.assertEqual(res["grid"]["sized_by"], "scale factor")
        coarse = self.client.post(url, json={"scale_factor": 5}).json()
        self.assertLess(coarse["grid"]["rows"], res["grid"]["rows"])
        self.assertEqual(self.client.post(url, json={"scale_factor": -1}).status_code, 400)
        back = self.client.post(url, json={"scale_factor": None, "grid_cells": 80}).json()
        self.assertEqual(back["grid"]["sized_by"], "80 cells on the longest side")
        self.client.post(url, json={"grid_cells": None})

    def test_neighbor_background(self):
        self._run_job("/api/projects/test/props/tree/cams/3/detect", {"background": "neighbors"})
        data = self.client.get("/api/projects/test/props/tree/cams/3/detections").json()
        uv = syn.project(self.truth, 3)
        for it in data["items"]:
            i = it["index"]
            if i in GAP_SHORT or i in GAP_LONG:
                self.assertEqual(it["status"], "none", i)
            else:
                self.assertEqual(it["status"], "ok", i)
                self.assertLess(np.hypot(it["x"] - uv[i, 0], it["y"] - uv[i, 1]), 1.5)

    def test_model_fill_all(self):
        res = self.client.post("/api/projects/test/props/tree/model", json={"fill_short_gaps_only": False}).json()
        self.assertEqual(res["empty_runs"], [])
        self.assertEqual(res["missing"], 0)
        self.assertEqual(res["filled"], len(GAP_SHORT) + len(GAP_LONG))
        # leave the saved option at its default for other runs
        self.client.post("/api/projects/test/props/tree/model", json={"fill_short_gaps_only": True})


if __name__ == "__main__":
    unittest.main()
