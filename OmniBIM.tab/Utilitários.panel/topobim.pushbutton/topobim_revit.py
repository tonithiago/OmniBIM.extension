# -*- coding: utf-8 -*-
"""Revit 2026 adapter. All document changes belong to one transaction."""
from __future__ import division, unicode_literals

import json
import math
from collections import namedtuple
from System import DateTimeOffset
from System.Collections.Generic import List
from pyrevit import DB
import topobim_core as core
import topobim_geo as geo

CadPoint = namedtuple('CadPoint', 'point layer')
DEFAULT_LOCATION_NAME = 'Terreno Padrão'


class Choice(object):
    def __init__(self, element):
        self.Id = element.Id
        self.Name = DB.Element.Name.GetValue(element)
        self.Label = '{0} [ID {1}]'.format(self.Name, self.Id)


def choices(doc, element_type):
    return sorted([Choice(e) for e in DB.FilteredElementCollector(doc).OfClass(element_type)],
                  key=lambda e: (e.Name, str(e.Id)))


def feet(metres):
    return DB.UnitUtils.ConvertToInternalUnits(metres, DB.UnitTypeId.Meters)


def metres(value):
    return DB.UnitUtils.ConvertFromInternalUnits(value, DB.UnitTypeId.Meters)


def internal_to_shared(location):
    def shared(point):
        position = location.GetProjectPosition(point)
        try:
            return DB.XYZ(position.EastWest, position.NorthSouth, position.Elevation)
        finally:
            position.Dispose()
    origin = shared(DB.XYZ.Zero)
    transform = DB.Transform.Identity
    transform.Origin = origin
    transform.BasisX = shared(DB.XYZ.BasisX).Subtract(origin)
    transform.BasisY = shared(DB.XYZ.BasisY).Subtract(origin)
    transform.BasisZ = shared(DB.XYZ.BasisZ).Subtract(origin)
    return transform


def to_internal(points, location):
    transform = internal_to_shared(location).Inverse
    return [transform.OfPoint(DB.XYZ(feet(p.E), feet(p.N), feet(p.Z))) for p in points]


def outside_limits(points):
    return any(not DB.XYZ.IsWithinLengthLimits(p) or p.GetLength() > feet(15000)
               for p in points)


def needs_location(doc, analysis):
    # A valid vertical shared offset must NOT trigger a new project location.
    return outside_limits(to_internal(analysis.points, doc.ActiveProjectLocation))


def geographic_settings(doc, settings):
    """Geographic location at the internal origin/base points' XY."""
    if settings['NewLocation']:
        east, north, elevation = settings['East'], settings['North'], settings['Elevation']
    else:
        origin = internal_to_shared(doc.ActiveProjectLocation).Origin
        east, north, elevation = metres(origin.X), metres(origin.Y), metres(origin.Z)
    mode = settings.get('GeographicMode', 'utm')
    if mode == 'manual':
        latitude, longitude = geo.validate_latlon(settings['Latitude'], settings['Longitude'])
    elif mode == 'utm':
        latitude, longitude = geo.utm_to_latlon(east, north, settings['Zone'], settings['Hemisphere'], settings['Datum'])
    else:
        raise ValueError('Modo de localização geográfica inválido.')
    return dict(Latitude=latitude, Longitude=longitude, Mode=mode,
                Reference='Internal origin (base points XY)',
                East=east, North=north, Elevation=elevation, Datum=settings['Datum'])


