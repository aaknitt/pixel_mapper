import math
import re
import struct
import unittest
from xml.etree import ElementTree

import numpy as np

from app import detect
from app import reconstruct as rc
from app import sacn
from app import xlights as xl
from tests import synthetic as syn


class SacnTest(unittest.TestCase):
    def test_packet_layout(self):
        data = bytes(range(30))
        cid = bytes(range(16))
        pkt = sacn.build_packet(2001, data, sequence=7, cid=cid, source_name="test")
        self.assertEqual(len(pkt), 126 + len(data))
        self.assertEqual(pkt[4:16], b"ASC-E1.17\x00\x00\x00")
        self.assertEqual(struct.unpack("!H", pkt[16:18])[0], 0x7000 | (len(pkt) - 16))
        self.assertEqual(struct.unpack("!I", pkt[18:22])[0], 4)
        self.assertEqual(pkt[22:38], cid)
        self.assertEqual(struct.unpack("!H", pkt[38:40])[0], 0x7000 | (len(pkt) - 38))
        self.assertEqual(struct.unpack("!I", pkt[40:44])[0], 2)
        self.assertEqual(pkt[44:48], b"test")
        self.assertEqual(pkt[108], 100)
        self.assertEqual(pkt[111], 7)
        self.assertEqual(struct.unpack("!H", pkt[113:115])[0], 2001)
        self.assertEqual(struct.unpack("!H", pkt[115:117])[0], 0x7000 | (len(pkt) - 115))
        self.assertEqual(pkt[117], 2)
        self.assertEqual(pkt[118], 0xA1)
        self.assertEqual(struct.unpack("!H", pkt[123:125])[0], len(data) + 1)
        self.assertEqual(pkt[125], 0)
        self.assertEqual(pkt[126:], data)

    def test_multicast_address(self):
        self.assertEqual(sacn.multicast_address(2000), "239.255.7.208")
        self.assertEqual(sacn.multicast_address(1), "239.255.0.1")

    def test_pixel_spans_universes(self):
        sent = []

        class FakeSender:
            def send(self, universe, data):
                sent.append((universe, data))

            def close(self):
                pass

        lights = sacn.Lights()
        lights.configure({"controller_ip": "127.0.0.1", "universes": [
            {"universe": 1, "channels": 510}, {"universe": 2, "channels": 60}]})
        lights._sender = FakeSender()
        lights.show([169, 170], [1, 2, 3])
        by_uni = dict(sent)
        self.assertEqual(len(by_uni[1]), 510)
        self.assertEqual(by_uni[1][507:510], bytes([1, 2, 3]))
        self.assertEqual(by_uni[2][0:3], bytes([1, 2, 3]))
        self.assertEqual(sum(by_uni[2][3:]), 0)


class TriangulationTest(unittest.TestCase):
    def test_exact_point_from_three_cameras(self):
        truth = np.array([[25.0, -40.0, 60.0], [0.0, 0.0, -30.0], [-55.0, 10.0, 5.0]])
        scales = [rc.camera_scale([syn.W, syn.H], syn.FOV, syn.guides()) for _ in range(3)]
        dets = [syn.project(truth, cam) for cam in (1, 2, 3)]
        points, notes, _ = rc.solve_3d(dets, scales, syn.DISTANCE)
        np.testing.assert_allclose(points, truth, atol=1e-6)
        self.assertEqual(notes, ["3 pairs"] * 3)

    def test_guides_give_scale(self):
        s = rc.camera_scale([1920, 1080], [65, 53], {"left_x": 460, "right_x": 1460})
        self.assertTrue(s.from_guides)
        self.assertAlmostEqual(s.cx, 960)
        self.assertAlmostEqual(s.deg_per_px_h, 60 / 1000)
        fallback = rc.camera_scale([1920, 1080], [65, 53], None)
        self.assertFalse(fallback.from_guides)
        self.assertAlmostEqual(fallback.deg_per_px_h, 65 / 1920)

    def test_grazing_rays_rejected(self):
        p1, p2 = np.array([0.0, 0.0]), np.array([100.0, 0.0])
        self.assertIsNone(rc.triangulate_pair(p1, 0.0, 0.0, p2, math.radians(179.0), 0.0, 15.0))
        self.assertIsNotNone(rc.triangulate_pair(p1, math.radians(45), 0.0, p2, math.radians(135), 0.0, 15.0))

    def test_outlier_pair_dropped(self):
        good = [np.array([10.0, 10.0, 10.0]), np.array([11.0, 10.0, 10.0])]
        bad = np.array([80.0, -50.0, 10.0])
        point, note = rc.combine_candidates([good[0], bad, good[1]], threshold=20)
        self.assertEqual(note, "outlier dropped")
        np.testing.assert_allclose(point, [10.5, 10, 10])


