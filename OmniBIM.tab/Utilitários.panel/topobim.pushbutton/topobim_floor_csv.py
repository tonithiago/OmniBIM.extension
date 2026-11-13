# -*- coding: utf-8 -*-
"""Ordered CSV vertices grouped into floor layers; no Revit dependency."""
from __future__ import division, unicode_literals
import topobim_core as core
import topobim_floor_geometry as geom


class AreaMap(dict):
    pass


def _read_vertex(line, separator, columns, factor, layer_column, contour_column):
    # Keep exception handlers outside the file loop. IronPython's interpreter
    # can retain handler frames across iterations until the native stack fills.
    try:
        fields = core.split_line(line.rstrip('\r\n'), separator)
        indexes = list(columns) + [layer_column]
        if contour_column is not None:
            indexes.append(contour_column)
        if len(fields) <= max(indexes):
            raise ValueError('Colunas insuficientes.')
        layer = fields[layer_column].strip()
        contour = fields[contour_column].strip() if contour_column is not None else '1'
        if not layer or not contour:
            raise ValueError('Layer e contorno não podem ficar vazios.')
        values = [core.number(fields[i]) * factor for i in columns]
        if not all(core.finite(v) for v in values):
            raise ValueError('Coordenada não finita após conversão de unidade.')
        return (layer, contour, core.Point(*values)), None
    except (ValueError, OverflowError) as error:
        return None, core.text_type(error)


def _read_layer(contours):
    # Return the diagnostic instead of raising again inside a nested handler.
    # Returning also unwinds the interpreter before the next invalid layer.
    loops = []
    for contour in sorted(contours):
        try:
            loops.append(geom.clean_loop(contours[contour]))
        except ValueError as error:
            return None, 'Contorno {0}: {1}'.format(contour, core.text_type(error))
    try:
        return geom.regions(loops), None
    except ValueError as error:
        return None, core.text_type(error)


def detect_groups(path, separator, header):
    if not header:
        return None, None
    with core._open_survey(path) as stream:
        first = next((line for line in stream if line.strip()), '')
    names = [field.strip().upper() for field in core.split_line(first.rstrip('\r\n'), separator)]
    return tuple(next((i for i, name in enumerate(names) if name in aliases), None)
                 for aliases in (('LAYER', 'CAMADA'), ('CONTORNO', 'CONTOUR', 'POLIGONO', 'POLÍGONO')))


def read_areas(path, separator=';', columns=(0, 1, 2), header=True,
               factor=1.0, layer_column=3, contour_column=None):
    indexes = list(columns) + [layer_column]
    if contour_column is not None:
        indexes.append(contour_column)
    if len(columns) != 3 or any(i is None or i < 0 for i in indexes) or len(set(indexes)) != len(indexes):
        raise ValueError('Informe colunas diferentes para E, N, Z, layer e contorno, começando em 1.')
    if separator not in (';', ',', '\t') or not core.finite(factor) or factor <= 0:
        raise ValueError('Separador ou unidade inválidos.')
    groups, errors = {}, []
    skipped_header, count = False, 0
    with core._open_survey(path) as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            if header and not skipped_header:
                skipped_header = True
                continue
            count += 1
            if count > core.MAX_INPUT:
                raise ValueError('Limite de entrada: 100.000 vértices. Reduza o CSV.')
            vertex, error = _read_vertex(line, separator, columns, factor,
                                         layer_column, contour_column)
            if error is not None:
                errors.append('Linha {0}: {1}'.format(line_number, error))
            else:
                layer, contour, point = vertex
                groups.setdefault(layer, {}).setdefault(contour, []).append(point)
    # Never drop a malformed vertex and silently close a different polygon.
    if errors:
        raise ValueError('Corrija os vértices do CSV antes de identificar os pisos.\n' + '\n'.join(errors[:15]))
    result, issues = AreaMap(), []
    result.elevated_regions = {}
    for layer in sorted(groups):
        regions, error = _read_layer(groups[layer])
        if error is None:
            result[layer] = regions
            result.elevated_regions[layer] = [any(abs(p.Z) > 0.001 for loop in [r.outer]+r.holes for p in loop)
                                              for r in regions]
        else:
            issues.append('{0}: {1} Camada não disponível para criação.'.format(layer, error))
    if not result:
        raise ValueError('Nenhum contorno de piso utilizável no CSV.\n'
                         'Confira a coluna de layer: ela deve agrupar os vértices de uma área, '
                         'não identificar cada ponto individualmente. Cada contorno precisa de '
                         'pelo menos três vértices em sequência.\n' + '\n'.join(issues[:15]))
    return result, issues