def use_default_location(doc, settings):
    """Replace the default site's coordinates, without accumulating new sites."""
    previous = doc.ActiveProjectLocation
    locations = list(doc.ProjectLocations)
    target = next((p for p in locations if p.Name == DEFAULT_LOCATION_NAME), None)
    if target is None:
        target = next((p for p in locations if p.Name.strip().upper() == DEFAULT_LOCATION_NAME.upper()), None)
    if target is None:
        target = next((p for p in locations if p.Name.strip().lower() in ('internal', 'default site', 'site padrão')), previous)
    # Capture names/IDs before mutation; even inactive legacy sites must be replaced.
    obsolete = [p for p in locations if p.Id != target.Id and
                (p.Name.strip().upper() == DEFAULT_LOCATION_NAME.upper() or
                 p.Name.strip().upper().startswith('TOPOBIM '))]
    if settings['NewLocation']:
        position = DB.ProjectPosition(feet(settings['East']), feet(settings['North']), feet(settings['Elevation']), 0)
    else:
        # Copy rotation and vertical offset from the active site, not the old default.
        position = previous.GetProjectPosition(DB.XYZ.Zero)
    try:
        target.SetProjectPosition(DB.XYZ.Zero, position)
    finally:
        position.Dispose()
    target.Name = DEFAULT_LOCATION_NAME
    doc.ActiveProjectLocation = target
    doc.Regenerate()
    # Clean up all older TOPOBIM sites, including those accumulated by old versions.
    # The active transform was copied above before removing its old site.
    for old in obsolete:
        allowed_ids = [old.Id, old.GetSiteLocation().Id]
        deleted = doc.Delete(old.Id)
        if any(element_id not in allowed_ids for element_id in deleted):
            raise ValueError('A localização TOPOBIM está associada a outros elementos. A substituição foi cancelada para preservá-los.')
        doc.Regenerate()
    return target


def align_base_points(doc, target_position=None):
    """Move the markers, not the shared coordinate system or the terrain."""
    before = internal_to_shared(doc.ActiveProjectLocation)
    target_position = target_position if target_position is not None else DB.XYZ.Zero
    project = DB.BasePoint.GetProjectBasePoint(doc)
    survey = DB.BasePoint.GetSurveyPoint(doc)
    if project is None or survey is None:
        raise ValueError('Não foi possível obter os pontos base do projeto e de levantamento.')
    for base in (project, survey):
        pinned = base.Pinned
        clipped = base.Clipped if base.IsShared else False
        try:
            if pinned:
                base.Pinned = False
            if base.IsShared and clipped:
                base.Clipped = False
            delta = target_position.Subtract(base.Position)
            if delta.GetLength() > feet(0.000001):
                DB.ElementTransformUtils.MoveElement(doc, base.Id, delta)
            doc.Regenerate()
        finally:
            if base.IsShared and clipped:
                base.Clipped = clipped
            if pinned:
                base.Pinned = True
    doc.Regenerate()
    return verify_base_points(doc, before, target_position)


def verify_base_points(doc, reference_transform=None, target_position=None):
    """Read fresh positions, including after Commit, rather than trusting a move."""
    project = DB.BasePoint.GetProjectBasePoint(doc)
    survey = DB.BasePoint.GetSurveyPoint(doc)
    if project is None or survey is None:
        raise ValueError('Não foi possível conferir os dois pontos base.')
    tolerance = feet(0.000001)
    target_position = target_position if target_position is not None else DB.XYZ.Zero
    if reference_transform is not None:
        after = internal_to_shared(doc.ActiveProjectLocation)
        for probe in (DB.XYZ.Zero, DB.XYZ.BasisX, DB.XYZ.BasisY, DB.XYZ.BasisZ):
            if reference_transform.OfPoint(probe).DistanceTo(after.OfPoint(probe)) > tolerance:
                raise ValueError('Mover os pontos base alterou a referência compartilhada. Operação cancelada.')
    project_position, survey_position = project.Position, survey.Position
    separation = project_position.DistanceTo(survey_position)
    if (project_position.DistanceTo(target_position) > tolerance or
            survey_position.DistanceTo(target_position) > tolerance or separation > tolerance or
            project.SharedPosition.DistanceTo(survey.SharedPosition) > tolerance):
        raise ValueError('Os pontos base não ficaram coincidentes (distância: {0:.6f} m). Operação cancelada.'.format(metres(separation)))
    return dict(ProjectBasePointId=str(project.Id), SurveyPointId=str(survey.Id),
                InternalPosition=[metres(project_position.X), metres(project_position.Y), metres(project_position.Z)],
                SurveyInternalPosition=[metres(survey_position.X), metres(survey_position.Y), metres(survey_position.Z)],
                SeparationMetres=metres(separation),
                SharedPositionMetres=[metres(project.SharedPosition.X),
                                      metres(project.SharedPosition.Y), metres(project.SharedPosition.Z)])


