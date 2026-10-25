# -*- coding: utf-8 -*-
from __future__ import division, unicode_literals
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from topobim_core import Point
import topobim_floor_geometry as g


def loop(values, z=0):
    return [Point(x, y, z) for x, y in values]


class FloorGeometryTests(unittest.TestCase):
    def setUp(self):
        self.square = loop([(0,0), (10,0), (10,10), (0,10)])

    def test_closed_polylines(self):
        loops, issues = g.assemble([self.square+self.square[:1]])
        self.assertEqual(1, len(loops))
        self.assertEqual([], issues)
        self.assertEqual(100, g.region_area(g.regions(loops)[0]))

    def test_unordered_and_reversed_curves_join(self):
        a,b,c,d = self.square
        loops, issues = g.assemble([[b,a], [d,c], [a,d], [c,b]])
        self.assertEqual(1, len(loops))
        self.assertFalse(issues)

    def test_open_and_ambiguous_curves_are_diagnostics(self):
        a,b,c,d = self.square
        loops, issues = g.assemble([[a,b], [b,c], [b,d]])
        self.assertFalse(loops)
        self.assertTrue(issues)

    def test_concave_area_is_preserved(self):
        concave = loop([(0,0),(4,0),(4,1),(1,1),(1,4),(0,4)])
        region = g.regions([concave])[0]
        self.assertEqual(7, g.region_area(region))
        self.assertFalse(g.contains(Point(2,2,0), region))

    def test_nested_hole_island_and_disconnected_region(self):
        hole = loop([(2,2),(8,2),(8,8),(2,8)])
        island = loop([(3,3),(4,3),(4,4),(3,4)])
        other = loop([(20,0),(21,0),(21,1),(20,1)])
        regions = g.regions([hole, other, island, self.square])
        self.assertEqual(3, len(regions))
        self.assertEqual(66, sum(g.region_area(r) for r in regions))
        self.assertFalse(g.contains(Point(5,5,0), regions[0]))
        self.assertTrue(g.contains(Point(2,5,0), regions[0]))

    def test_crossing_duplicate_and_touching_loops_rejected(self):
        for other in (self.square, loop([(8,8),(12,8),(12,12),(8,12)]),
                      loop([(10,2),(12,2),(12,4),(10,4)])):
            self.assertRaises(ValueError, g.regions, [self.square, other])

    def test_self_crossing_rejected(self):
        self.assertRaises(ValueError, g.clean_loop, loop([(0,0),(4,4),(0,4),(4,0)]))

    def test_large_survey_coordinates_keep_area(self):
        shifted = [Point(p.E+780000,p.N+9840000,p.Z) for p in self.square]
        self.assertEqual(100, g.area(shifted))

    def surface(self):
        a,b,c,d = loop([(0,0),(10,0),(10,10),(0,10)], 10)
        peak = Point(5,5,14)
        return g.Surface([(a,b,peak), (b,c,peak), (c,d,peak), (d,a,peak)])

    def test_surface_sample_actual_piecewise_slope(self):
        surface = self.surface()
        self.assertAlmostEqual(14, surface.height(Point(5,5,0)))
        self.assertAlmostEqual(12, surface.height(Point(2.5,5,0)))
        self.assertRaises(ValueError, surface.height, Point(11,5,0))
        self.assertAlmostEqual(10, surface.height(Point(-0.00000001,5,0)))
        self.assertRaises(ValueError, surface.height, Point(-0.001,5,0))

    def test_constraints_keep_peak_boundary_crossings_and_breaklines(self):
        region = g.Region(loop([(1,2),(8,2),(8,9),(1,9)]), [])
        loops, points, lines = self.surface().constraints(region)
        self.assertTrue(any(g.distance(p,Point(5,5,0)) < 1e-6 for p in points))
        self.assertGreater(len(loops[0]),4)
        self.assertGreater(len(lines),0)
        for p in points:
            self.assertTrue(g.contains(p,region))
            self.assertAlmostEqual(p.Z,self.surface().height(p))

    def test_breaklines_never_cross_hole(self):
        hole = loop([(4,4),(6,4),(6,6),(4,6)])
        region = g.Region(self.square,[hole])
        loops, points, lines = self.surface().constraints(region)
        self.assertEqual(2,len(loops))
        self.assertFalse(any(g.inside(g.interpolate(a,b,0.5),hole,False) for a,b in lines))
        self.assertFalse(any(g.distance(p,Point(5,5,0)) < 1e-6 for p in points))

    def test_no_floor_outside_terrain_and_limit_is_explicit(self):
        self.assertRaises(ValueError, self.surface().constraints, g.Region(loop([(0,0),(20,0),(20,20),(0,20)]), []))
        self.assertRaises(ValueError, self.surface().constraints, g.Region(self.square,[]), 2)

    def test_floor_may_extend_beyond_terrain_without_clipping(self):
        region = g.Region(loop([(-2,-2),(12,-2),(12,12),(-2,12)]), [])
        loops, points, lines = self.surface().constraints(region, allow_outside=True)
        self.assertEqual(196, abs(g.area(loops[0])))
        self.assertTrue(any(p.E < 0 for p in points))
        self.assertTrue(any(p.E > 10 for p in points))
        self.assertTrue(any(g.distance(p, Point(5,5,0)) < 1e-6 for p in points))
        self.assertTrue(lines)

    def test_fully_external_floor_and_far_coordinates_do_not_expand_grid(self):
        region = g.Region(loop([(780000,-9800000),(780010,-9800000),
                                (780010,-9799990),(780000,-9799990)]), [])
        loops, points, lines = self.surface().constraints(region, allow_outside=True)
        self.assertEqual(4,len(points))
        self.assertEqual([],lines)
        self.assertEqual(100,abs(g.area(loops[0])))
        self.assertTrue(all(p.Z == 10 for p in points))

    def test_external_reference_uses_nearest_border_not_unbounded_slope(self):
        a,b,c = Point(0,0,10),Point(10,0,20),Point(0,10,10)
        surface = g.Surface([(a,b,c)])
        self.assertAlmostEqual(15,surface.height(Point(5,-30,0), allow_outside=True))
        self.assertAlmostEqual(20,surface.height(Point(1000000,0,0), allow_outside=True))
        self.assertRaises(ValueError,surface.height,Point(5,-30,0))

    def test_cad_design_surface_preserves_elevations_and_concave_outline(self):
        outer = [Point(x,y,10+x*0.1+y*0.2) for x,y in [(0,0),(4,0),(4,1),(1,1),(1,4),(0,4)]]
        surface = g.contour_surface(g.Region(outer,[]))
        self.assertAlmostEqual(10.15,surface.height(Point(0.5,0.5,0)))
        for p in outer:
            self.assertAlmostEqual(p.Z,surface.height(p))
        self.assertRaises(ValueError,surface.height,Point(3,3,0))

    def test_cad_hole_vertices_contribute_their_design_z(self):
        outer = [Point(p.E,p.N,10) for p in self.square]
        hole = loop([(4,4),(6,4),(6,6),(4,6)],11)
        surface = g.contour_surface(g.Region(outer,[hole]))
        for p in hole:
            self.assertAlmostEqual(11,surface.height(p))


if __name__ == '__main__':
    unittest.main()
