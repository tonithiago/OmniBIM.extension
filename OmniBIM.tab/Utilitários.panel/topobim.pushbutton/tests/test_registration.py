# -*- coding: utf-8 -*-
from __future__ import division, unicode_literals
import math
import unittest
from test_core import core


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.local = [core.Point(x,y,12+i) for i,(x,y) in enumerate(
            [(0,0),(2,1),(7,2),(8,9),(3,11),(-2,6),(1,3),(4,5)])]

    def moved(self, points, angle=0, e=778468.522117, n=9839410.822919):
        c,s = math.cos(angle),math.sin(angle)
        return [core.Point(c*p.E-s*p.N+e,s*p.E+c*p.N+n,p.Z) for p in points]

    def test_local_dwg_is_registered_to_utm_csv_without_model_placement(self):
        survey = self.moved(self.local)
        r = core.register_survey(survey, {'CurvasTG':self.local})
        self.assertAlmostEqual(778468.522117,r['East'],places=6)
        self.assertAlmostEqual(9839410.822919,r['North'],places=6)
        self.assertEqual(1,r['Coverage'])

    def test_rotation_is_measured_from_common_vertices(self):
        survey = self.moved(self.local,0.713)
        r = core.register_survey(survey, {'CurvasTG':self.local})
        self.assertAlmostEqual(math.cos(0.713),r['Cos'],places=6)
        self.assertAlmostEqual(math.sin(0.713),r['Sin'],places=6)

    def test_same_bounds_are_insufficient_without_matching_vertices(self):
        wrong = list(self.local)
        wrong[1] = core.Point(2.6,1.7,0)
        self.assertRaises(ValueError,core.register_survey,self.moved(self.local),{'Different':wrong})

    def test_ambiguous_repeated_survey_in_two_layers_is_rejected(self):
        self.assertRaises(ValueError,core.register_survey,self.moved(self.local),
                          {'A':self.local,'B':self.moved(self.local,e=30,n=40)})

    def test_scaled_geometry_is_not_accepted(self):
        scaled = [core.Point(p.E*1.01,p.N*1.01,p.Z) for p in self.local]
        self.assertRaises(ValueError,core.register_survey,self.moved(self.local),{'Wrong units':scaled})


if __name__ == '__main__':
    unittest.main()