class GapFillTest(unittest.TestCase):
    def setUp(self):
        self.pts = np.stack([np.arange(20.0), np.arange(20.0) * 2, np.zeros(20)], axis=1)
        self.pts[3:5] = np.nan       # short interior gap
        self.pts[8:16] = np.nan      # long interior gap
        self.pts[0] = np.nan         # leading gap

    def test_short_only(self):
        out, filled, empty = rc.fill_gaps(self.pts, 3, max_gap=5)
        np.testing.assert_allclose(out[3:5, 0], [3, 4])
        self.assertEqual(empty, [(0, 0), (8, 15)])
        self.assertTrue(np.isnan(out[10, 0]))
        self.assertEqual(int(filled.sum()), 2)

    def test_fill_everything(self):
        out, filled, empty = rc.fill_gaps(self.pts, 3, max_gap=None)
        self.assertEqual(empty, [])
        np.testing.assert_allclose(out[8:16, 0], np.arange(8, 16))
        self.assertEqual(out[0, 0], 1.0)
        self.assertEqual(int(filled.sum()), 11)


class DetectFrameTest(unittest.TestCase):
    def setUp(self):
        import cv2

        self.cv2 = cv2
        self.bg = np.full((200, 300), 20, np.uint8)
        self.params = detect.DetectParams()

    def lit(self, *spots):
        img = self.bg.copy()
        for (x, y, level) in spots:
            self.cv2.circle(img, (x, y), 4, level, -1)
        return img

    def test_single_spot(self):
        d = detect.detect_frame(self.lit((100, 50, 220)), self.bg, None, self.params)
        self.assertEqual(d.status, "ok")
        self.assertAlmostEqual(d.x, 100, delta=0.5)
        self.assertAlmostEqual(d.y, 50, delta=0.5)

    def test_two_bright_spots_are_ambiguous(self):
        d = detect.detect_frame(self.lit((100, 50, 220), (250, 150, 210)), self.bg, None, self.params)
        self.assertEqual(d.status, "ambiguous")

    def test_dim_reflection_is_ignored(self):
        d = detect.detect_frame(self.lit((100, 50, 220), (250, 150, 80)), self.bg, None, self.params)
        self.assertEqual(d.status, "ok")

    def test_mask_excludes_outside_light(self):
        mask = detect.build_mask(self.bg.shape, [[50, 0], [200, 0], [200, 120], [50, 120]])
        d = detect.detect_frame(self.lit((100, 50, 150), (280, 180, 250)), self.bg, mask, self.params)
        self.assertEqual(d.status, "ok")
        self.assertAlmostEqual(d.x, 100, delta=0.5)

    def test_nothing_lit(self):
        d = detect.detect_frame(self.bg.copy(), self.bg, None, self.params)
        self.assertEqual(d.status, "none")


def parse_xmodel(text):
    node = ElementTree.fromstring(text)
    cols, rows, depth = int(node.get("parm1")), int(node.get("parm2")), int(node.get("Depth"))
    cells = {}
    layers = node.get("CustomModel").split("|")
    assert len(layers) == depth
    for l, layer in enumerate(layers):
        row_strs = layer.split(";")
        assert len(row_strs) == rows
        for r, row in enumerate(row_strs):
            vals = row.split(",")
            assert len(vals) == cols
            for c, v in enumerate(vals):
                if v:
                    cells[int(v)] = (l, r, c)
    return cells, (depth, rows, cols)


