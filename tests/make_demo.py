"""Create a synthetic demo project (no camera or lights needed) to try Review and Model.

    python -m tests.make_demo C:/temp/pm_demo
    python run.py --projects C:/temp/pm_demo
"""

import sys
import time

import cv2
from fastapi.testclient import TestClient

from app import project as pj
from tests import synthetic as syn

N = 300


def main(folder: str) -> None:
    pj.set_root(folder)
    from app.main import app, jobs

    c = TestClient(app)
    if "demo" not in pj.list_projects():
        c.post("/api/projects", json={"name": "demo"})
    c.put("/api/projects/demo/props/tree", json={
        "mode": "3d",
        # Unused universes and a non-routable controller IP so trying the demo cannot light real props.
        "universes": [{"universe": 63000, "channels": 510}, {"universe": 63001, "channels": 390}],
        "controller_ip": "192.0.2.1",
        "image_size": [syn.W, syn.H],
        "fov": syn.FOV,
        "distance": syn.DISTANCE,
    })
    truth = syn.helix(N)
    for cam in (1, 2, 3):
        d = pj.cam_dir("demo", "tree", cam)
        d.mkdir(parents=True, exist_ok=True)
        bg = syn.background(cam)
        cv2.imwrite(str(d / "all_off.jpg"), bg)
        cv2.imwrite(str(d / "all_on.jpg"), bg)
        uv = syn.project(truth, cam)
        for i in range(N):
            hidden = (cam == 1 and 100 <= i < 104) or 200 <= i < 210 or (cam == 2 and i % 37 == 0)
            frame = syn.frame_with_pixel(bg, None if hidden else uv[i], seed=cam * 1000 + i)
            cv2.imwrite(str(pj.frame_path("demo", "tree", cam, i)), frame)
        pj.update_cam_meta("demo", "tree", cam, image_size=[syn.W, syn.H], capture_complete=True,
                           exposure_locked=True)
        c.put(f"/api/projects/demo/props/tree/cams/{cam}/align", json=syn.guides())
        poly = [[150, 20], [syn.W - 150, 20], [syn.W - 150, syn.H - 20], [150, syn.H - 20]]
        c.put(f"/api/projects/demo/props/tree/cams/{cam}/polygon", json={"points": poly})
        c.post(f"/api/projects/demo/props/tree/cams/{cam}/detect", json={})
        while jobs.busy():
            time.sleep(0.1)
    c.post("/api/projects/demo/props/tree/model", json={})
    print(f"Demo project written to {pj.root()}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo_projects")
