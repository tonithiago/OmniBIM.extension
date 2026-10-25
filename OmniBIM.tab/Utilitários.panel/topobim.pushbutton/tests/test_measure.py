# -*- coding: utf-8 -*-
from __future__ import division
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from topobim_measure import distance, polygon_area, ray_hit, snap_vertex


class MeasureTests(unittest.TestCase):
    def test_snap_preserves_original_coordinates_and_rejects_interpolation(self):
        point = (780000.123456,9840000.654321,11.987654)
        picked, ambiguous = snap_vertex([point],point[0]+0.02,point[1]+0.01,0.1,0.02)
        self.assertIs(picked,point)
        self.assertFalse(ambiguous)
        self.assertEqual(snap_vertex([point],point[0]+1,point[1],0.1,0.02),(None,False))

    def test_nearby_vertices_require_zoom_to_resolve(self):
        points = [(0,0,11),(0.01,0,14)]
        self.assertEqual(snap_vertex(points,0,0,0.08,0.02),(None,True))
        self.assertEqual(snap_vertex(points,0,0,0.008,0.002),(points[0],False))

    def test_slope_distance_and_horizontal_projection(self):
        spatial, horizontal = distance((780000,9840000,11),(780003,9840004,23))
        self.assertAlmostEqual(spatial, 13)
        self.assertAlmostEqual(horizontal, 5)

    def test_area_is_horizontal_and_stable_at_utm_coordinates(self):
        points = [(780000,9840000,10),(780010,9840000,20),
                  (780010,9840005,30),(780000,9840005,5)]
        self.assertAlmostEqual(polygon_area(points), 50)
        self.assertAlmostEqual(polygon_area(list(reversed(points))), 50)

    def test_concave_polygon_and_invalid_rings(self):
        ring = [(0,0,0),(4,0,0),(4,1,0),(1,1,0),(1,4,0),(0,4,0)]
        self.assertAlmostEqual(polygon_area(ring), 7)
        for invalid in ([(0,0,0),(4,4,0),(0,4,0),(4,0,0)],
                        [(0,0,0),(1,1,0),(2,2,0)],
                        [(0,0,0),(1,0,0),(1,0,0),(0,1,0)]):
            with self.assertRaises(ValueError):
                polygon_area(invalid)

    def test_ray_chooses_front_surface_and_rejects_misses(self):
        vertices = [(0,0,0),(10,0,0),(0,10,0),(0,0,5),(10,0,5),(0,10,5)]
        triangles = [(0,1,2),(3,4,5)]
        self.assertEqual(ray_hit((2,2,20),(0,0,-1),vertices,triangles),(2,2,5))
        self.assertEqual(ray_hit((2,2,-10),(0,0,1),vertices,triangles),(2,2,0))
        self.assertIsNone(ray_hit((20,20,20),(0,0,-1),vertices,triangles))
        self.assertIsNone(ray_hit((2,2,20),(1,0,0),vertices,triangles))


if __name__ == '__main__':
    unittest.main()
