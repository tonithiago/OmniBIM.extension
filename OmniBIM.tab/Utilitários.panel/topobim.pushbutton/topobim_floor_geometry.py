# -*- coding: utf-8 -*-
"""Planar CAD regions and terrain constraints. No Revit dependencies; metres."""
from __future__ import division, unicode_literals
import math
from collections import namedtuple
from topobim_core import Point, triangle_height, text_type

TOL = 0.0001
Region = namedtuple('Region', 'outer holes')


def distance(a, b):
    return math.hypot(a.E - b.E, a.N - b.N)


def cross(a, b, c):
    return (b.E-a.E)*(c.N-a.N)-(b.N-a.N)*(c.E-a.E)


def area(loop):
    # Translate before multiplying: survey coordinates can have millions of metres.
    return sum(cross(loop[0], loop[i], loop[i+1]) for i in range(1, len(loop)-1))/2


def on_segment(p, a, b):
    return (abs(cross(a, b, p)) <= TOL * max(distance(a, b), TOL) and
            min(a.E, b.E)-TOL <= p.E <= max(a.E, b.E)+TOL and
            min(a.N, b.N)-TOL <= p.N <= max(a.N, b.N)+TOL)


def inside(p, loop, boundary=True):
    result = False
    for a, b in edges(loop):
        if on_segment(p, a, b):
            return boundary
        if (a.N > p.N) != (b.N > p.N):
            if p.E < (b.E-a.E)*(p.N-a.N)/(b.N-a.N)+a.E:
                result = not result
    return result


def contains(p, region, boundary=True):
    return inside(p, region.outer, boundary) and not any(inside(p, h, not boundary) for h in region.holes)


def edges(loop):
    return zip(loop, loop[1:]+loop[:1])


def intersections(a, b, c, d):
    """Parameters on AB, including collinear overlapping endpoints."""
    dx, dy = b.E-a.E, b.N-a.N
    ex, ey = d.E-c.E, d.N-c.N
    denominator = dx*ey-dy*ex
    if abs(denominator) < 1e-12:
        if abs(cross(a, b, c)) > TOL * max(distance(a, b), TOL):
            return []
        length2 = dx*dx+dy*dy
        if length2 < TOL*TOL:
            return []
        return [max(0, min(1, ((p.E-a.E)*dx+(p.N-a.N)*dy)/length2))
                for p in (c, d) if on_segment(p, a, b)]
    t = ((c.E-a.E)*ey-(c.N-a.N)*ex)/denominator
    u = ((c.E-a.E)*dy-(c.N-a.N)*dx)/denominator
    return [max(0, min(1, t))] if -1e-10 <= t <= 1+1e-10 and -1e-10 <= u <= 1+1e-10 else []


def interpolate(a, b, t):
    return Point(a.E+(b.E-a.E)*t, a.N+(b.N-a.N)*t, a.Z+(b.Z-a.Z)*t)


def clean_loop(points):
    loop = []
    for p in points:
        if not loop or distance(p, loop[-1]) > TOL:
            loop.append(p)
    if len(loop) > 1 and distance(loop[0], loop[-1]) <= TOL:
        loop.pop()
    if len(loop) < 3 or abs(area(loop)) < 0.000001:
        raise ValueError('Contorno degenerado ou sem área.')
    if len(loop) > 2500:
        raise ValueError('Contorno excede 2.500 vértices. Simplifique ou divida a área no DWG.')
    segments = list(edges(loop))
    for i, (a, b) in enumerate(segments):
        for j in range(i+1, len(segments)):
            if j == i+1 or (i == 0 and j == len(segments)-1):
                continue
            if intersections(a, b, *segments[j]):
                raise ValueError('Contorno com cruzamento ou contato consigo mesmo.')
    return loop


def assemble(paths):
    """Join only unambiguous endpoints; open/branched networks are diagnostics."""
    loops, pending, issues = [], [], []
    for path in paths:
        if len(path) < 2:
            continue
        if distance(path[0], path[-1]) <= TOL:
            try:
                loops.append(clean_loop(path))
            except ValueError as error:
                issues.append(text_type(error))
        else:
            pending.append(list(path))
    def bucket(p):
        return int(math.floor(p.E/TOL)), int(math.floor(p.N/TOL))
    endpoints = {}
    active = set(range(len(pending)))
    for index, path in enumerate(pending):
        for reverse, p in ((False, path[0]), (True, path[-1])):
            endpoints.setdefault(bucket(p), []).append((index, reverse))
    for seed in range(len(pending)):
        if seed not in active:
            continue
        active.remove(seed)
        chain = list(pending[seed])
        ambiguous = False
        while distance(chain[0], chain[-1]) > TOL:
            x, y = bucket(chain[-1])
            matches = [(i, reverse) for xx in range(x-1,x+2) for yy in range(y-1,y+2)
                       for i, reverse in endpoints.get((xx,yy),[]) if i in active
                       and distance(chain[-1], pending[i][-1] if reverse else pending[i][0]) <= TOL]
            if len(matches) != 1:
                ambiguous = len(matches) > 1
                break
            index, reverse = matches[0]
            active.remove(index)
            path = pending[index]
            chain.extend((list(reversed(path)) if reverse else path)[1:])
        if distance(chain[0], chain[-1]) <= TOL:
            try:
                loops.append(clean_loop(chain))
            except ValueError as error:
                issues.append(text_type(error))
        else:
            issues.append('Curvas ramificadas/ambíguas.' if ambiguous else 'Curvas abertas ignoradas.')
    return loops, issues


