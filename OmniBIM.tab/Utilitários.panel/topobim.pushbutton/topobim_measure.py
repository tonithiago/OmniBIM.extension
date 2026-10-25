# -*- coding: utf-8 -*-
"""Measurement math in survey metres; no Revit or WPF dependency."""
from __future__ import division, unicode_literals
import math


def snap_vertex(points, east, north, radius, ambiguity):
    """Return an original vertex, or reject a miss/ambiguous nearby selection."""
    nearest = []
    for point in points:
        squared = (point[0]-east)**2 + (point[1]-north)**2
        if squared <= radius*radius:
            nearest.append((squared, point))
    if not nearest:
        return None, False
    nearest.sort(key=lambda item: item[0])
    if len(nearest) > 1 and math.sqrt(nearest[1][0])-math.sqrt(nearest[0][0]) < ambiguity:
        return None, True
    return nearest[0][1], False


def distance(a, b):
    horizontal = math.hypot(b[0] - a[0], b[1] - a[1])
    return math.hypot(horizontal, b[2] - a[2]), horizontal


def polygon_area(points):
    if len(points) < 3:
        raise ValueError('Selecione pelo menos três pontos para a área.')
    # Work near the origin to retain precision with large UTM coordinates.
    x, y = points[0][:2]
    ring = [(p[0]-x, p[1]-y) for p in points]
    count = len(ring)

    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])

    def on_segment(a, b, p):
        return (abs(cross(a, b, p)) <= 1e-9 and
                min(a[0], b[0])-1e-9 <= p[0] <= max(a[0], b[0])+1e-9 and
                min(a[1], b[1])-1e-9 <= p[1] <= max(a[1], b[1])+1e-9)

    for i in range(count):
        a, b = ring[i], ring[(i+1) % count]
        if math.hypot(a[0]-b[0], a[1]-b[1]) < 1e-6:
            raise ValueError('Há pontos repetidos no contorno. Desfaça o último ponto.')
        for j in range(i+1, count):
            if j == i+1 or (i == 0 and j == count-1):
                continue
            c, d = ring[j], ring[(j+1) % count]
            if ((cross(a,b,c)*cross(a,b,d) < 0 and cross(c,d,a)*cross(c,d,b) < 0) or
                    on_segment(a,b,c) or on_segment(a,b,d) or
                    on_segment(c,d,a) or on_segment(c,d,b)):
                raise ValueError('O contorno se cruza ou se toca. Desfaça pontos e refaça a seleção.')
    area = abs(sum(ring[i][0]*ring[(i+1) % count][1] -
                   ring[(i+1) % count][0]*ring[i][1] for i in range(count))) / 2
    if area < 1e-8:
        raise ValueError('Os pontos não delimitam uma área. Selecione pontos fora da mesma linha.')
    return area


def ray_hit(origin, direction, vertices, triangles):
    """Nearest positive ray/triangle intersection, double-sided, in local XYZ."""
    def sub(a, b):
        return tuple(a[i]-b[i] for i in range(3))
    def dot(a, b):
        return sum(a[i]*b[i] for i in range(3))
    def cross(a, b):
        return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    nearest = None
    for indices in triangles:
        a, b, c = [vertices[i] for i in indices]
        ab, ac = sub(b,a), sub(c,a)
        h = cross(direction, ac)
        determinant = dot(ab,h)
        if abs(determinant) < 1e-12:
            continue
        s = sub(origin,a)
        u = dot(s,h) / determinant
        if u < -1e-9 or u > 1+1e-9:
            continue
        q = cross(s,ab)
        v = dot(direction,q) / determinant
        if v < -1e-9 or u+v > 1+1e-9:
            continue
        t = dot(ac,q) / determinant
        if t >= 0 and (nearest is None or t < nearest):
            nearest = t
    if nearest is None:
        return None
    return tuple(origin[i] + nearest*direction[i] for i in range(3))
