# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import topobim_geo as geo


class GeographicTests(unittest.TestCase):
    def test_equator_and_all_zone_meridians(self):
        for zone in range(1, 61):
            for datum in ('SIRGAS 2000', 'WGS 84'):
                self.assertEqual((0.0, zone * 6 - 183), geo.utm_to_latlon(500000, 0, zone, 'Norte', datum))
                self.assertEqual((0.0, zone * 6 - 183), geo.utm_to_latlon(500000, 10000000, zone, 'Sul', datum))

    def test_proj_northern_reference(self):
        # Rounded to 1 cm in https://proj.org/en/stable/operations/projections/utm.html
        lat, lon = geo.utm_to_latlon(687071.44, 6210141.33, 32, 'Norte', 'WGS84')
        self.assertAlmostEqual(56, lat, places=7)
        self.assertAlmostEqual(12, lon, places=7)

    def test_proj_southern_reference(self):
        lat, lon = geo.utm_to_latlon(740526.32, 5123750.87, 59, 'Sul', 'WGS84')
        self.assertAlmostEqual(-44, lat, places=7)
        self.assertAlmostEqual(174, lon, places=7)

    def test_sirgas_belem_reference(self):
        # Independent PROJ/GRS80 forward projection of this geographic location.
        lat, lon = geo.utm_to_latlon(778441.0266824275, 9839396.046282109, 22, 'Sul', 'SIRGAS 2000')
        self.assertAlmostEqual(-1.451637, lat, places=10)
        self.assertAlmostEqual(-48.497723, lon, places=10)

    def test_invalid_utm_is_not_interpreted_as_local_coordinates(self):
        for east, north in ((0, 0), (100, 100), (1e7, 9840000), (780000, -1),
                            (float('nan'), 9840000), (780000, float('inf'))):
            self.assertRaises(ValueError, geo.utm_to_latlon, east, north, 22, 'Sul', 'SIRGAS 2000')

    def test_crs_validation(self):
        for zone in (0, 61, 22.5):
            self.assertRaises(ValueError, geo.utm_to_latlon, 780025, 9840040, zone, 'Sul', 'SIRGAS 2000')
        self.assertRaises(ValueError, geo.utm_to_latlon, 780025, 9840040, 22, 'Sul', 'SAD69')
        self.assertRaises(ValueError, geo.utm_to_latlon, 780025, 9840040, 22, 'S', 'WGS84')
        self.assertRaises(ValueError, geo.utm_to_latlon, 500000, 0, 22, 'Sul', 'WGS84')

    def test_manual_coordinates_validate_degrees_and_signs(self):
        self.assertEqual((-1.451637, -48.497723), geo.validate_latlon(-1.451637, -48.497723))
        for lat, lon in ((91, 0), (-91, 0), (0, 181), (0, -181), (float('nan'), 0), (0, float('inf'))):
            self.assertRaises(ValueError, geo.validate_latlon, lat, lon)


if __name__ == '__main__':
    unittest.main()
