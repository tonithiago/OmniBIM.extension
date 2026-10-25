# -*- coding: utf-8 -*-
"""Optional DWG floor regions and native Revit 2026 shape-edited floors."""
from __future__ import division, unicode_literals
import json
import hashlib
from System.Collections.Generic import List
from pyrevit import DB
import topobim_core as core
import topobim_floor_geometry as geom
import topobim_revit as service


class SurfaceUnavailable(ValueError):
    pass


class AreaMap(dict):
    pass


def floor_choices(doc):
    result = []
    for element in DB.FilteredElementCollector(doc).OfClass(DB.FloorType):
        if element.IsFoundationSlab:
            continue
        choice = service.Choice(element)
        structure = element.GetCompoundStructure()
        materials = []
        if structure is not None:
            try:
                for layer in structure.GetLayers():
                    material = doc.GetElement(layer.MaterialId)
                    name = material.Name if material is not None else 'Por categoria'
                    if name not in materials:
                        materials.append(name)
                choice.Label = '{0} · {1:.0f} mm · {2}{3}'.format(
                    choice.Name, service.metres(structure.GetWidth())*1000,
                    ' / '.join(materials), ' (camada variável)' if structure.VariableLayerIndex >= 0 else '')
            finally:
                structure.Dispose()
        result.append(choice)
    return sorted(result, key=lambda c: (c.Name, str(c.Id)))


def read_areas(doc, element_id, original=True):
    cad = doc.GetElement(element_id)
    if not isinstance(cad, DB.ImportInstance) or cad.ViewSpecific:
        raise ValueError('Selecione um DWG de modelo, sem a opção Somente vista atual.')
    output = cad.GetTransform().Inverse if original else service.internal_to_shared(doc.ActiveProjectLocation)
    paths = {}
    count = [0]

    def walk(geometry, transform, inherited):
        for obj in geometry:
            layer = inherited
            style = doc.GetElement(obj.GraphicsStyleId)
            if isinstance(style, DB.GraphicsStyle) and style.GraphicsStyleCategory is not None:
                layer = style.GraphicsStyleCategory.Name
            if isinstance(obj, DB.GeometryInstance):
                nested = obj.GetSymbolGeometry()
                if nested is not None:
                    try:
                        walk(nested, transform.Multiply(obj.Transform), layer)
                    finally:
                        nested.Dispose()
            elif isinstance(obj, (DB.PolyLine, DB.Curve)):
                vertices = obj.GetCoordinates() if isinstance(obj, DB.PolyLine) else obj.Tessellate()
                path = []
                for p in vertices:
                    q = output.OfPoint(transform.OfPoint(p))
                    path.append(core.Point(service.metres(q.X), service.metres(q.Y), service.metres(q.Z)))
                count[0] += len(path)
                if count[0] > core.MAX_INPUT:
                    raise ValueError('DWG excede 100.000 vértices de contorno. Simplifique o arquivo.')
                paths.setdefault(layer, []).append(path)
    options = DB.Options()
    options.IncludeNonVisibleObjects = True
    options.DetailLevel = DB.ViewDetailLevel.Fine
    try:
        geometry = cad.get_Geometry(options)
        if geometry is None:
            raise ValueError('DWG sem geometria de contornos disponível.')
        try:
            walk(geometry, DB.Transform.Identity, 'Sem camada')
        finally:
            geometry.Dispose()
    finally:
        options.Dispose()
    result, issues = AreaMap(), []
    result.elevated_regions = {}
    for layer in sorted(paths):
        loops, errors = geom.assemble(paths[layer])
        issues.extend('{0}: {1}'.format(layer, error) for error in errors)
        if loops:
            try:
                result[layer] = geom.regions(loops)
                flags = []
                for region in result[layer]:
                    vertices = [p for loop in [region.outer]+region.holes for p in loop]
                    if original:
                        flags.append(any(abs(p.Z) > 0.001 for p in vertices))
                    else:
                        shared_to_wcs = cad.GetTransform().Inverse.Multiply(output.Inverse)
                        flags.append(any(abs(shared_to_wcs.OfPoint(DB.XYZ(service.feet(p.E),service.feet(p.N),service.feet(p.Z))).Z) > service.feet(0.001) for p in vertices))
                result.elevated_regions[layer] = flags
            except ValueError as error:
                issues.append('{0}: {1} Camada não disponível para criação.'.format(layer, core.text_type(error)))
    if not result:
        raise ValueError('Nenhum contorno fechado utilizável. Use polilinhas fechadas ou curvas conectadas sem ramificações.\n'+'\n'.join(issues[:15]))
    return result, issues