def set_site_geography(doc, geographic):
    site = doc.SiteLocation
    site.Latitude = math.radians(geographic['Latitude'])
    site.Longitude = math.radians(geographic['Longitude'])
    doc.Regenerate()
    if (abs(site.Latitude - math.radians(geographic['Latitude'])) > 1e-10 or
            abs(site.Longitude - math.radians(geographic['Longitude'])) > 1e-10):
        raise ValueError('O Revit não preservou a latitude/longitude informada. Operação cancelada.')
    geographic['TimeZoneHours'] = site.TimeZone
    return geographic


def read_cad(doc, element_id, original_coordinates=True):
    cad = doc.GetElement(element_id)
    if not isinstance(cad, DB.ImportInstance):
        raise ValueError('Selecione um DWG do projeto.')
    if cad.ViewSpecific:
        raise ValueError("O DWG está restrito à vista. Vincule-o com 'Somente vista atual' desmarcado.")
    transform_out = (cad.GetTransform().Inverse if original_coordinates
                     else internal_to_shared(doc.ActiveProjectLocation))
    output = []

    def add(point, layer):
        q = transform_out.OfPoint(point)
        output.append(CadPoint(core.Point(metres(q.X), metres(q.Y), metres(q.Z)), layer))
        if len(output) > core.MAX_INPUT:
            raise ValueError('O DWG excede 100.000 vértices. Simplifique o arquivo.')

    def walk(geometry, transform, inherited_layer):
        for obj in geometry:
            layer = inherited_layer
            style = doc.GetElement(obj.GraphicsStyleId)
            if isinstance(style, DB.GraphicsStyle) and style.GraphicsStyleCategory is not None:
                layer = style.GraphicsStyleCategory.Name
            if isinstance(obj, DB.GeometryInstance):
                symbol_geometry = obj.GetSymbolGeometry()
                if symbol_geometry is not None:
                    walk(symbol_geometry, transform.Multiply(obj.Transform), layer)
            elif isinstance(obj, DB.PolyLine):
                for point in obj.GetCoordinates():
                    add(transform.OfPoint(point), layer)
            elif isinstance(obj, DB.Curve):
                for point in obj.Tessellate():
                    add(transform.OfPoint(point), layer)
            elif isinstance(obj, DB.Point):
                add(transform.OfPoint(obj.Coord), layer)
            elif isinstance(obj, DB.Mesh):
                for point in obj.Vertices:
                    add(transform.OfPoint(point), layer)
    options = DB.Options()
    options.IncludeNonVisibleObjects = True
    options.DetailLevel = DB.ViewDetailLevel.Fine
    try:
        geometry = cad.get_Geometry(options)
        if geometry is None:
            raise ValueError('O DWG não disponibilizou geometria.')
        walk(geometry, DB.Transform.Identity, 'Sem camada')
    finally:
        options.Dispose()
    if not output:
        raise ValueError('Não foram encontrados pontos, curvas ou malhas. Converta proxies Civil 3D em geometria CAD comum.')
    return output