def regions(loops):
    """Even/odd nesting: disconnected islands and holes, without a convex hull."""
    loops = sorted(loops, key=lambda p: -abs(area(p)))
    parents, depths = [], []
    for i, loop in enumerate(loops):
        for other in loops[:i]:
            if any(intersections(a, b, c, d) for a, b in edges(loop) for c, d in edges(other)):
                raise ValueError('Contornos se cruzam, se tocam ou estão duplicados na mesma camada.')
        candidates = [j for j in range(i) if inside(loop[0], loops[j], False)]
        parent = candidates[-1] if candidates else None
        parents.append(parent)
        depths.append(depths[parent]+1 if parent is not None else 0)
    return [Region(loop if area(loop) > 0 else list(reversed(loop)),
                   [h if area(h) < 0 else list(reversed(h)) for j, h in enumerate(loops)
                    if parents[j] == i and depths[j] % 2])
            for i, loop in enumerate(loops) if depths[i] % 2 == 0]


def region_area(region):
    return abs(area(region.outer))-sum(abs(area(h)) for h in region.holes)


def contour_surface(region):
    """Interpolate the 3D CAD outline; triangulate concave outer rings in XY.

    Hole vertices contribute their Z, but the hole remains excluded by the floor
    profile. This is a piecewise linear design surface, not a survey extrapolation.
    """
    remaining = list(region.outer)
    if area(remaining) < 0:
        remaining.reverse()
    triangles = []
    while len(remaining) > 3:
        found = False
        for i, b in enumerate(remaining):
            a, c = remaining[i-1], remaining[(i+1) % len(remaining)]
            if cross(a,b,c) <= 1e-12:
                continue
            if any(triangle_height(p.E,p.N,a,b,c) is not None for j,p in enumerate(remaining)
                   if j not in ((i-1) % len(remaining),i,(i+1) % len(remaining))):
                continue
            triangles.append((a,b,c))
            remaining.pop(i)
            found = True
            break
        if not found:
            raise ValueError('Não foi possível triangular as cotas do contorno DWG. Confira cruzamentos ou vértices coincidentes.')
    triangles.append(tuple(remaining))
    for hole in region.holes:
        for p in hole:
            updated = []
            for triangle in triangles:
                if any(distance(p,q) <= TOL for q in triangle):
                    updated.append(tuple(p if distance(p,q) <= TOL else q for q in triangle))
                elif triangle_height(p.E,p.N,*triangle) is None:
                    updated.append(triangle)
                else:
                    updated.extend((a,b,p) for a,b in edges(list(triangle)) if abs(cross(a,b,p)) > 1e-12)
            triangles = updated
    return Surface(triangles)