def signature(areas, layers):
    data = [(layer, [[[[round(p.E, 6), round(p.N, 6), round(p.Z, 6)] for p in loop] for loop in [r.outer]+r.holes]
                     for r in areas[layer]]) for layer in sorted(layers)]
    return hashlib.sha256(json.dumps(data, ensure_ascii=True, sort_keys=True).encode('utf-8')).hexdigest()


def read_registered_areas(doc, element_id, survey):
    groups = {}
    for vertex in service.read_cad(doc, element_id, True):
        groups.setdefault(vertex.layer, []).append(vertex.point)
    registration = core.register_survey(survey, groups)
    areas, issues = read_areas(doc, element_id, True)
    c,s,e,n = [registration[k] for k in ('Cos','Sin','East','North')]

    def move(p):
        return core.Point(c*p.E-s*p.N+e,s*p.E+c*p.N+n,p.Z)

    result = AreaMap({layer: [geom.Region([move(p) for p in r.outer],
                                        [[move(p) for p in loop] for loop in r.holes])
                             for r in regions] for layer, regions in areas.items()})
    result.elevated_regions = areas.elevated_regions
    result.registration = registration
    return result, issues


def prepare(doc, settings):
    """Read before changing the site, preserving the reviewed shared frame."""
    if not settings:
        return None
    if settings.get('RegisterSurvey'):
        areas, issues = read_registered_areas(doc, settings['CadId'], settings['SurveyPoints'])
    else:
        areas, issues = read_areas(doc, settings['CadId'], settings['Original'])
    layers = [name for name, type_id in settings['Layers']]
    if any(name not in areas for name in layers) or signature(areas, layers) != settings['Signature']:
        raise ValueError('O DWG mudou desde a conferência. Identifique e confira as áreas novamente.')
    prepared = dict(settings)
    prepared.update(Areas=areas, Issues=issues)
    if not settings['Original'] and not settings.get('RegisterSurvey'):
        # "Position in project" means the CAD instance's actual model position.
        # Snapshot INTERNAL geometry before changing ProjectLocation, so a new
        # shared origin does not translate these already placed contours again.
        prepared['InternalAreas'] = {name: [internal_region(r,doc.ActiveProjectLocation) for r in areas[name]]
                                     for name in layers}
    return prepared


def surface(element, upper=True):
    """Extract only the physical top or bottom faces, in internal metres."""
    triangles = []
    box = element.get_BoundingBox(None)
    origin = DB.XYZ((box.Min.X+box.Max.X)/2, (box.Min.Y+box.Max.Y)/2,
                    (box.Min.Z+box.Max.Z)/2) if box is not None else DB.XYZ.Zero
    shift = DB.Transform.CreateTranslation(DB.XYZ(-origin.X,-origin.Y,-origin.Z))
    restore = DB.Transform.CreateTranslation(origin)

    def read_faces(solid):
        for face in solid.Faces:
            mesh = face.Triangulate()
            try:
                for index in range(mesh.NumTriangles):
                    triangle = mesh.get_Triangle(index)
                    local = [triangle.get_Vertex(i) for i in range(3)]
                    center = DB.XYZ(sum(p.X for p in local)/3, sum(p.Y for p in local)/3, sum(p.Z for p in local)/3)
                    projection = face.Project(center)
                    if projection is None:
                        continue
                    normal = face.ComputeNormal(projection.UVPoint)
                    if (normal.Z if upper else -normal.Z) <= 1e-8:
                        continue
                    vertices = [restore.OfPoint(p) for p in local]
                    triangles.append(tuple(core.Point(service.metres(p.X), service.metres(p.Y), service.metres(p.Z)) for p in vertices))
            finally:
                mesh.Dispose()

    def walk(geometry, transform):
        for obj in geometry:
            if isinstance(obj, DB.GeometryInstance):
                nested = obj.GetSymbolGeometry()
                if nested is not None:
                    try:
                        walk(nested, transform.Multiply(obj.Transform))
                    finally:
                        nested.Dispose()
            elif isinstance(obj, DB.Solid):
                if obj.Faces.Size == 0:
                    continue
                # Tessellate a temporary local solid. Translating mesh vertices
                # AFTER tessellation cannot recover precision already lost far
                # from the origin. The document/element itself is never moved.
                local_solid = DB.SolidUtils.CreateTransformed(obj, shift.Multiply(transform))
                try:
                    read_faces(local_solid)
                finally:
                    local_solid.Dispose()
    options = DB.Options()
    options.DetailLevel = DB.ViewDetailLevel.Fine
    try:
        geometry = element.get_Geometry(options)
        if geometry is not None:
            try:
                walk(geometry, DB.Transform.Identity)
            finally:
                geometry.Dispose()
    finally:
        options.Dispose()
    if not any(abs(geom.cross(*t)) > 1e-12 for t in triangles):
        raise SurfaceUnavailable('O Revit não disponibilizou triângulos da face {0} do elemento {1}.'.format('superior' if upper else 'inferior', element.Id))
    return geom.Surface(triangles)