def match_surface(topo, expected):
    tolerance = feet(0.001)
    editor = topo.GetSlabShapeEditor()
    try:
        vertices = [v.Position for v in editor.SlabShapeVertices]
    finally:
        editor.Dispose()
    if not vertices:
        raise ValueError('Não foi possível conferir os vértices da superfície criada.')

    def key(point):
        return int(math.floor(point.X / tolerance)), int(math.floor(point.Y / tolerance))
    buckets = {}
    for vertex in vertices:
        buckets.setdefault(key(vertex), []).append(vertex)
    matches = []
    for point in expected:
        px, py = key(point)
        nearest, best = None, tolerance * tolerance
        for x in range(px - 1, px + 2):
            for y in range(py - 1, py + 2):
                for candidate in buckets.get((x, y), []):
                    distance = (candidate.X - point.X) ** 2 + (candidate.Y - point.Y) ** 2
                    if distance <= best:
                        best, nearest = distance, candidate
        if nearest is None:
            raise ValueError('Um ponto do levantamento não foi preservado na superfície. Criação cancelada.')
        matches.append((point, nearest))
    return matches


def preserve_elevations(doc, topo, expected):
    tolerance = feet(0.001)
    matches = match_surface(topo, expected)
    correction = matches[0][0].Z - matches[0][1].Z
    if any(abs((wanted.Z - actual.Z) - correction) > tolerance for wanted, actual in matches):
        raise ValueError('A superfície alterou os desníveis do levantamento. Criação cancelada.')
    if abs(correction) > feet(0.000001):
        DB.ElementTransformUtils.MoveElement(doc, topo.Id, DB.XYZ(0, 0, correction))
        doc.Regenerate()
    matches = match_surface(topo, expected)
    if any(abs(wanted.Z - actual.Z) > tolerance for wanted, actual in matches):
        raise ValueError('As cotas da superfície diferem do levantamento em mais de 1 mm. Criação cancelada.')
    return matches


def surface_base_point(topo):
    """Actual upper surface above the internal origin's XY, not its zero Z.

    The newly created Toposolid has planar triangulated faces. Intersect their
    triangles vertically and take the upper envelope, excluding the lower face
    and any vertical sides, independently of type thickness/reference level.
    """
    highest = [None]

    def read_mesh(mesh, transform):
        for index in range(mesh.NumTriangles):
            triangle = mesh.get_Triangle(index)
            vertices = [transform.OfPoint(triangle.get_Vertex(i)) for i in range(3)]
            points = [core.Point(p.X, p.Y, p.Z) for p in vertices]
            height = core.triangle_height(0.0, 0.0, *points)
            if height is not None and (highest[0] is None or height > highest[0]):
                highest[0] = height

    def walk(geometry, transform):
        for obj in geometry:
            if isinstance(obj, DB.GeometryInstance):
                nested = obj.GetSymbolGeometry()
                if nested is not None:
                    walk(nested, transform.Multiply(obj.Transform))
            elif isinstance(obj, DB.Solid):
                for face in obj.Faces:
                    mesh = face.Triangulate()
                    try:
                        read_mesh(mesh, transform)
                    finally:
                        mesh.Dispose()
            elif isinstance(obj, DB.Mesh):
                read_mesh(obj, transform)
    options = DB.Options()
    options.DetailLevel = DB.ViewDetailLevel.Fine
    try:
        geometry = topo.get_Geometry(options)
        if geometry is not None:
            try:
                walk(geometry, DB.Transform.Identity)
            finally:
                geometry.Dispose()
    finally:
        options.Dispose()
    if highest[0] is None:
        raise ValueError('A posição em planta dos pontos base está fora do terreno. Em Criação, defina Este/Norte da origem próximos do centro do levantamento para colocar os pontos sobre a superfície.')
    return DB.XYZ(0.0, 0.0, highest[0])


