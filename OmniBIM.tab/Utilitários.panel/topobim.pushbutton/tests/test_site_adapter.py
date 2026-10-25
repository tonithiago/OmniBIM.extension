# -*- coding: utf-8 -*-
"""API adapter contract checks with a small fake document, not a Revit test."""
from __future__ import division, unicode_literals
import math
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Record(object):
    def __init__(self, **values):
        self.__dict__.update(values)


class XYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def Subtract(self, other):
        return XYZ(self.X - other.X, self.Y - other.Y, self.Z - other.Z)

    def GetLength(self):
        return math.sqrt(self.X**2 + self.Y**2 + self.Z**2)

    def DistanceTo(self, other):
        return self.Subtract(other).GetLength()


XYZ.Zero, XYZ.BasisX, XYZ.BasisY, XYZ.BasisZ = XYZ(0, 0, 0), XYZ(1, 0, 0), XYZ(0, 1, 0), XYZ(0, 0, 1)


class Transform(object):
    def __init__(self):
        self.Origin = XYZ.Zero
        self.BasisX, self.BasisY, self.BasisZ = XYZ.BasisX, XYZ.BasisY, XYZ.BasisZ

    def OfPoint(self, p):
        return XYZ(self.Origin.X + p.X*self.BasisX.X + p.Y*self.BasisY.X + p.Z*self.BasisZ.X,
                   self.Origin.Y + p.X*self.BasisX.Y + p.Y*self.BasisY.Y + p.Z*self.BasisZ.Y,
                   self.Origin.Z + p.X*self.BasisX.Z + p.Y*self.BasisY.Z + p.Z*self.BasisZ.Z)


class TransformFactory(object):
    @property
    def Identity(self):
        return Transform()


class Mesh(object):
    def __init__(self, triangles):
        self.triangles = triangles
        self.NumTriangles = len(triangles)

    def get_Triangle(self, index):
        return Record(get_Vertex=lambda i: self.triangles[index][i])

    def Dispose(self):
        pass


class Solid(object):
    def __init__(self, triangles):
        self.Faces = [Record(Triangulate=lambda: Mesh(triangles))]


class Geometry(list):
    def Dispose(self):
        pass


class Position(object):
    def __init__(self, east, north, z, angle):
        self.EastWest, self.NorthSouth, self.Elevation, self.Angle = east, north, z, angle

    def Dispose(self):
        pass


class Location(object):
    def __init__(self, name, element_id, position):
        self.Name, self.Id, self.position = name, element_id, position

    def GetProjectPosition(self, point):
        p = self.position
        return Position(p.EastWest + math.cos(p.Angle)*point.X - math.sin(p.Angle)*point.Y,
                        p.NorthSouth + math.sin(p.Angle)*point.X + math.cos(p.Angle)*point.Y,
                        p.Elevation + point.Z, p.Angle)

    def SetProjectPosition(self, point, position):
        self.position = position

    def GetSiteLocation(self):
        return Record(Id=99)


class Base(object):
    def __init__(self, doc, element_id, shared, position):
        self.doc, self.Id, self.IsShared, self.Position = doc, element_id, shared, position
        self.Pinned = True
        self.Clipped = shared

    @property
    def SharedPosition(self):
        p = self.doc.ActiveProjectLocation.GetProjectPosition(self.Position)
        return XYZ(p.EastWest, p.NorthSouth, p.Elevation)


class Document(object):
    def __init__(self):
        self.default = Location('Terreno padrão', 1, Position(0, 0, 0, 0))
        self.legacy = Location('TOPOBIM 20261023', 2, Position(780025/0.3048, 9840040/0.3048, 25/0.3048, 0.37))
        self.other = Location('Outra localização', 3, Position(1, 2, 3, 0))
        self.ProjectLocations = [self.default, self.legacy, self.other]
        self.ActiveProjectLocation = self.legacy
        self.SiteLocation = Record(Latitude=0.0, Longitude=0.0, TimeZone=-3.0)
        self.project = Base(self, 10, False, XYZ(100, 200, 30))
        self.survey = Base(self, 11, True, XYZ(-200, 300, 40))
        self.moves = []
        self.extra_deletion = False

    def Regenerate(self):
        pass

    def Delete(self, element_id):
        self.ProjectLocations = [p for p in self.ProjectLocations if p.Id != element_id]
        return [element_id, 500] if self.extra_deletion else [element_id]


def move_element(doc, element_id, delta):
    base = doc.project if element_id == doc.project.Id else doc.survey
    assert not base.Pinned
    assert not base.IsShared or not base.Clipped
    doc.moves.append(element_id)
    base.Position = XYZ(base.Position.X + delta.X, base.Position.Y + delta.Y, base.Position.Z + delta.Z)