def excavate(doc, topo, floor):
    """An outside floor is valid; only intersecting floors excavate the host."""
    a, b = topo.get_BoundingBox(None), floor.get_BoundingBox(None)
    if a is not None and b is not None and any(hi1 < lo2 or hi2 < lo1 for lo1,hi1,lo2,hi2 in
            ((a.Min.X,a.Max.X,b.Min.X,b.Max.X),(a.Min.Y,a.Max.Y,b.Min.Y,b.Max.Y),(a.Min.Z,a.Max.Z,b.Min.Z,b.Max.Z))):
        return False
    if not topo.CanBeExcavatedBy(floor.Id):
        return False
    topo.ExcavateBy(floor.Id)
    doc.Regenerate()
    # Nonintersecting regions, including floors outside a concave footprint or
    # inside a hole, can have overlapping bounding boxes but remove no volume.
    return is_excavated(topo, floor.Id)


def is_excavated(topo, element_id):
    data = list(topo.GetIntersectingElementData())
    try:
        return any(d.IntersectionType == DB.IntersectionType.Excavate and
                   element_id in (d.IntersectingElementId, d.IntersectedElementId) for d in data)
    finally:
        for item in data:
            item.Dispose()


def internal_region(region, location):
    def convert(loop):
        return [core.Point(service.metres(p.X), service.metres(p.Y), service.metres(p.Z))
                for p in service.to_internal(loop, location)]
    return geom.Region(convert(region.outer), [convert(h) for h in region.holes])


def shape_key(p):
    return int(round(p.X/service.feet(geom.TOL))), int(round(p.Y/service.feet(geom.TOL)))


