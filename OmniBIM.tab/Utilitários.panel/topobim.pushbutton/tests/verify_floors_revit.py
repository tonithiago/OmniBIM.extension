# -*- coding: utf-8 -*-
"""Native API QA. Creates an independent unsaved document; always closes it."""
from __future__ import division, unicode_literals
import os
import sys
import json
import traceback
from System.Collections.Generic import List
from System.IO import File
from pyrevit import DB, HOST_APP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import topobim_core as core
import topobim_revit as service
import topobim_floor_geometry as geom
import topobim_floors as floors
reload(geom)
reload(floors)


class TemporaryWarnings(DB.IFailuresPreprocessor):
    def __init__(self):
        self.messages = []

    def PreprocessFailures(self, accessor):
        for message in accessor.GetFailureMessages():
            if message.GetSeverity() == DB.FailureSeverity.Warning:
                self.messages.append(message.GetDescriptionText())
                accessor.DeleteWarning(message)
        return DB.FailureProcessingResult.Continue


def run():
    doc = HOST_APP.app.NewProjectDocument(DB.UnitSystem.Metric)
    results = []
    try:
        types = floors.floor_choices(doc)
        floor_type = next(doc.GetElement(t.Id) for t in types
                          if doc.GetElement(t.Id).GetCompoundStructure().VariableLayerIndex < 0)
        topo_type = next(iter(DB.FilteredElementCollector(doc).OfClass(DB.ToposolidType)))
        for case in ('slope', 'hill', 'hole', 'thick', 'variable', 'dwg_z', 'outside', 'external_10km'):
            group = DB.TransactionGroup(doc, 'TOPOBIM QA isolated case')
            group.Start()
            transaction = DB.Transaction(doc, 'TOPOBIM QA ' + case)
            transaction.Start()
            warnings = TemporaryWarnings()
            options = transaction.GetFailureHandlingOptions()
            options.SetFailuresPreprocessor(warnings)
            transaction.SetFailureHandlingOptions(options)
            try:
                selected_type = floor_type
                if case in ('thick','variable'):
                    selected_type = floor_type.Duplicate('TOPOBIM QA ' + case)
                    cs = selected_type.GetCompoundStructure()
                    try:
                        cs.SetLayerWidth(0, service.feet(0.3))
                        if case == 'variable':
                            cs.VariableLayerIndex = 0
                        selected_type.SetCompoundStructure(cs)
                    finally:
                        cs.Dispose()
                level = DB.Level.Create(doc, service.feet(-4 if case == 'thick' else 3))
                values = [(-10,-10,10), (10,-10,11), (10,10,12), (-10,10,11)]
                if case != 'slope':
                    values.append((0,0,13))
                points = [DB.XYZ(service.feet(x), service.feet(y), service.feet(z)) for x,y,z in values]
                topo = DB.Toposolid.Create(doc, List[DB.XYZ](points), topo_type.Id, level.Id)
                doc.Regenerate()
                service.preserve_elevations(doc, topo, points)
                upper = floors.surface(topo)
                outer = [core.Point(x,y,0) for x,y in [(-6,-5), (7,-5), (7,6), (-6,6)]]
                holes = [[core.Point(x,y,0) for x,y in [(-1,-1), (-1,1), (1,1), (1,-1)]]] if case == 'hole' else []
                if case == 'outside':
                    outer = [core.Point(x,y,0) for x,y in [(-12,-12),(12,-12),(12,12),(-12,12)]]
                if case == 'external_10km':
                    outer = [core.Point(10000+x,-200+y,0) for x,y in [(-6,-5),(7,-5),(7,6),(-6,6)]]
                design = upper
                if case == 'dwg_z':
                    outer = [core.Point(p.E,p.N,10.5+p.E*0.01) for p in outer]
                    design = geom.contour_surface(geom.Region(outer,holes))
                try:
                    floor, report = floors.create_one(doc, design, geom.Region(outer, holes), selected_type.Id, level.Id)
                except Exception:
                    debug = [(str(f.Id), floors.surface(f, False).triangles) for f in DB.FilteredElementCollector(doc).OfClass(DB.Floor)]
                    File.WriteAllText(os.path.join(os.environ['LOCALAPPDATA'], 'Temp', 'omnibim-topobim-qa', 'floors-debug.txt'), unicode(dict(Case=case, Bottom=debug)))
                    raise
                assert floor.LevelId == level.Id
                assert report['MaximumTopErrorMetres'] <= 0.001
                report['Excavation'] = floors.excavate(doc,topo,floor)
                if case == 'slope':
                    view_id=service.create_review_view(doc,topo,[floor.Id])
                    view=doc.GetElement(view_id)
                    assert isinstance(view,DB.View3D)
                    assert not view.AreModelCategoriesHidden
                    assert view.IsSectionBoxActive
                    report['ReviewViewId']=str(view_id)
                if case not in ('outside','external_10km'):
                    assert report['Excavation']
                if case == 'external_10km':
                    assert not report['Excavation']
                assert transaction.Commit() == DB.TransactionStatus.Committed
                floor = doc.GetElement(floor.Id)
                report['AfterCommitErrorMetres'] = floors.verify_contact(floor, design, geom.Region(outer,holes))
                if report['Excavation']:
                    assert floors.is_excavated(doc.GetElement(topo.Id),floor.Id)
                report['RevitWarnings'] = warnings.messages
                assert floor.LevelId == level.Id
                report['Case'] = case
                results.append(report)
                File.WriteAllText(os.path.join(os.environ['LOCALAPPDATA'], 'Temp', 'omnibim-topobim-qa', 'floors-progress.txt'), unicode(results))
            finally:
                if transaction.GetStatus() == DB.TransactionStatus.Started:
                    transaction.RollBack()
                transaction.Dispose()
                group.RollBack()
                group.Dispose()
    finally:
        doc.Close(False)
    return results


if __name__ == '__main__':
    target = os.path.join(os.environ['LOCALAPPDATA'], 'Temp', 'omnibim-topobim-qa', 'floors-native-result.json')
    if not os.path.isdir(os.path.dirname(target)):
        os.makedirs(os.path.dirname(target))
    try:
        result = dict(Status='OK', Results=run())
    except Exception:
        detail = traceback.format_exc()
        if isinstance(detail, str):
            detail = detail.decode('utf-8', 'replace')
        result = dict(Status='FAILED', Error=detail)
    File.WriteAllText(target + '.txt', unicode(result))
    # The embedded shell can load an older json module with non-ASCII issues.
    File.WriteAllText(target, json.dumps(result, ensure_ascii=False, indent=2, default=unicode))
    print(result)