def load_adapter():
    names = ('System', 'System.Collections', 'System.Collections.Generic', 'pyrevit', 'topobim_revit')
    old = {name: sys.modules.get(name) for name in names}
    try:
        for name in names[:-1]:
            sys.modules[name] = types.ModuleType(name)
        sys.modules['System'].DateTimeOffset = object
        sys.modules['System.Collections.Generic'].List = list
        sys.modules['pyrevit'].DB = Record(
            XYZ=XYZ, Transform=TransformFactory(), ProjectPosition=Position,
            GeometryInstance=type('GeometryInstance', (), {}), Mesh=Mesh, Solid=Solid,
            Options=lambda: Record(Dispose=lambda: None), ViewDetailLevel=Record(Fine='fine'),
            UnitTypeId=Record(Meters='m'),
            UnitUtils=Record(ConvertToInternalUnits=lambda x, unit: x/0.3048,
                             ConvertFromInternalUnits=lambda x, unit: x*0.3048),
            BasePoint=Record(GetProjectBasePoint=lambda doc: doc.project, GetSurveyPoint=lambda doc: doc.survey),
            ElementTransformUtils=Record(MoveElement=move_element))
        sys.modules.pop('topobim_revit', None)
        return __import__('topobim_revit')
    finally:
        for name, module in old.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class SiteAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_adapter()

    def setUp(self):
        self.doc = Document()
        self.settings = dict(NewLocation=False, East=0, North=0, Elevation=0,
                             Datum='SIRGAS 2000', Zone=22, Hemisphere='Sul')

    def test_default_reuses_id_and_preserves_active_transform(self):
        before = self.doc.legacy.GetProjectPosition(XYZ(1, 2, 3))
        self.service.use_default_location(self.doc, self.settings)
        self.assertEqual(1, self.doc.ActiveProjectLocation.Id)
        self.assertEqual('Terreno Padrão', self.doc.ActiveProjectLocation.Name)
        after = self.doc.ActiveProjectLocation.GetProjectPosition(XYZ(1, 2, 3))
        self.assertEqual(before.__dict__, after.__dict__)
        self.assertEqual([1, 3], [p.Id for p in self.doc.ProjectLocations])

    def test_explicit_origin_updates_default_without_duplicate(self):
        self.settings.update(NewLocation=True, East=700000, North=9800000, Elevation=50)
        self.service.use_default_location(self.doc, self.settings)
        p = self.doc.ActiveProjectLocation.GetProjectPosition(XYZ.Zero)
        self.assertAlmostEqual(700000, self.service.metres(p.EastWest))
        self.assertAlmostEqual(9800000, self.service.metres(p.NorthSouth))
        self.assertAlmostEqual(50, self.service.metres(p.Elevation))
        self.assertEqual(0, p.Angle)
        self.service.use_default_location(self.doc, self.settings)
        self.assertEqual(2, len(self.doc.ProjectLocations))

    def test_custom_sites_are_not_deleted(self):
        self.doc.legacy.Name = 'Coordenacao externa'
        self.service.use_default_location(self.doc, self.settings)
        self.assertEqual(3, len(self.doc.ProjectLocations))

    def test_inactive_legacy_sites_are_removed_too(self):
        older = Location('TOPOBIM 20261023 161504 317000', 4, Position(10, 20, 30, 0))
        self.doc.ProjectLocations.insert(1, older)
        self.service.use_default_location(self.doc, self.settings)
        self.assertEqual([1, 3], [p.Id for p in self.doc.ProjectLocations])
        self.assertEqual('Terreno Padrão', self.doc.ActiveProjectLocation.Name)

    def test_repeated_creation_replaces_coordinates_in_one_canonical_site(self):
        self.settings.update(NewLocation=True, East=700000, North=9800000, Elevation=50)
        self.service.use_default_location(self.doc, self.settings)
        self.settings.update(East=710000, North=9810000, Elevation=60)
        self.service.use_default_location(self.doc, self.settings)
        self.assertEqual(1, self.doc.ActiveProjectLocation.Id)
        self.assertEqual(['Terreno Padrão', 'Outra localização'], [p.Name for p in self.doc.ProjectLocations])
        p = self.doc.ActiveProjectLocation.GetProjectPosition(XYZ.Zero)
        self.assertAlmostEqual(710000, self.service.metres(p.EastWest))
        self.assertAlmostEqual(9810000, self.service.metres(p.NorthSouth))
        self.assertAlmostEqual(60, self.service.metres(p.Elevation))

    def test_uppercase_canonical_site_is_reused_when_already_present(self):
        self.doc.default.Name = 'TERRENO PADRÃO'
        self.service.use_default_location(self.doc, self.settings)
        self.assertEqual(1, self.doc.ActiveProjectLocation.Id)
        self.assertEqual(['Terreno Padrão', 'Outra localização'], [p.Name for p in self.doc.ProjectLocations])

    def test_unexpected_cascade_raises_for_transaction_rollback(self):
        self.doc.extra_deletion = True
        self.assertRaises(ValueError, self.service.use_default_location, self.doc, self.settings)

    def test_base_points_coincide_and_restore_pin_and_clip(self):
        old_position = self.doc.ActiveProjectLocation.position.__dict__.copy()
        report = self.service.align_base_points(self.doc)
        self.assertEqual([10, 11], self.doc.moves)
        for base in (self.doc.project, self.doc.survey):
            self.assertEqual(0, base.Position.GetLength())
            self.assertTrue(base.Pinned)
        self.assertTrue(self.doc.survey.Clipped)
        self.assertEqual(old_position, self.doc.ActiveProjectLocation.position.__dict__)
        self.assertEqual(0, self.doc.project.SharedPosition.DistanceTo(self.doc.survey.SharedPosition))
        self.assertAlmostEqual(25, report['SharedPositionMetres'][2])

    def test_already_aligned_markers_are_not_moved(self):
        self.doc.project.Position = self.doc.survey.Position = XYZ.Zero
        self.service.align_base_points(self.doc)
        self.assertEqual([], self.doc.moves)

    def test_fresh_verification_detects_a_marker_displaced_after_alignment(self):
        self.service.align_base_points(self.doc)
        self.doc.survey.Position = XYZ(0, 0, 5)
        self.assertRaises(ValueError, self.service.verify_base_points, self.doc)

    def test_final_report_contains_measured_separation(self):
        self.service.align_base_points(self.doc)
        report = self.service.verify_base_points(self.doc)
        self.assertEqual(0.0, report['SeparationMetres'])
        self.assertEqual(report['InternalPosition'], report['SurveyInternalPosition'])

    def test_both_markers_can_use_a_nonzero_survey_elevation(self):
        target = XYZ(0, 0, 13.25 / 0.3048)
        old_origin = self.doc.ActiveProjectLocation.position.__dict__.copy()
        report = self.service.align_base_points(self.doc, target)
        self.assertAlmostEqual(13.25, report['InternalPosition'][2])
        self.assertAlmostEqual(38.25, report['SharedPositionMetres'][2])
        self.assertEqual(0, self.doc.project.Position.DistanceTo(self.doc.survey.Position))
        self.assertEqual(old_origin, self.doc.ActiveProjectLocation.position.__dict__)
        self.service.verify_base_points(self.doc, target_position=target)

    def test_base_target_uses_the_upper_surface_not_the_bottom_of_the_solid(self):
        top = [XYZ(-10, -10, 10 / 0.3048), XYZ(10, -10, 20 / 0.3048), XYZ(0, 10, 30 / 0.3048)]
        bottom = [XYZ(p.X, p.Y, p.Z - 5 / 0.3048) for p in top]
        topo = Record(get_Geometry=lambda options: Geometry([Solid([bottom, top])]))
        target = self.service.surface_base_point(topo)
        self.assertAlmostEqual(22.5, self.service.metres(target.Z))
        self.assertEqual((0, 0), (target.X, target.Y))

    def test_origin_outside_the_terrain_does_not_get_an_invented_elevation(self):
        triangle = [XYZ(10, 10, 20), XYZ(20, 10, 20), XYZ(10, 20, 20)]
        topo = Record(get_Geometry=lambda options: Geometry([Solid([triangle])]))
        self.assertRaises(ValueError, self.service.surface_base_point, topo)

    def test_geography_uses_actual_origin_when_preserving_coordinates(self):
        values = self.service.geographic_settings(self.doc, self.settings)
        self.assertAlmostEqual(780025, values['East'])
        self.assertAlmostEqual(9840040, values['North'])
        self.assertLess(values['Latitude'], 0)
        self.assertLess(values['Longitude'], 0)

    def test_site_angles_are_written_in_radians(self):
        values = dict(Latitude=-1.451637, Longitude=-48.497723)
        self.service.set_site_geography(self.doc, values)
        self.assertAlmostEqual(math.radians(-1.451637), self.doc.SiteLocation.Latitude)
        self.assertAlmostEqual(math.radians(-48.497723), self.doc.SiteLocation.Longitude)
        self.assertEqual(-3.0, values['TimeZoneHours'])

    def test_manual_geography_does_not_project_local_coordinates(self):
        self.settings.update(NewLocation=True, East=0, North=0, GeographicMode='manual',
                             Latitude=-1.451637, Longitude=-48.497723)
        values = self.service.geographic_settings(self.doc, self.settings)
        self.assertEqual(-1.451637, values['Latitude'])
        self.assertEqual(-48.497723, values['Longitude'])


if __name__ == '__main__':
    unittest.main()