def create_one(doc, terrain_surface, region, type_id, level_id):
    floor_type, level = doc.GetElement(type_id), doc.GetElement(level_id)
    if not isinstance(floor_type, DB.FloorType) or floor_type.IsFoundationSlab or not isinstance(level, DB.Level):
        raise ValueError('Escolha um tipo de piso e um nível válidos para as áreas de piso.')
    structure = floor_type.GetCompoundStructure()
    if structure is None:
        raise ValueError('O tipo de piso precisa de uma estrutura com espessura definida.')
    try:
        variable_base = structure.VariableLayerIndex >= 0
    finally:
        structure.Dispose()
    loops, control_points, lines = terrain_surface.constraints(region, allow_outside=True)
    outside_points = 0
    for p in control_points:
        try:
            terrain_surface.height(p)
        except ValueError:
            outside_points += 1
    baseline = min(p.Z for p in control_points)
    profiles = List[DB.CurveLoop]()
    for loop in loops:
        curve_loop = DB.CurveLoop()
        for a, b in geom.edges(loop):
            if service.feet(geom.distance(a, b)) <= doc.Application.ShortCurveTolerance:
                raise ValueError('O contorno encontra uma aresta do terreno com distância menor que a tolerância de curvas do Revit. Ajuste ou divida o contorno do piso no DWG.')
            curve_loop.Append(DB.Line.CreateBound(DB.XYZ(service.feet(a.E), service.feet(a.N), 0),
                                                 DB.XYZ(service.feet(b.E), service.feet(b.N), 0)))
        profiles.Add(curve_loop)
    floor = DB.Floor.Create(doc, profiles, type_id, level_id)
    floor.get_Parameter(DB.BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM).Set(service.feet(baseline)-level.ProjectElevation)
    doc.Regenerate()
    editor = floor.GetSlabShapeEditor()
    try:
        editor.Enable()
        doc.Regenerate()
        existing = {shape_key(v.Position): v for v in editor.SlabShapeVertices}
        for point in control_points:
            xyz = DB.XYZ(service.feet(point.E), service.feet(point.N), service.feet(point.Z))
            vertex = existing.get(shape_key(xyz))
            if vertex is None:
                vertex = editor.AddPoint(xyz)
                if vertex is None:
                    raise ValueError('O Revit não aceitou um ponto de conformação do piso.')
                existing[shape_key(xyz)] = vertex
            else:
                editor.ModifySubElement(vertex, service.feet(point.Z-baseline))
        doc.Regenerate()
        # Impose the terrain's triangulation rather than an unrelated floor TIN.
        existing = {shape_key(v.Position): v for v in editor.SlabShapeVertices}
        def pair(a, b):
            return tuple(sorted((shape_key(a), shape_key(b))))
        imposed = set()
        for crease in editor.SlabShapeCreases:
            ends = list(crease.EndPoints)
            if len(ends) == 2:
                imposed.add(pair(ends[0].Position, ends[1].Position))
        for a, b in lines:
            av = existing[shape_key(DB.XYZ(service.feet(a.E), service.feet(a.N), 0))]
            bv = existing[shape_key(DB.XYZ(service.feet(b.E), service.feet(b.N), 0))]
            key = pair(av.Position, bv.Position)
            if key not in imposed:
                editor.AddSplitLine(av, bv)
                imposed.add(key)
        doc.Regenerate()
    finally:
        editor.Dispose()
    if floor.LevelId != level_id:
        raise ValueError('O Revit alterou o nível associado ao piso. Operação cancelada.')
    # The upper face is the design datum. Never shift it to satisfy the bottom.
    # Variable-layer floor types are valid: Revit may keep their underside flat.
    error = verify_contact(floor, terrain_surface, region)
    return floor, dict(ElementId=str(floor.Id), TypeId=str(type_id),
                       Type=DB.Element.Name.GetValue(floor_type), LevelId=str(level_id), Level=level.Name,
                       AreaSquareMetres=geom.region_area(region), TopElevationToleranceMetres=0.001,
                       MaximumTopErrorMetres=error, ShapePoints=len(control_points),
                       VariableThicknessLayer=variable_base,
                       OutsideControlPoints=outside_points,
                       OutsideElevationReference='Nearest terrain boundary elevation',
                       ContactValidationScope='Upper face against design elevations')


def verify_shape_vertices(floor, reference, controls):
    """Double-precision upper vertices are authoritative when a mesh misses XY."""
    editor = floor.GetSlabShapeEditor()
    try:
        vertices = [v.Position for v in editor.SlabShapeVertices]
    finally:
        editor.Dispose()
    if not vertices:
        raise ValueError('O Revit não disponibilizou os vértices superiores para conferir o piso {0}.'.format(floor.Id))
    buckets = {}
    tolerance = service.feet(0.001)
    def key(x,y):
        return int(round(x/tolerance)),int(round(y/tolerance))
    for vertex in vertices:
        buckets.setdefault(key(vertex.X,vertex.Y),[]).append(vertex)
    maximum = 0.0
    for p in controls:
        px,py = service.feet(p.E),service.feet(p.N)
        x,y = key(px,py)
        matches = [v for xx in range(x-1,x+2) for yy in range(y-1,y+2)
                   for v in buckets.get((xx,yy),[]) if (v.X-px)**2+(v.Y-py)**2 <= tolerance*tolerance]
        if not matches:
            raise ValueError('O Revit não preservou um vértice de controle do piso {0}. Não foi possível conferir sua cota.'.format(floor.Id))
        nearest = min(matches,key=lambda v:(v.X-px)**2+(v.Y-py)**2)
        maximum = max(maximum,abs(service.metres(nearest.Z)-p.Z))
    for v in vertices:
        p = core.Point(service.metres(v.X),service.metres(v.Y),service.metres(v.Z))
        try:
            wanted = reference.height(p)
        except ValueError:
            continue
        maximum = max(maximum,abs(p.Z-wanted))
    if maximum > 0.001:
        raise ValueError('O topo do piso difere das cotas desejadas em {0:.1f} mm.'.format(maximum*1000))
    return maximum


