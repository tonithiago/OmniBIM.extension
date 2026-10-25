# -*- coding: utf-8 -*-
from __future__ import division
import math
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from topobim_core import Point
from topobim_preview import terrain_mesh, sample_points, camera_frame


class PreviewTests(unittest.TestCase):
    def test_grid_has_complete_area_and_preserves_heights(self):
        points = [Point(x, y, x * 0.3 + y * 0.2) for x in range(8) for y in range(9)]
        before = list(points)
        vertices, triangles = terrain_mesh(points)
        area = 0
        used = set()
        for indices in triangles:
            used.update(indices)
            a, b, c = [vertices[i] for i in indices]
            cross = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
            self.assertGreater(cross, 0)
            area += cross / 2
        self.assertAlmostEqual(area, 56)
        self.assertEqual(len(used), len(points))
        self.assertEqual(points, before)
        for source, vertex in zip(points, vertices):
            self.assertAlmostEqual(vertex[2], source.Z - 1.85)

    def test_utm_translation_does_not_change_mesh(self):
        points = [Point(x, y, (x*y) % 3) for x in range(5) for y in range(6)]
        moved = [Point(p.E + 780000, p.N + 9840000, p.Z + 300) for p in points]
        self.assertEqual(terrain_mesh(points), terrain_mesh(moved))

    def test_collinear_and_insufficient_points(self):
        self.assertEqual(terrain_mesh([Point(0, 0, 0)])[1], [])
        self.assertEqual(terrain_mesh([Point(i, i, i) for i in range(12)])[1], [])

    def test_display_budget_and_elevation_extremes(self):
        points = [Point(x, y, (x + y) % 7) for x in range(100) for y in range(100)]
        points[101] = Point(1, 1, -100)
        points[9050] = Point(90, 50, 200)
        selected = sample_points(points)
        self.assertLessEqual(len(selected), 1400)
        self.assertIn(points[101], selected)
        self.assertIn(points[9050], selected)
        self.assertEqual(sample_points(list(reversed(points))), selected)
        self.assertEqual(len(points), 10000)

    def test_camera_basis_stays_orthonormal(self):
        for yaw in (0, 45, 200):
            for pitch in (-85, 0, 35, 85):
                basis = camera_frame(yaw, pitch)
                for vector in basis:
                    self.assertAlmostEqual(sum(v*v for v in vector), 1)
                for i, j in ((0,1), (0,2), (1,2)):
                    self.assertAlmostEqual(sum(a*b for a,b in zip(basis[i], basis[j])), 0)

    def test_large_sample_covers_the_survey_boundary(self):
        points = [Point(780000+x, 9840000+y, (x*y) % 19)
                  for x in range(150) for y in range(140)]
        vertices, triangles = terrain_mesh(points)
        area = 0
        for indices in triangles:
            a, b, c = [vertices[i] for i in indices]
            area += ((b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])) / 2
        self.assertAlmostEqual(area, 149*139)


if __name__ == '__main__':
    unittest.main()
