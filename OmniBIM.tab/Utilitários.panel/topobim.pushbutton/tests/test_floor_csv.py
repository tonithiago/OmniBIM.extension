# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import codecs
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import topobim_floor_csv as csv_floors
import topobim_floor_geometry as geom
from test_floor_adapter import floors, Record, Location, Position


class CsvFloorTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix='.csv')
        os.close(handle)

    def tearDown(self):
        os.remove(self.path)

    def write(self, text, encoding='utf-8'):
        with codecs.open(self.path, 'w', encoding) as stream:
            stream.write(text)
        return self.path

    def test_sample_layers_hole_and_elevations(self):
        path = os.path.join(ROOT, 'samples', 'pisos_layers.csv')
        self.assertEqual((3, 4), csv_floors.detect_groups(path, ';', True))
        areas, issues = csv_floors.read_areas(path, contour_column=4)
        self.assertFalse(issues)
        self.assertEqual(['CALCADA', 'PAVIMENTACAO'], sorted(areas))
        self.assertEqual(375, geom.region_area(areas['PAVIMENTACAO'][0]))
        self.assertEqual(1, len(areas['PAVIMENTACAO'][0].holes))
        self.assertTrue(areas.elevated_regions['PAVIMENTACAO'][0])

    def test_headerless_reordered_columns_units_and_quoted_layer(self):
        path = self.write('"Calçada, A",0,0,0\n"Calçada, A",0,1000,0\n"Calçada, A",1000,0,0\n', 'cp1252')
        self.assertEqual((None, None), csv_floors.detect_groups(path, ',', False))
        areas, _ = csv_floors.read_areas(path, ',', (2, 1, 3), False, 0.001, 0)
        self.assertAlmostEqual(0.5, geom.region_area(areas['Calçada, A'][0]))
        self.assertFalse(areas.elevated_regions['Calçada, A'][0])

    def test_concave_contour_preserved_with_explicit_closure(self):
        path = self.write('E;N;Z;Layer\n0;0;2;A\n4;0;2;A\n4;1;2;A\n1;1;2;A\n1;4;2;A\n0;4;2;A\n0;0;2;A\n')
        areas, _ = csv_floors.read_areas(path)
        self.assertEqual(7, geom.region_area(areas['A'][0]))
        self.assertEqual(6, len(areas['A'][0].outer))

    def test_bad_vertex_cannot_be_dropped_to_make_floor(self):
        for bad in ('bad;1;0;A', '1;1;0;', '1;1;0', '1e999;1;0;A', '"1;1;0;A'):
            path = self.write('E;N;Z;Layer\n0;0;0;A\n2;0;0;A\n'+bad+'\n0;2;0;A\n')
            with self.assertRaises(ValueError) as caught:
                csv_floors.read_areas(path)
            self.assertIn('Linha 4', str(caught.exception))

    def test_invalid_layer_excluded_in_full(self):
        path = self.write('E;N;Z;Layer;Contorno\n0;0;0;A;1\n2;0;0;A;1\n0;2;0;A;1\n5;5;0;A;2\n0;0;0;B;1\n2;0;0;B;1\n0;2;0;B;1\n')
        areas, issues = csv_floors.read_areas(path, contour_column=4)
        self.assertEqual(['B'], list(areas))
        self.assertIn('A: Contorno 2:', issues[0])

    def test_crossing_overlapping_and_insufficient_vertices_rejected(self):
        for vertices in ('0;0\n3;3\n0;3\n3;0', '0;0\n1;0', '0;0\n1;1\n2;2'):
            path = self.write('E;N;Z;Layer\n' + '\n'.join(v+';0;A' for v in vertices.split('\n')))
            self.assertRaises(ValueError, csv_floors.read_areas, path)
        path = os.path.join(ROOT, 'samples', 'pisos_layers.csv')
        self.assertRaises(ValueError, csv_floors.read_areas, path, layer_column=2)

    def test_prepare_rereads_csv_without_cad_and_rejects_changes(self):
        data = 'E;N;Z;Layer\n0;0;0;A\n2;0;0;A\n0;2;0;A\n'
        path = self.write(data)
        areas, _ = csv_floors.read_areas(path)
        settings = dict(Source='CSV', Csv=dict(path=path), Original=True,
                        Layers=[('A', 10)], LevelId=20, Signature=floors.signature(areas, ['A']))
        prepared = floors.prepare(None, settings)
        self.assertEqual(['A'], list(prepared['Areas']))
        self.assertNotIn('Areas', settings)
        self.assertNotIn('InternalAreas', prepared)
        self.write(data.replace('2;0;0', '3;0;0'))
        self.assertRaises(ValueError, floors.prepare, None, settings)

    def test_create_csv_reports_source_and_uses_contour_elevation(self):
        path = self.write('E;N;Z;Layer\n0;0;12;A\n2;0;12;A\n0;2;12;A\n')
        areas, _ = csv_floors.read_areas(path)
        settings = dict(Source='CSV', Csv=dict(path=path), Original=True,
                        Layers=[('A', 10)], LevelId=20, Signature=floors.signature(areas, ['A']))
        prepared = floors.prepare(None, settings)
        doc = Record(ActiveProjectLocation=Location('Atual',1,Position(0,0,0,0)))
        original = floors.surface, floors.create_one, floors.excavate
        old_parameters = getattr(floors.DB, 'BuiltInParameter', None)
        captured = []
        try:
            floors.surface = lambda *args: None
            def create_one(doc, design, region, type_id, level_id):
                captured.append((design, region))
                return Record(Id=50, get_Parameter=lambda p: None), dict(ElementId='50')
            floors.create_one = create_one
            floors.excavate = lambda *args: False
            floors.DB.BuiltInParameter = Record(ALL_MODEL_INSTANCE_COMMENTS='comments')
            report = floors.create(doc, None, prepared)[0]
            self.assertEqual('CSV closed contours', report['Source'])
            self.assertEqual('CSV contour Z', report['ElevationSource'])
            self.assertEqual(path, report['CsvPath'])
            self.assertNotIn('CadId', report)
            self.assertAlmostEqual(12, captured[0][1].outer[0].Z)
            self.assertIsNotNone(captured[0][0])
        finally:
            floors.surface, floors.create_one, floors.excavate = original
            if old_parameters is None:
                del floors.DB.BuiltInParameter
            else:
                floors.DB.BuiltInParameter = old_parameters


if __name__ == '__main__':
    unittest.main()