def create_review_view(doc, terrain, floor_ids):
    """A result view avoids the floor plan's unrelated level/view-range limits.

    Called inside the creation transaction, so the view shares the same Undo.
    """
    view_type = next((t for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                      if t.ViewFamily == DB.ViewFamily.ThreeDimensional), None)
    if view_type is None:
        return None
    view = DB.View3D.CreateIsometric(doc,view_type.Id)
    view.Name = 'TOPOBIM - terreno e pisos {0}'.format(terrain.Id)
    view.ViewTemplateId = DB.ElementId.InvalidElementId
    view.DetailLevel = DB.ViewDetailLevel.Fine
    view.DisplayStyle = DB.DisplayStyle.ShadingWithEdges
    view.AreImportCategoriesHidden = True
    view.AreAnnotationCategoriesHidden = True
    for category in (DB.BuiltInCategory.OST_Floors,DB.BuiltInCategory.OST_Toposolid):
        category_id = DB.ElementId(category)
        if view.CanCategoryBeHidden(category_id):
            view.SetCategoryHidden(category_id,False)
    keep_ids = set([terrain.Id]+list(floor_ids))
    hidden = List[DB.ElementId]()
    for kind in (DB.Floor,DB.Toposolid):
        for other in DB.FilteredElementCollector(doc).OfClass(kind):
            if other.Id not in keep_ids and other.CanBeHidden(view):
                hidden.Add(other.Id)
    if hidden.Count:
        view.HideElements(hidden)
    boxes = [e.get_BoundingBox(None) for e in [terrain]+[doc.GetElement(i) for i in floor_ids]]
    boxes = [b for b in boxes if b is not None]
    if boxes:
        margin = feet(2)
        section = DB.BoundingBoxXYZ()
        section.Min = DB.XYZ(min(b.Min.X for b in boxes)-margin,min(b.Min.Y for b in boxes)-margin,min(b.Min.Z for b in boxes)-margin)
        section.Max = DB.XYZ(max(b.Max.X for b in boxes)+margin,max(b.Max.Y for b in boxes)+margin,max(b.Max.Z for b in boxes)+margin)
        view.SetSectionBox(section)
        view.IsSectionBoxActive = True
    return view.Id


def show_review_view(uidoc,view_id):
    """Switch only after ShowDialog has returned to the external command."""
    from System import Int64
    view = uidoc.Document.GetElement(DB.ElementId(Int64.Parse(str(view_id))))
    if view is None:
        raise ValueError('A vista 3D de conferência não está mais disponível.')
    uidoc.ActiveView = view
    uidoc.RefreshActiveView()
    for opened in uidoc.GetOpenUIViews():
        if opened.ViewId == view.Id:
            opened.ZoomToFit()
            break