def verify_contact(floor, terrain_surface, region):
    """Validate the UPPER face. Outside terrain coverage is always permitted."""
    _, controls, _ = terrain_surface.constraints(region, allow_outside=True)
    try:
        top = surface(floor, True)
    except SurfaceUnavailable:
        return verify_shape_vertices(floor,terrain_surface,controls)
    maximum = 0.0
    # Piecewise linear surfaces: verify the vertices and crossings of both TINs,
    # plus every bottom triangle centroid. Only measured coverage is checked:
    # the floor may continue beyond the terrain, without surveyed support there.
    # All controls (including exterior ones) must attain their design Z.
    for p in controls:
        try:
            actual = top.height(p)
        except ValueError:
            return verify_shape_vertices(floor,terrain_surface,controls)
        maximum = max(maximum,abs(actual-p.Z))
    samples = [p for t in top.triangles for p in t]
    samples.extend(core.Point(sum(p.E for p in t)/3, sum(p.N for p in t)/3, sum(p.Z for p in t)/3) for t in top.triangles)
    samples.extend(controls)
    for triangle in top.triangles:
        _, crossings, _ = terrain_surface.constraints(geom.Region(list(triangle), []), allow_outside=True)
        samples.extend(crossings)
    for p in samples:
        if not geom.contains(p, region):
            continue
        try:
            wanted = terrain_surface.height(p)
        except ValueError:
            continue
        try:
            actual = top.height(p)
        except ValueError:
            return verify_shape_vertices(floor,terrain_surface,controls)
        maximum = max(maximum, abs(actual-wanted))
    if maximum > 0.001:
        raise ValueError('O topo do piso difere das cotas desejadas em {0:.1f} mm. Toda a criação foi revertida.'.format(maximum*1000))
    return maximum


def create(doc, topo, settings):
    if not settings:
        return []
    terrain_surface = surface(topo)
    reports = []
    settings['Created'] = []
    areas, issues = settings['Areas'], settings['Issues']
    for layer, type_id in settings['Layers']:
        if layer not in areas:
            raise ValueError('Os contornos da camada {0} mudaram. Identifique as áreas novamente.'.format(layer))
        for index, region in enumerate(areas[layer]):
            internal = (settings['InternalAreas'][layer][index] if 'InternalAreas' in settings
                        else internal_region(region, doc.ActiveProjectLocation))
            flags = getattr(areas, 'elevated_regions', {}).get(layer, [False]*len(areas[layer]))
            from_cad = flags[index]
            design = geom.contour_surface(internal) if from_cad else terrain_surface
            floor, report = create_one(doc, design, internal, type_id, settings['LevelId'])
            did_excavate = excavate(doc, topo, floor)
            report.update(Layer=layer, CadId=str(settings['CadId']), Coordinates='WCS' if settings['Original'] else 'Shared',
                          ContactFace='Top', Source='DWG closed contours', Diagnostics=issues,
                          ElevationSource='DWG contour Z' if from_cad else 'Terrain surface (2D DWG)',
                          ExcavatesTerrain=did_excavate)
            if settings.get('RegisterSurvey'):
                report.update(Coordinates='Survey shared coordinates', Registration=areas.registration)
            comment = floor.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if comment is not None and not comment.IsReadOnly:
                comment.Set(json.dumps(dict(Plugin='TOPOBIM', TerrainId=str(topo.Id), **report), ensure_ascii=False))
            reports.append(report)
            settings['Created'].append((floor.Id, internal, design))
    if not reports:
        raise ValueError('Nenhum piso foi criado. Identifique os contornos e selecione os layers de piso na aba Conferência.')
    return reports


def verify_created(doc, topo, settings, reports):
    if not settings:
        return
    for (element_id, region, design), report in zip(settings['Created'], reports):
        floor = doc.GetElement(element_id)
        if floor is None or str(floor.LevelId) != report['LevelId']:
            raise ValueError('O Revit alterou um piso após confirmar a transação. Operação cancelada.')
        report['MaximumTopErrorMetres'] = verify_contact(floor, design, region)
        if report['ExcavatesTerrain'] and not is_excavated(topo, element_id):
            raise ValueError('A escavação do terreno não foi preservada após confirmar a transação.')
        report['VerifiedAfterCommit'] = True
