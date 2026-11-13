# -*- coding: utf-8 -*-
"""Link a supplied DWG into an unsaved QA document and verify WCS recovery.

Run via pyrevit run --revit=2026 with TOPOBIM_CAD_QA_DWG, _ROOT and _OUTPUT
environment variables. The source DWG is read only; the QA project is discarded.
"""
from __future__ import unicode_literals
import os
import sys
import json
import traceback
from System.IO import File

result = dict(Status='STARTED')
doc = None
try:
    import clr
    sys.path.insert(0, os.path.join(os.environ['APPDATA'], 'pyRevit-Master', 'pyrevitlib'))
    from pyrevit import DB, HOST_APP
    sys.path.insert(0, os.environ['TOPOBIM_CAD_QA_ROOT'])
    import topobim_revit as service
    import topobim_core as core

    def bounds(rows):
        points = [r.point for r in rows]
        return dict(Count=len(points), Min=[min(p[i] for p in points) for i in range(3)],
                    Max=[max(p[i] for p in points) for i in range(3)]) if points else dict(Count=0)

    def transform(t):
        return dict(Origin=[t.Origin.X, t.Origin.Y, t.Origin.Z], Scale=t.Scale)

    def location_state():
        position = doc.ActiveProjectLocation.GetProjectPosition(DB.XYZ.Zero)
        try:
            markers = [DB.BasePoint.GetProjectBasePoint(doc), DB.BasePoint.GetSurveyPoint(doc)]
            return [position.EastWest, position.NorthSouth, position.Elevation,
                    position.Angle, doc.SiteLocation.Latitude, doc.SiteLocation.Longitude,
                    doc.ActiveProjectLocation.Id.Value,
                    DB.FilteredElementCollector(doc).GetElementCount(),
                    [[m.Position.X, m.Position.Y, m.Position.Z, m.Pinned] for m in markers]]
        finally:
            position.Dispose()

    doc = HOST_APP.app.NewProjectDocument(DB.UnitSystem.Metric)
    transaction = DB.Transaction(doc, 'TOPOBIM QA CAD units')
    transaction.Start()
    try:
        level = DB.Level.Create(doc, 0)
        view_type = next(t for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                         if t.ViewFamily == DB.ViewFamily.FloorPlan)
        view = DB.ViewPlan.Create(doc, view_type.Id, level.Id)
        options = DB.DWGImportOptions()
        options.Unit = DB.ImportUnit.Meter
        options.Placement = DB.ImportPlacement.Centered
        options.ThisViewOnly = False
        cad_id = clr.Reference[DB.ElementId]()
        try:
            if not doc.Link(os.environ['TOPOBIM_CAD_QA_DWG'], options, view, cad_id):
                raise ValueError('DWG import failed')
        finally:
            options.Dispose()
        doc.Regenerate()
        transaction.Commit()
    finally:
        if transaction.GetStatus() == DB.TransactionStatus.Started:
            transaction.RollBack()
        transaction.Dispose()
    cad = doc.GetElement(cad_id.Value)
    result['Transform'] = transform(cad.GetTransform())
    result['TotalTransform'] = transform(cad.GetTotalTransform())
    result['IsLinked'] = cad.IsLinked
    acquire = DB.Transaction(doc, 'TOPOBIM QA acquire and rollback')
    acquire.Start()
    try:
        doc.AcquireCoordinates(cad.Id)
        doc.Regenerate()
        result['Acquired'] = bounds(service.read_cad(doc, cad.Id, False))
    except Exception:
        result['AcquireError'] = traceback.format_exc()
    finally:
        acquire.RollBack()
        acquire.Dispose()
    options = DB.Options()
    options.IncludeNonVisibleObjects = True
    geometry = cad.get_Geometry(options)
    try:
        result['GeometryInstances'] = [transform(g.Transform) for g in geometry if isinstance(g, DB.GeometryInstance)]
    finally:
        geometry.Dispose()
        options.Dispose()
    corrected_transform = service.cad_to_original_feet
    try:
        service.cad_to_original_feet = lambda instance: instance.GetTransform().Inverse
        result['LegacyWCS'] = bounds(service.read_cad(doc, cad.Id, True))
    finally:
        service.cad_to_original_feet = corrected_transform
    initial_state = location_state()
    for original in (True, False):
        rows = service.read_cad(doc, cad.Id, original)
        result['WCS' if original else 'Shared'] = dict(
            Bounds=bounds(rows), Layers={layer: bounds([r for r in rows if r.layer == layer])
                                        for layer in sorted(set(r.layer for r in rows))})
        if original:
            analysis = core.analyze([r.point for r in rows])
            settings = dict(NewLocation=False, East=0, North=0, Elevation=0,
                            GeographicMode='utm', Zone=22, Hemisphere='Sul', Datum='SIRGAS 2000')
            recovered = service.automatic_utm_settings(doc, analysis, settings)
            result['Geography'] = service.geographic_settings(doc, recovered or settings)
    assert location_state() == initial_state, 'Reading changed project coordinates or elements'
    result['ReadPreservedProject'] = True
    assert result['WCS']['Bounds'] == result['Acquired'], 'WCS differs from native acquisition'

    acquire = DB.Transaction(doc, 'TOPOBIM QA already acquired coordinates')
    acquire.Start()
    try:
        doc.AcquireCoordinates(cad.Id)
        doc.Regenerate()
        acquire.Commit()
    finally:
        acquire.Dispose()
    acquired_state = location_state()
    result['AlreadyAcquiredWCS'] = bounds(service.read_cad(doc, cad.Id, True))
    assert result['AlreadyAcquiredWCS'] == result['Acquired'], 'Already acquired WCS changed'
    assert location_state() == acquired_state, 'Retry changed project coordinates or elements'
    result['RetryPreservedProject'] = True
    outer = DB.Transaction(doc, 'TOPOBIM QA read during creation')
    outer.Start()
    try:
        result['NestedWCS'] = bounds(service.read_cad(doc, cad.Id, True))
        assert result['NestedWCS'] == result['Acquired'], 'Nested transaction WCS changed'
        assert location_state() == acquired_state, 'Nested read changed project state'
        assert doc.IsModifiable, 'Reading ended the caller transaction'
        result['NestedReadPreservedProject'] = True
    finally:
        outer.RollBack()
        outer.Dispose()
    result['Status'] = 'OK'
except Exception:
    result.update(Status='FAILED', Error=traceback.format_exc())
finally:
    if doc is not None:
        doc.Close(False)
    File.WriteAllText(os.environ['TOPOBIM_CAD_QA_OUTPUT'], json.dumps(result, ensure_ascii=False, indent=2))
