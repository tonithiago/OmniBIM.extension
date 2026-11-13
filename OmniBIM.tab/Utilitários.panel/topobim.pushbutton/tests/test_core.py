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

    def test_survey_encodings_preserve_accents_and_column_detection(self):
        for encoding in ('utf-8', 'utf-8-sig', 'cp1252'):
            path = self.source('\nPONTO;ESTE;NORTE;ELEVAÇÃO\n'
                               'Estação;10;20;30\n'
                               'Marco;inválido;20;30\n', encoding)
            self.assertEqual((';', [1, 2, 3]), core.detect_columns(path))
            result = core.read_points(path, columns=(1, 2, 3))
            self.assertEqual([core.Point(10, 20, 30)], result.points)
            self.assertEqual(['Linha 4: Número inválido: inválido'], result.errors)

    def test_detect_format_header_and_existing_semicolon_decimals(self):
        for separator in (';', ',', '\t'):
            path = self.source(separator.join(('PONTO', 'Z', 'N', 'E')) + '\n' +
                               separator.join(('A', '20.5', '9845213.791', '784842.009')))
            detected = core.detect_format(path)
            self.assertEqual((separator, [3, 2, 1], True), detected)
            result = core.read_points(path, *detected)
            self.assertEqual([], result.errors)
            self.assertEqual([core.Point(784842.009, 9845213.791, 20.5)], result.points)
        path = self.source('1,25;2,5;3,75\n4,25;5,5;6,75\n')
        detected = core.detect_format(path)
        self.assertEqual((';', [0, 1, 2], False), detected)
        self.assertEqual([core.Point(1.25, 2.5, 3.75), core.Point(4.25, 5.5, 6.75)],
                         core.read_points(path, *detected).points)

    def test_detect_headerless_sector_export_keeps_first_point(self):
        for separator, decimal in ((',', '.'), (';', '.'), (';', ','), ('\t', '.')):
            rows = [('JS4', '20.272', '', '9845213.7910', '784842.0090', ''),
                    ('V1', '20.256', '', '9845226.7744', '784851.2066', ''),
                    ('1', '19.882', 'PT', '9845250.3357', '784841.6984', '')]
            path = self.source('\n'.join(separator.join(v.replace('.', decimal) for v in row)
                                         for row in rows))
            detected = core.detect_format(path)
            self.assertEqual((separator, [4, 3, 1], False), detected)
            result = core.read_points(path, *detected)
            self.assertEqual([], result.errors)
            self.assertEqual(3, len(result.points))
            self.assertEqual(core.Point(784842.009, 9845213.791, 20.272), result.points[0])
            self.assertEqual(core.Point(784841.6984, 9845250.3357, 19.882), result.points[-1])

    def test_detect_headerless_screenshot_export(self):
        path = self.source('JS1,9852066.2330,791133.7060,17.698,,\n'
                           'B1,9852060.9818,791129.5874,16.399,,\n'
                           '1,9852096.1382,791146.7796,17.947,PN,\n', 'utf-8-sig')
        detected = core.detect_format(path)
        self.assertEqual((',', [2, 1, 3], False), detected)
        result = core.read_points(path, *detected)
        self.assertEqual([], result.errors)
        self.assertEqual(3, len(result.points))
        self.assertEqual(core.Point(791133.706, 9852066.233, 17.698), result.points[0])

    def test_format_unknown_layout_requires_manual_columns(self):
        for content in ('ID,A,B,C\n1,2,3,4',
                        '1,20,30,40,',
                        '1,20,PT,9845213,784842,\n2,20,PT,100,200,'):
            self.assertEqual((',', None, None), core.detect_format(self.source(content)))
        for content in ('', '\n\n', '1.2.3', '"1,2,3', '1,2,3\n4,5'):
            self.assertIsNone(core.detect_format(self.source(content)))

    def test_detect_format_quotes_encoding_and_trailing_fields(self):
        path = self.source('"Estação, A";"20,272";"Descrição; marco";"9845213,791";"784842,009";\n',
                           'cp1252')
        detected = core.detect_format(path)
        self.assertEqual((';', [4, 3, 1], False), detected)
        self.assertEqual([core.Point(784842.009, 9845213.791, 20.272)],
                         core.read_points(path, *detected).points)

    def test_windows1252_accent_after_first_chunk(self):
        path = self.source('1;2;3;Marco\n' * 7000 + '4;5;6;Estação “A”\n', 'cp1252')
        result = core.read_points(path, header=False)
        self.assertEqual([], result.errors)
        self.assertEqual(7001, len(result.points))
        self.assertEqual(core.Point(4, 5, 6), result.points[-1])

    def test_utf8_multibyte_character_at_chunk_boundary(self):
        prefix = 'E;N;Z\n1;2;'
        path = self.source(prefix + ' ' * (65535 - len(prefix)) + 'ação\n')
        result = core.read_points(path)
        self.assertEqual([], result.points)
        self.assertEqual(['Linha 2: Número inválido: ação'], result.errors)

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
