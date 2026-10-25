# -*- coding: utf-8 -*-
"""Survey parsing and analysis. No Revit dependency; Python 2.7 and 3 compatible."""
from __future__ import division, unicode_literals

import codecs
import json
import math
import re
from collections import namedtuple

class Point(namedtuple('SurveyPoint', 'E N Z')):
    """Coordinates are doubles, like the original C# SurveyPoint."""
    __slots__ = ()

    def __new__(cls, east, north, elevation):
        return super(Point, cls).__new__(cls, float(east), float(north), float(elevation))


ReadResult = namedtuple('ReadResult', 'points errors')
Analysis = namedtuple('Analysis', 'points duplicates conflicts')
MAX_INPUT = 100000
MAX_CREATE = 20000
NUMBER_PATTERN = re.compile(r'^[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)(?:[eE][+-]?[0-9]+)?$')
try:
    text_type = unicode
except NameError:
    text_type = str


def finite(value):
    return not (math.isnan(value) or math.isinf(value))


def register_survey(survey, groups, tolerance=0.002):
    """Rigid XY registration, accepted only against measured common vertices.

    A bounding-box translation is merely a candidate, never the acceptance
    criterion. At least 95% of survey vertices (minimum six, non-collinear)
    must coincide with a CAD layer within 2 mm. No scale or Z change is fitted.
    """
    survey = deduplicate(survey).points
    if len(survey) < 6 or len(hull(survey)) < 3:
        raise ValueError('São necessários seis vértices comuns não colineares para relacionar DWG e levantamento.')

    def key(x, y):
        return int(math.floor(x/tolerance)), int(math.floor(y/tolerance))

    def mapped(p, t):
        c,s,e,n = t
        return Point(c*p.E-s*p.N+e,s*p.E+c*p.N+n,p.Z)

    # Score survey coverage, so a small coincidental CAD detail cannot pass.
    def coverage(buckets, t):
        c,s,e,n = t
        inverse = (c,-s,-c*e-s*n,s*e-c*n)
        matched = 0
        for index,p in enumerate(survey):
            q = mapped(p,inverse)
            x,y = key(q.E,q.N)
            if any((v.E-q.E)**2+(v.N-q.N)**2 <= tolerance**2
                   for xx in range(x-1,x+2) for yy in range(y-1,y+2)
                   for v in buckets.get((xx,yy), [])):
                matched += 1
            if index+1-matched > len(survey)*0.05:
                return 0.0
        return matched/len(survey)

    def edges(points):
        return [(a,b,math.hypot(b.E-a.E,b.N-a.N)) for a,b in zip(points,points[1:])
                if math.hypot(b.E-a.E,b.N-a.N) > tolerance*10]

    survey_edges = sorted(edges(survey), key=lambda item:-item[2])[:64]
    accepted = []
    for layer in sorted(groups):
        points = groups[layer]
        if len(points) < 6:
            continue
        buckets = {}
        for p in points:
            buckets.setdefault(key(p.E,p.N), []).append(p)
        e = (min(p.E for p in survey)+max(p.E for p in survey)-min(p.E for p in points)-max(p.E for p in points))/2
        n = (min(p.N for p in survey)+max(p.N for p in survey)-min(p.N for p in points)-max(p.N for p in points))/2
        candidates = [(1.0,0.0,e,n)]
        lengths = {}
        for a,b,length in edges(points):
            lengths.setdefault(int(round(length/tolerance)), []).append((a,b,length))
        for a,b,length in survey_edges:
            k = int(round(length/tolerance))
            for bucket in range(k-1,k+2):
                for u,v,d in lengths.get(bucket,[])[:8]:
                    if abs(length-d) > tolerance:
                        continue
                    for u,v in ((u,v),(v,u)):
                        angle = math.atan2(b.N-a.N,b.E-a.E)-math.atan2(v.N-u.N,v.E-u.E)
                        c,s = math.cos(angle),math.sin(angle)
                        candidates.append((c,s,a.E-c*u.E+s*u.N,a.N-s*u.E-c*u.N))
            if len(candidates) >= 256:
                break
        seen = set()
        for t in candidates:
            signature = tuple(int(round(v/tolerance)) for p in (points[0],points[len(points)//2]) for v in mapped(p,t)[:2])
            if signature in seen:
                continue
            seen.add(signature)
            score = coverage(buckets,t)
            if score >= 0.95:
                accepted.append((t,layer,score))
    if not accepted:
        raise ValueError('Não foi possível relacionar o DWG ao levantamento por vértices comuns (mínimo 95% dentro de 2 mm). Confira o DWG de origem ou selecione uma referência manual compatível.')
    chosen, layer, score = max(accepted,key=lambda item:item[2])
    for other, other_layer, other_score in accepted:
        if any(math.hypot(mapped(p,chosen).E-mapped(p,other).E,mapped(p,chosen).N-mapped(p,other).N) > tolerance
               for p in groups[layer][:16]):
            raise ValueError('Há mais de uma correspondência possível entre DWG e levantamento. Selecione uma referência manual compatível.')
    return dict(Cos=chosen[0],Sin=chosen[1],East=chosen[2],North=chosen[3],Layer=layer,
                Coverage=score,ToleranceMetres=tolerance,Method='Common survey vertices; rigid XY')


def number(text):
    text = text.strip()
    if ',' in text and '.' in text:
        raise ValueError('Use números sem separadores de milhar.')
    if not NUMBER_PATTERN.match(text):
        raise ValueError('Número inválido: {0}'.format(text))
    value = float(text.replace(',', '.'))
    if not finite(value):
        raise ValueError('Número não finito.')
    return value


def split_line(line, separator):
    """Same single-line quote semantics as the original Survey.Split."""
    fields, field = [], []
    quoted = False
    i = 0
    while i < len(line):
        char = line[i]
        if char == '"':
            if quoted and i + 1 < len(line) and line[i + 1] == '"':
                field.append('"')
                i += 1
            else:
                quoted = not quoted
        elif char == separator and not quoted:
            fields.append(''.join(field))
            field = []
        else:
            field.append(char)
        i += 1
    if quoted:
        raise ValueError('Aspas não fechadas. Campos multilinha não são suportados.')
    fields.append(''.join(field))
    return fields


def detect_columns(path):
    aliases = (
        ('X', 'E', 'ESTE', 'LESTE', 'EASTING', 'X_LESTE', 'X_ESTE'),
        ('Y', 'N', 'NORTE', 'NORTHING', 'Y_NORTE'),
        ('Z', 'COTA', 'ELEVACAO', 'ELEVAÇÃO', 'ELEVATION', 'Z_COTA'))
    with codecs.open(path, 'r', 'utf-8-sig') as stream:
        first = next((line for line in stream if line.strip()), '')
    for separator in (';', ',', '\t'):
        try:
            names = [s.strip().upper() for s in split_line(first, separator)]
        except ValueError:
            continue
        columns = [next((i for i, name in enumerate(names) if name in group), -1)
                   for group in aliases]
        if min(columns) >= 0 and len(set(columns)) == 3:
            return separator, columns
    return None


def read_points(path, separator=';', columns=(0, 1, 2), header=True, factor=1.0):
    if len(columns) != 3 or min(columns) < 0 or len(set(columns)) != 3:
        raise ValueError('As três colunas devem ser diferentes e começar em 1.')
    if separator not in (';', ',', '\t'):
        raise ValueError('Separador inválido.')
    if not finite(factor) or factor <= 0:
        raise ValueError('Unidade inválida.')
    points, errors = [], []
    skipped_header = False
    count = 0
    with codecs.open(path, 'r', 'utf-8-sig') as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            if header and not skipped_header:
                skipped_header = True
                continue
            count += 1
            # Count invalid records too, to bound memory and diagnostics.
            if count > MAX_INPUT:
                raise ValueError('Limite de entrada: 100.000 pontos. Reduza o levantamento.')
            try:
                fields = split_line(line.rstrip('\r\n'), separator)
                if len(fields) <= max(columns):
                    raise ValueError('Colunas insuficientes.')
                values = [number(fields[i]) * factor for i in columns]
                if not all(finite(v) for v in values):
                    raise ValueError('Coordenada não finita após conversão de unidade.')
                points.append(Point(*values))
            except (ValueError, OverflowError) as error:
                errors.append('Linha {0}: {1}'.format(line_number, error))
    return ReadResult(points, errors)


def grid_key(value):
    """Math.Round(double, 3): scale, ties-to-even, unscale (not Python 2 round).

    .NET leaves values >= 1e16 unchanged. Keeping the rounded coordinate as
    the key also preserves its floating-point equality semantics.
    """
    if abs(value) >= 1e16:
        return value
    scaled = value * 1000.0
    low = math.floor(scaled)
    fraction = scaled - low
    if fraction > 0.5 or (fraction == 0.5 and low % 2 != 0):
        low += 1
    return low / 1000.0


def hull(points):
    ordered = sorted(points, key=lambda p: (p.E, p.N))
    if len(ordered) < 3:
        return ordered

    def cross(a, b, c):
        return (b.E - a.E) * (c.N - a.N) - (b.N - a.N) * (c.E - a.E)

    def chain(items):
        result = []
        for point in items:
            while len(result) >= 2 and cross(result[-2], result[-1], point) <= 1e-9:
                result.pop()
            result.append(point)
        return result
    return chain(ordered)[:-1] + chain(reversed(ordered))[:-1]


def deduplicate(points):
    """Keep diagnostics available even when the resulting geometry is invalid."""
    by_xy, unique, conflicts = {}, [], []
    duplicates = 0
    for point in points:
        if not all(finite(v) for v in point):
            raise ValueError('Coordenada não finita.')
        key = (grid_key(point.E), grid_key(point.N))
        previous = by_xy.get(key)
        if previous is None:
            by_xy[key] = point
            unique.append(point)
        elif abs(previous.Z - point.Z) > 0.001 + 1e-9:
            conflicts.append('E={0:.3f}; N={1:.3f}: cotas {2:.3f} / {3:.3f}'.format(
                point.E, point.N, previous.Z, point.Z))
        else:
            duplicates += 1
    return Analysis(unique, duplicates, conflicts)


def validate_analysis(analysis):
    if len(analysis.points) < 3:
        raise ValueError('São necessários ao menos três pontos distintos em planta.')
    if len(analysis.points) > MAX_CREATE:
        raise ValueError('Limite de criação: 20.000 pontos únicos. Reduza os dados.')
    if len(hull(analysis.points)) < 3:
        raise ValueError('Os pontos são colineares em planta.')
    return analysis


def analyze(points):
    return validate_analysis(deduplicate(points))


def triangle_height(east, north, a, b, c):
    """Interpolate Z vertically on a triangle, or return None outside its XY area.

    All coordinates use the same unit. Translating before calculating the
    determinants avoids loss of precision with large survey coordinates.
    """
    ax, ay = a.E - c.E, a.N - c.N
    bx, by = b.E - c.E, b.N - c.N
    px, py = east - c.E, north - c.N
    determinant = ax * by - bx * ay
    if abs(determinant) < 1e-18:
        return None
    wa = (px * by - bx * py) / determinant
    wb = (ax * py - px * ay) / determinant
    wc = 1 - wa - wb
    if min(wa, wb, wc) < -1e-9 or max(wa, wb, wc) > 1 + 1e-9:
        return None
    return wa * a.Z + wb * b.Z + wc * c.Z


def summary(analysis):
    points = analysis.points
    east, north, z = zip(*points)
    return dict(count=len(points), duplicates=analysis.duplicates,
                width=max(east) - min(east), height=max(north) - min(north),
                min_z=min(z), max_z=max(z), relief=max(z) - min(z),
                anchor_e=(min(east) + max(east)) / 2,
                anchor_n=(min(north) + max(north)) / 2)


def occurrence_rows(errors, conflicts, geometry_error=None):
    rows = []
    for error in errors:
        rows.append(('Erro de leitura', error,
                     'Corrija a linha, separador, colunas ou unidade e releia a origem.'))
    for conflict in conflicts:
        rows.append(('Aviso aceito', conflict,
                     'Primeira cota mantida na grade XY de 1 mm; a posterior foi ignorada.'))
    if geometry_error:
        rows.append(('Erro de geometria', geometry_error,
                     'Confira os pontos e as camadas selecionadas antes de criar.'))
    return rows


def write_occurrences(path, rows):
    def quote(value):
        return '"' + text_type(value).replace('"', '""') + '"'
    with codecs.open(path, 'w', 'utf-8-sig') as stream:
        stream.write('Número;Tipo;Detalhe;Orientação\r\n')
        for index, row in enumerate(rows, 1):
            stream.write('{0};{1}\r\n'.format(index, ';'.join(quote(s) for s in row)))


def write_report(path, report):
    with codecs.open(path, 'w', 'utf-8') as stream:
        stream.write(text_type(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)))