class XModelTest(unittest.TestCase):
    def test_3d_grid_dimensions_and_orientation(self):
        pts = np.array([
            [0.0, 0.0, 0.0],      # bottom, left, front
            [10.0, 0.0, 0.0],     # right
            [0.0, 0.0, 10.0],     # top
            [0.0, 10.0, 0.0],     # back
            [np.nan, np.nan, np.nan],
        ])
        cells, shape, nudged = xl.to_grid(pts, "3d", grid_cells=11)
        text = xl.xmodel_xml("tree", cells, shape)
        parsed, pshape = parse_xmodel(text)
        self.assertEqual(pshape, (11, 11, 11))
        self.assertEqual(nudged, 0)
        self.assertNotIn(5, parsed)  # missing pixel is absent, not placed at the origin
        self.assertEqual(parsed[1], (0, 10, 0))
        self.assertEqual(parsed[2], (0, 10, 10))
        self.assertEqual(parsed[3], (0, 0, 0))
        self.assertEqual(parsed[4], (10, 10, 0))

    def test_scale_factor_sets_units_per_cell(self):
        pts = np.array([[0.0, 0.0, 0.0], [10.0, 4.0, 20.0]])
        self.assertEqual(xl.grid_step(pts, "3d", grid_cells=11, scale_factor=2.0), 2.0)
        cells, shape, _ = xl.to_grid(pts, "3d", grid_cells=11, scale_factor=2.0)
        self.assertEqual(shape, (3, 11, 6))  # 4/2+1 deep, 20/2+1 high, 10/2+1 wide
        _, shape_small, _ = xl.to_grid(pts, "3d", scale_factor=5.0)
        self.assertEqual(shape_small, (2, 5, 3))
        self.assertAlmostEqual(xl.grid_step(pts, "3d", grid_cells=11), 2.0)

    def test_auto_sizing_follows_pixel_spacing(self):
        # A tightly wrapped trunk inside a tall prop: 120 cells on the longest side crowds it.
        t = np.linspace(0, 40 * np.pi, 600)
        trunk = np.column_stack([7 * np.cos(t), 7 * np.sin(t), np.linspace(0, 60, 600)])
        top = np.column_stack([np.zeros(150), np.zeros(150), np.linspace(70, 240, 150)])
        pts = np.vstack([trunk, top])
        _, _, fixed_nudged = xl.to_grid(pts, "3d", grid_cells=120)
        step, sized_by = xl.grid_sizing(pts, "3d")
        cells, shape, nudged = xl.to_grid(pts, "3d")
        self.assertGreater(fixed_nudged, 50)
        self.assertLessEqual(nudged, len(pts) * 0.02)
        self.assertLess(step, 240 / 119)
        self.assertTrue(sized_by.startswith("auto"))
        self.assertLessEqual(max(shape), xl.XLIGHTS_MAX_SIDE)
        self.assertLessEqual(shape[0] * shape[1] * shape[2], xl.AUTO_MAX_CELLS)
        parsed, _ = parse_xmodel(xl.xmodel_xml("tree", cells, shape))
        self.assertEqual(set(parsed), set(range(1, len(pts) + 1)))

    def test_auto_sizing_never_coarser_than_default(self):
        pts = np.array([[0.0, 0.0, 0.0], [100.0, 50.0, 80.0], [50.0, 100.0, 20.0]])
        self.assertAlmostEqual(xl.grid_step(pts, "3d"), 100.0 / 119)

    def test_auto_sizing_respects_file_size_limit(self):
        # Very close pixels in a large cube would need a huge grid to separate them all.
        rng = np.random.default_rng(1)
        corners = rng.uniform(0, 1000, size=(50, 3))
        corners[0], corners[1] = 0.0, 1000.0
        line = np.column_stack([np.linspace(400, 475, 750), np.full(750, 500.0), np.full(750, 500.0)])
        pts = np.vstack([corners, line])
        step, sized_by = xl.grid_sizing(pts, "3d")
        cells, shape, _ = xl.to_grid(pts, "3d")
        self.assertEqual(sized_by, "auto, limited by model size")
        self.assertLessEqual(shape[0] * shape[1] * shape[2], xl.AUTO_MAX_CELLS)
        self.assertLessEqual(max(shape), xl.XLIGHTS_MAX_SIDE)
        self.assertEqual(len(set(cells.values())), len(pts))

    def test_collisions_nudged(self):
        pts = np.array([[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [10.0, 10.0, 0.0]])
        cells, shape, nudged = xl.to_grid(pts, "2d", grid_cells=11)
        self.assertEqual(nudged, 1)
        self.assertEqual(len(set(cells.values())), 3)
        parsed, _ = parse_xmodel(xl.xmodel_xml("bush", cells, shape))
        self.assertEqual(set(parsed), {1, 2, 3})

    def test_2d_top_row_is_highest(self):
        pts = np.array([[0.0, 0.0, np.nan], [0.0, 100.0, np.nan]])
        cells, shape, _ = xl.to_grid(pts, "2d", grid_cells=5)
        self.assertEqual(shape[0], 1)
        self.assertEqual(cells[1][1], 0)
        self.assertEqual(cells[0][1], shape[1] - 1)

    def test_name_is_escaped(self):
        text = xl.xmodel_xml('a"b<c', {0: (0, 0, 0)}, (1, 1, 1))
        self.assertEqual(ElementTree.fromstring(text).get("name"), 'a"b<c')

    def test_ply_header_counts(self):
        pts = np.array([[0.0, 1.0, 2.0], [np.nan] * 3, [3.0, 4.0, 5.0]])
        text = xl.ply_text(pts, "3d")
        self.assertIn("element vertex 2", text)
        body = text.split("end_header\n")[1].strip().splitlines()
        self.assertEqual(len(body), 2)
        self.assertTrue(re.match(r"3\.000 4\.000 5\.000 2 ", body[1]))


if __name__ == "__main__":
    unittest.main()