class Surface(object):
    """XY indexed mesh, sampled without extrapolation."""
    def __init__(self, triangles):
        self.triangles = [t for t in triangles if abs(cross(*t)) > 1e-12]
        if not self.triangles:
            raise ValueError('A superfície não contém triângulos utilizáveis.')
        points = [p for t in self.triangles for p in t]
        self.x, self.y = min(p.E for p in points), min(p.N for p in points)
        self.cell = max(0.1, max(max(p.E for p in points)-self.x, max(p.N for p in points)-self.y)
                        / max(1, min(128, math.sqrt(len(self.triangles)))))
        self.buckets = {}
        for index, triangle in enumerate(self.triangles):
            for key in self.keys(triangle):
                self.buckets.setdefault(key, []).append(index)
        self.grid_min = (min(k[0] for k in self.buckets), min(k[1] for k in self.buckets))
        self.grid_max = (max(k[0] for k in self.buckets), max(k[1] for k in self.buckets))
        self._boundary = None

    def key(self, p):
        return int(math.floor((p.E-self.x)/self.cell)), int(math.floor((p.N-self.y)/self.cell))

    def keys(self, points, clipped=False):
        low = self.key(Point(min(p.E for p in points), min(p.N for p in points), 0))
        high = self.key(Point(max(p.E for p in points), max(p.N for p in points), 0))
        if clipped:
            low = (max(low[0], self.grid_min[0]), max(low[1], self.grid_min[1]))
            high = (min(high[0], self.grid_max[0]), min(high[1], self.grid_max[1]))
        return [(x, y) for x in range(low[0], high[0]+1) for y in range(low[1], high[1]+1)]

    def boundary_height(self, p):
        """Use the nearest border's elevation outside surveyed coverage.

        This is a modelling reference, not an assertion of surveyed support.
        Do not prolong the edge triangle's slope over an unlimited distance.
        """
        if self._boundary is None:
            segments = {}
            counts = {}
            def key(q):
                return int(round(q.E/TOL)), int(round(q.N/TOL))
            for triangle in self.triangles:
                for a, b in edges(list(triangle)):
                    pair = tuple(sorted((key(a), key(b))))
                    segments[pair] = (a, b)
                    counts[pair] = counts.get(pair, 0)+1
            self._boundary = [segments[k] for k in segments if counts[k] == 1]
            if not self._boundary:
                self._boundary = list(segments.values())
        nearest, height = float('inf'), None
        for a, b in self._boundary:
            dx, dy = b.E-a.E, b.N-a.N
            length2 = dx*dx+dy*dy
            if length2 < 1e-20:
                continue
            t = max(0, min(1, ((p.E-a.E)*dx+(p.N-a.N)*dy)/length2))
            q = interpolate(a, b, t)
            gap = distance(p, q)
            if gap < nearest:
                nearest, height = gap, q.Z
        if height is None:
            raise ValueError('Não foi possível obter a cota de referência da borda do terreno.')
        return height

    def height(self, p, highest=True, allow_outside=False):
        x, y = self.key(p)
        candidates = set(i for xx in range(x-1, x+2) for yy in range(y-1, y+2)
                         for i in self.buckets.get((xx, yy), []))
        values = [triangle_height(p.E, p.N, *self.triangles[i]) for i in candidates]
        values = [v for v in values if v is not None]
        # Revit's triangulation can round boundary XY by a few micrometres.
        # Clamp only within 0.1 mm, including the edge of a hole; never extend a
        # floor to an unsupported area or bridge a hole by extrapolation.
        if not values:
            nearest, height = TOL, None
            for i in candidates:
                for a, b in edges(list(self.triangles[i])):
                    dx, dy = b.E-a.E, b.N-a.N
                    length2 = dx*dx+dy*dy
                    if length2 < 1e-20:
                        continue
                    t = max(0, min(1, ((p.E-a.E)*dx+(p.N-a.N)*dy)/length2))
                    q = interpolate(a, b, t)
                    gap = distance(p, q)
                    if gap <= nearest:
                        nearest, height = gap, q.Z
            if height is not None:
                values.append(height)
        if not values:
            if allow_outside:
                return self.boundary_height(p)
            raise ValueError('Uma área de piso está fora da superfície do terreno (E {0:.3f}, N {1:.3f}).'.format(p.E, p.N))
        return max(values) if highest else min(values)

    def constraints(self, region, limit=5000, allow_outside=False):
        """Split CAD boundaries at terrain edges; clip terrain breaklines to region."""
        loops = [region.outer]+region.holes
        for loop in loops:
            for p in loop:
                self.height(p, allow_outside=allow_outside)
        boundary = [segment for loop in loops for segment in edges(loop)]
        candidate_ids = set(i for key in self.keys(region.outer, clipped=True) for i in self.buckets.get(key, []))
        terrain_edges = {}
        def key(p):
            return int(round(p.E/TOL)), int(round(p.N/TOL))
        for i in candidate_ids:
            for a, b in edges(list(self.triangles[i])):
                terrain_edges[tuple(sorted((key(a), key(b))))] = (a, b)
        cuts = [[] for s in boundary]
        lines, points = [], {}
        def add(p):
            q = Point(p.E, p.N, self.height(p, allow_outside=allow_outside))
            points.setdefault(key(q), q)
            if len(points) > limit:
                raise ValueError('Área de piso excede {0} pontos de conformação. Divida o contorno no DWG.'.format(limit))
            return points[key(q)]
        for a, b in terrain_edges.values():
            parameters = [0.0, 1.0]
            for index, (c, d) in enumerate(boundary):
                parameters.extend(intersections(a, b, c, d))
                cuts[index].extend(intersections(c, d, a, b))
            parameters = sorted(set(parameters))
            for t, u in zip(parameters, parameters[1:]):
                if distance(interpolate(a, b, t), interpolate(a, b, u)) <= TOL:
                    continue
                if contains(interpolate(a, b, (t+u)/2), region, False):
                    lines.append((add(interpolate(a, b, t)), add(interpolate(a, b, u))))
        split_loops, index = [], 0
        for loop in loops:
            split = []
            for a, b in edges(loop):
                for t in sorted(set([0.0]+[t for t in cuts[index] if t < 1-1e-10])):
                    q = add(interpolate(a, b, t))
                    if not split or distance(q, split[-1]) > TOL:
                        split.append(q)
                index += 1
            if distance(split[0], split[-1]) <= TOL:
                split.pop()
            split_loops.append(split)
        return split_loops, list(points.values()), lines
