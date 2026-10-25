# -*- coding: utf-8 -*-
"""Bounded, local-coordinate terrain mesh for display only (Python 2.7/3)."""
from __future__ import division
import math
from topobim_core import hull


def sample_points(points, limit=1400):
    if len(points) <= limit:
        return list(points)
    boundary = hull(points)
    stride = max(1, int(math.ceil(len(boundary) / 200.0)))
    chosen = set(boundary[::stride])
    chosen.update((min(points, key=lambda p: p.Z), max(points, key=lambda p: p.Z)))
    # Sort spatially so changing CSV row order does not change the sampling.
    ordered = sorted(points)
    slots = limit - len(chosen)
    chosen.update(ordered[int(i * len(ordered) / slots)] for i in range(slots))
    return sorted(chosen)


def terrain_mesh(points):
    """Return centered XYZ vertices and CCW triangles; never change survey data.

    Incremental Delaunay triangulation with cached circumcircles. XY is normalized
    before predicates to avoid cancellation at UTM coordinate magnitudes.
    The preview has its own triangulation, independent of Revit's final surface.
    """
    selected = sample_points(points)
    if len(selected) < 3:
        return [], []
    east, north, heights = zip(*selected)
    origin = ((min(east) + max(east)) / 2, (min(north) + max(north)) / 2,
              (min(heights) + max(heights)) / 2)
    span = max(max(east) - min(east), max(north) - min(north), 0.001)
    vertices = [(p.E - origin[0], p.N - origin[1], p.Z - origin[2]) for p in selected]
    xy = [(p[0] / span, p[1] / span) for p in vertices]
    count = len(xy)
    xy.extend([(-4096.0, -2048.0), (4096.0, -2048.0), (0.0, 4096.0)])

    def triangle(a, b, c):
        ax, ay = xy[a]
        bx, by = xy[b][0] - ax, xy[b][1] - ay
        cx, cy = xy[c][0] - ax, xy[c][1] - ay
        cross = bx * cy - by * cx
        if abs(cross) < 1e-15:
            return None
        bb, cc = bx * bx + by * by, cx * cx + cy * cy
        ux = (cy * bb - by * cc) / (2 * cross)
        uy = (bx * cc - cx * bb) / (2 * cross)
        indices = (a, b, c) if cross > 0 else (a, c, b)
        return indices, (ux + ax, uy + ay, ux * ux + uy * uy)

    triangles = [triangle(count, count + 1, count + 2)]
    # Alternate across the sorted points to avoid a long, narrow insertion front.
    order = list(range(0, count, 2)) + list(range(1, count, 2))[::-1]
    for index in order:
        px, py = xy[index]
        remaining, edges = [], {}
        for item in triangles:
            indices, circle = item
            dx, dy = px - circle[0], py - circle[1]
            if dx * dx + dy * dy <= circle[2] + 1e-13:
                a, b, c = indices
                for edge in ((a, b), (b, c), (c, a)):
                    key = tuple(sorted(edge))
                    if key in edges:
                        del edges[key]
                    else:
                        edges[key] = edge
            else:
                remaining.append(item)
        for a, b in edges.values():
            item = triangle(a, b, index)
            if item is not None:
                remaining.append(item)
        triangles = remaining
    return vertices, [indices for indices, circle in triangles if max(indices) < count]


def camera_frame(yaw, pitch):
    """Orthonormal camera basis: camera-to-target opposite, screen right and up."""
    a, b = math.radians(yaw), math.radians(pitch)
    outward = (math.cos(b) * math.cos(a), math.cos(b) * math.sin(a), math.sin(b))
    right = (-math.sin(a), math.cos(a), 0.0)
    up = (-math.sin(b) * math.cos(a), -math.sin(b) * math.sin(a), math.cos(b))
    return outward, right, up
