# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import codecs
import json
import math
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import topobim_core as core


class SurveyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='topobim-test-')

    def tearDown(self):
        shutil.rmtree(self.directory)

    def source(self, text, encoding='utf-8'):
        path = os.path.join(self.directory, 'survey.csv')
        with codecs.open(path, 'w', encoding) as stream:
            stream.write(text)
        return path

    def sample(self, name):
        return os.path.join(ROOT, 'bruto_para_coverter', 'samples', name)

    def triangle(self):
        return [core.Point(0, 0, 1), core.Point(10, 0, 2), core.Point(0, 10, 3)]

    def test_terrain_fixture(self):
        result = core.read_points(self.sample('terreno_exemplo_ENZ.csv'))
        self.assertEqual([], result.errors)
        analysis = core.analyze(result.points)
        values = core.summary(analysis)
        self.assertEqual(54, values['count'])
        self.assertEqual(0, values['duplicates'])
        self.assertEqual((50, 80), (values['width'], values['height']))
        self.assertEqual((12, 14.773), (values['min_z'], values['max_z']))
        self.assertEqual(4, len(core.hull(analysis.points)))

    def test_error_fixture_keeps_first_elevation(self):
        result = core.read_points(self.sample('erros_exemplo.csv'))
        self.assertEqual(1, len(result.errors))
        self.assertTrue(result.errors[0].startswith('Linha 7:'))
        analysis = core.analyze(result.points)
        self.assertEqual(4, len(analysis.points))
        self.assertEqual(1, analysis.points[0].Z)
        self.assertEqual(1, len(analysis.conflicts))
        self.assertEqual(0, analysis.duplicates)

    def test_delimiters_and_units(self):
        for separator in (';', ',', '\t'):
            path = self.source(separator.join(('1', '2', '3')))
            for factor in (1, 0.01, 0.001, 0.3048):
                result = core.read_points(path, separator, header=False, factor=factor)
                self.assertEqual([core.Point(factor, 2 * factor, 3 * factor)], result.points)

    def test_decimal_comma_quotes_and_exponents(self):
        path = self.source('"1,25";"2,5";3e1\n')
        self.assertEqual([core.Point(1.25, 2.5, 30)], core.read_points(path, header=False).points)
        self.assertEqual(['a"b;c', '2'], core.split_line('"a""b;c";2', ';'))
        self.assertRaises(ValueError, core.split_line, '"1;2;3', ';')

    def test_bom_header_and_column_detection(self):
        path = self.source('\nPONTO,X_LESTE,Y_NORTE,ELEVAÇÃO\na,10,20,30\n', 'utf-8-sig')
        self.assertEqual((',', [1, 2, 3]), core.detect_columns(path))
        result = core.read_points(path, ',', (1, 2, 3))
        self.assertEqual([core.Point(10, 20, 30)], result.points)
        self.assertIsNone(core.detect_columns(self.source('1;2;3')))

    def test_reject_ambiguous_and_nonfinite_numbers(self):
        for text in ('1,234.5', '1.234,5', 'nan', 'NaN', 'Infinity', '1e999', '1_000', '1 000', '', '--1'):
            self.assertRaises(ValueError, core.number, text)
        self.assertEqual(-0.5, core.number(' -.5 '))
        self.assertEqual(1000, core.number('1e3'))

    def test_scaled_overflow_is_error(self):
        result = core.read_points(self.source('1e308;0;0'), header=False, factor=100)
        self.assertEqual([], result.points)
        self.assertEqual(1, len(result.errors))

    def test_invalid_columns(self):
        path = self.source('1;2;3')
        for columns in ((0, 0, 1), (-1, 0, 1), (0, 1)):
            self.assertRaises(ValueError, core.read_points, path, ';', columns, False)
        result = core.read_points(path, ';', (1, 2, 3), False)
        self.assertIn('Colunas insuficientes', result.errors[0])

    def test_line_numbers_blank_lines_and_unclosed_quotes(self):
        result = core.read_points(self.source('\nE;N;Z\n\nabc;0;0\n"1;2;3\n'))
        self.assertTrue(result.errors[0].startswith('Linha 4:'))
        self.assertTrue(result.errors[1].startswith('Linha 5:'))

    def test_grid_ties_match_dotnet(self):
        for value, expected in ((0.0005, 0), (0.0015, 0.002), (0.0025, 0.002),
                                (-0.0005, 0), (-0.0015, -0.002), (-0.0025, -0.002),
                                (780000.0005, 780000.0), (1e16, 1e16)):
            self.assertEqual(expected, core.grid_key(value))

    def test_grid_is_not_a_proximity_radius(self):
        points = [core.Point(0.00049, 0, 0), core.Point(0.00051, 0, 0)]
        self.assertEqual(2, len(core.deduplicate(points).points))

    def test_duplicates_conflicts_and_order(self):
        points = self.triangle()
        points += [core.Point(0.0004, 0, 1.001), core.Point(0, 0, 9)]
        analysis = core.analyze(points)
        self.assertEqual(self.triangle(), analysis.points)
        self.assertEqual(1, analysis.duplicates)
        self.assertEqual(1, len(analysis.conflicts))

    def test_degenerate_and_nonfinite_geometry(self):
        for points in ([], self.triangle()[:2], [core.Point(i, i, 0) for i in range(3)],
                       [core.Point(float('inf'), 0, 0)]):
            self.assertRaises(ValueError, core.analyze, points)

    def test_diagnostics_survive_insufficient_geometry(self):
        result = core.read_points(self.source('E;N;Z\n0;0;1\n0;0;2\nbad;0;0'))
        analysis = core.deduplicate(result.points)
        self.assertRaises(ValueError, core.validate_analysis, analysis)
        rows = core.occurrence_rows(result.errors, analysis.conflicts, 'Pontos insuficientes')
        self.assertEqual(3, len(rows))

    def test_input_limit_includes_invalid_rows(self):
        path = self.source('0;0;0\n' * core.MAX_INPUT)
        self.assertEqual(core.MAX_INPUT, len(core.read_points(path, header=False).points))
        path = self.source('bad;0;0\n' * (core.MAX_INPUT + 1))
        self.assertRaises(ValueError, core.read_points, path, header=False)

    def test_creation_limit(self):
        points = [core.Point(i % 200, i // 200, 0) for i in range(core.MAX_CREATE)]
        self.assertEqual(core.MAX_CREATE, len(core.analyze(points).points))
        points.append(core.Point(-1, -1, 0))
        self.assertRaises(ValueError, core.analyze, points)

    def test_report_roundtrip_and_csv_quoting(self):
        path = os.path.join(self.directory, 'report.json')
        report = dict(Datum='SIRGAS 2000', Location='Localização', Errors=[])
        core.write_report(path, report)
        with codecs.open(path, 'r', 'utf-8') as stream:
            self.assertEqual(report, json.load(stream))
        path = os.path.join(self.directory, 'issues.csv')
        core.write_occurrences(path, [('Aviso', 'cota "1"; E=2', 'Revisão')])
        with open(path, 'rb') as stream:
            raw = stream.read()
        self.assertTrue(raw.startswith(codecs.BOM_UTF8))
        text = raw.decode('utf-8-sig')
        fields = core.split_line(text.splitlines()[1], ';')
        self.assertEqual(['1', 'Aviso', 'cota "1"; E=2', 'Revisão'], fields)

    def test_triangle_height_uses_survey_cota_at_the_requested_xy(self):
        a, b, c = core.Point(780000, 9840000, 10), core.Point(780020, 9840000, 20), core.Point(780000, 9840020, 30)
        self.assertAlmostEqual(17.5, core.triangle_height(780005, 9840005, a, b, c))
        self.assertEqual(10, core.triangle_height(a.E, a.N, a, b, c))
        self.assertEqual(25, core.triangle_height(780010, 9840010, a, b, c))

    def test_triangle_height_does_not_extrapolate_outside_the_surface(self):
        points = [core.Point(0, 0, 10), core.Point(10, 0, 20), core.Point(0, 10, 30)]
        self.assertIsNone(core.triangle_height(10, 10, *points))
        self.assertIsNone(core.triangle_height(-1, 0, *points))

    def test_triangle_height_ignores_vertical_faces(self):
        points = [core.Point(0, 0, 0), core.Point(0, 0, 10), core.Point(0, 10, 10)]
        self.assertIsNone(core.triangle_height(0, 0, *points))


if __name__ == '__main__':
    unittest.main()