def create(doc, analysis, type_id, level_id, settings, source, floor_settings=None):
    core.validate_analysis(analysis)
    if not isinstance(doc.GetElement(type_id), DB.ToposolidType) or not isinstance(doc.GetElement(level_id), DB.Level):
        raise ValueError('Selecione um tipo de sólido topográfico e um nível válidos.')
    if not settings['Datum'].strip() or not 1 <= settings['Zone'] <= 60:
        raise ValueError('Informe datum e zona UTM de 1 a 60.')
    if settings['Hemisphere'] not in ('Sul', 'Norte'):
        raise ValueError('Hemisfério inválido.')
    if not all(core.finite(settings[k]) for k in ('East', 'North', 'Elevation')):
        raise ValueError('Coordenada de origem não finita.')
    geographic = geographic_settings(doc, settings)
    if floor_settings:
        import topobim_floors
        floor_settings = topobim_floors.prepare(doc, floor_settings)
    group = DB.TransactionGroup(doc, 'TOPOBIM - criar terreno')
    transaction = DB.Transaction(doc, 'TOPOBIM - criar terreno')
    try:
        if group.Start() != DB.TransactionStatus.Started:
            raise ValueError('Não foi possível iniciar a operação do terreno.')
        if transaction.Start() != DB.TransactionStatus.Started:
            raise ValueError('Não foi possível iniciar a transação.')
        failure_options = transaction.GetFailureHandlingOptions()
        failure_options.SetClearAfterRollback(True)
        failure_options.SetForcedModalHandling(True)
        transaction.SetFailureHandlingOptions(failure_options)
        use_default_location(doc, settings)
        points = to_internal(analysis.points, doc.ActiveProjectLocation)
        if outside_limits(points):
            raise ValueError('O terreno está fora dos limites ou a mais de 15 km da origem interna. Confira unidades, colunas e coordenadas da nova localização.')
        set_site_geography(doc, geographic)
        net_points = List[DB.XYZ]()
        for point in points:
            net_points.Add(point)
        topo = DB.Toposolid.Create(doc, net_points, type_id, level_id)
        doc.Regenerate()
        matches = preserve_elevations(doc, topo, points)
        transform = internal_to_shared(doc.ActiveProjectLocation)
        # Check actual surface positions, including extrema, in shared coordinates.
        for original, pair in zip(analysis.points, matches):
            actual = transform.OfPoint(pair[1])
            if (abs(metres(actual.X) - original.E) > 0.002 or
                    abs(metres(actual.Y) - original.N) > 0.002 or
                    abs(metres(actual.Z) - original.Z) > 0.001):
                raise ValueError('Falha na conferência da superfície em coordenadas compartilhadas.')
        # Capture survey elevation before excavation can remove this topo face.
        target_position = surface_base_point(topo)
        floor_reports = []
        if floor_settings:
            import topobim_floors
            floor_reports = topobim_floors.create(doc, topo, floor_settings)
        # Align last: site activation, geographic data and surface corrections are done.
        base_points = align_base_points(doc, target_position)
        review_view_id = create_review_view(doc,topo,[entry[0] for entry in floor_settings['Created']]) if floor_reports else None
        reference_transform = internal_to_shared(doc.ActiveProjectLocation)
        now = str(DateTimeOffset.Now.ToString('o'))
        report = dict(Version='0.8.3-pyrevit', Revit=doc.Application.VersionNumber,
                      Date=now, Source=source, ElementId=str(topo.Id),
                      Location=doc.ActiveProjectLocation.Name, Settings=dict(settings),
                      Points=len(analysis.points), Duplicates=analysis.duplicates,
                      Errors=[], Conflicts=list(analysis.conflicts), Boundary='Convex hull',
                      Reprojection=False, ElevationToleranceMetres=0.001,
                      GeographicLocation=geographic, BasePoints=base_points, Floors=floor_reports,
                      ReviewViewId=str(review_view_id) if review_view_id is not None else None)
        comment = topo.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if comment is not None and not comment.IsReadOnly:
            comment.Set(json.dumps(dict(Plugin='TOPOBIM 0.8.3-pyrevit', Source=source,
                                       Datum=settings['Datum'], Zone=settings['Zone'],
                                       Hemisphere=settings['Hemisphere'], Points=len(points),
                                       Boundary='Convex hull', CRSConversion=False,
                                       Latitude=geographic['Latitude'], Longitude=geographic['Longitude'],
                                       Location=DEFAULT_LOCATION_NAME,
                                       BasePointElevation=base_points['SharedPositionMetres'][2],
                                       Elevations='Cotas verificadas; tolerância 1 mm'), ensure_ascii=False))
        element_id = topo.Id
        if transaction.Commit() != DB.TransactionStatus.Committed:
            raise ValueError('O Revit não confirmou a criação do sólido.')
        if floor_settings:
            topobim_floors.verify_created(doc, doc.GetElement(element_id), floor_settings, floor_reports)
        # Commit can run additional Revit updates. Read both markers again and keep
        # the whole operation reversible until this final check has passed.
        report['BasePoints'] = verify_base_points(doc, reference_transform, target_position)
        report['BasePoints']['ElevationReference'] = 'Actual Toposolid upper surface at base points XY'
        report['BasePoints']['VerifiedAfterCommit'] = True
        if group.Assimilate() != DB.TransactionStatus.Committed:
            raise ValueError('O Revit não confirmou a operação completa do terreno.')
        return element_id, report
    except Exception:
        if transaction.GetStatus() == DB.TransactionStatus.Started:
            transaction.RollBack()
        if group.GetStatus() == DB.TransactionStatus.Started:
            group.RollBack()
        raise
    finally:
        transaction.Dispose()
        group.Dispose()
