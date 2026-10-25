# -*- coding: utf-8 -*-
"""WPF terrain viewport. Geometry is cached; mouse gestures only move the camera."""
from __future__ import division, unicode_literals
import math
from System.Windows import Point
from System.Windows.Media import Color, Colors
from System.Windows.Media.Media3D import (MeshGeometry3D, Point3D, Vector3D,
    GeometryModel3D, Model3DGroup, ModelVisual3D, DiffuseMaterial,
    AmbientLight, DirectionalLight, OrthographicCamera)
from topobim_preview import terrain_mesh, camera_frame, sample_points
from topobim_core import Point as SurveyPoint, triangle_height
from topobim_measure import ray_hit


class TerrainView(object):
    def __init__(self, viewport):
        self.viewport = viewport
        self.radius = 1.0
        self.point_count = 0
        self.ready = False
        self.vertices, self.triangles = [], []
        self.origin = (0, 0, 0)
        self.frame = None

    def clear(self):
        self.viewport.Children.Clear()
        self.ready = False
        self.point_count = 0
        self.vertices, self.triangles = [], []
        self.frame = None

    def build(self, points):
        self.clear()
        selected = sample_points(points)
        vertices, triangles = terrain_mesh(selected)
        if not triangles:
            return False
        self.vertices, self.triangles = vertices, triangles
        self.origin = tuple((min(p[i] for p in selected)+max(p[i] for p in selected))/2 for i in range(3))
        self.radius = max(0.01, max(math.sqrt(sum(v * v for v in p)) for p in vertices))
        low, high = min(p[2] for p in vertices), max(p[2] for p in vertices)
        mesh = MeshGeometry3D()
        # Separate triangle vertices give the surface a readable, faceted relief.
        for triangle in triangles:
            for index in triangle:
                x, y, z = vertices[index]
                mesh.TriangleIndices.Add(mesh.Positions.Count)
                mesh.Positions.Add(Point3D(x, y, z))
                mesh.TextureCoordinates.Add(Point(0.5, (z - low) / max(high - low, 0.001)))
        mesh.Freeze()
        material = DiffuseMaterial(self.viewport.FindResource('TerrainSurfaceBrush'))
        model = GeometryModel3D(mesh, material)
        model.BackMaterial = material
        group = Model3DGroup()
        group.Children.Add(AmbientLight(Color.FromRgb(105, 105, 105)))
        group.Children.Add(DirectionalLight(Colors.White, Vector3D(-0.4, 0.6, -1)))
        group.Children.Add(model)
        group.Freeze()
        visual = ModelVisual3D()
        visual.Content = group
        self.viewport.Children.Add(visual)
        self.point_count = len(vertices)
        self.ready = True
        return True

    def camera(self, width, height, zoom, offset, yaw, pitch):
        if not self.ready or width < 1 or height < 1:
            return
        outward, right, up = camera_frame(yaw, pitch)
        view_width = 2.25 * self.radius * max(1.0, width / height) / zoom
        per_pixel = view_width / width
        target = [(-right[i] * offset[0] + up[i] * offset[1]) * per_pixel for i in range(3)]
        distance = self.radius * 4
        position = [target[i] + outward[i] * distance for i in range(3)]
        camera = OrthographicCamera()
        camera.Position = Point3D(*position)
        camera.LookDirection = Vector3D(*[-v * distance for v in outward])
        camera.UpDirection = Vector3D(*up)
        camera.Width = view_width
        camera.NearPlaneDistance = self.radius * 0.01
        camera.FarPlaneDistance = self.radius * 10
        self.viewport.Camera = camera
        self.frame = (width, height, per_pixel, tuple(position), outward, right, up)

    def project(self, point):
        if self.frame is None:
            return None
        width, height, scale, position, outward, right, up = self.frame
        relative = [point[i]-self.origin[i]-position[i] for i in range(3)]
        return (width/2 + sum(relative[i]*right[i] for i in range(3))/scale,
                height/2 - sum(relative[i]*up[i] for i in range(3))/scale)

    def pick(self, x, y):
        if self.frame is None:
            return None
        width, height, scale, position, outward, right, up = self.frame
        origin = tuple(position[i] + right[i]*(x-width/2)*scale - up[i]*(y-height/2)*scale for i in range(3))
        local = ray_hit(origin, tuple(-v for v in outward), self.vertices, self.triangles)
        return None if local is None else SurveyPoint(*[local[i]+self.origin[i] for i in range(3)])

    def elevation(self, east, north):
        x, y = east-self.origin[0], north-self.origin[1]
        for indices in self.triangles:
            triangle = [SurveyPoint(*self.vertices[i]) for i in indices]
            z = triangle_height(x, y, *triangle)
            if z is not None:
                return SurveyPoint(east, north, z+self.origin[2])
        return None
