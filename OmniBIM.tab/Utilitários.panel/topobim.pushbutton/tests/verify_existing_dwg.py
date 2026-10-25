# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import os,sys,json,traceback,imp
from System import Int64
from System.IO import File
from System.Collections.Generic import List
from pyrevit import revit,DB,HOST_APP
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,ROOT)
qa=imp.load_source('topobim_real_floor_qa',os.path.join(ROOT,'tests','verify_floors_revit.py'))
import topobim_floors as floors
import topobim_floor_geometry as geom
import topobim_revit as service

def meta(e):
    p=e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    try:return json.loads(p.AsString()) if p else {}
    except Exception:return {}
def idof(s):return DB.ElementId(Int64.Parse(str(s)))
source=revit.doc
pairs=[(e,meta(e)) for e in DB.FilteredElementCollector(source).OfClass(DB.Floor)]
pairs=[(e,m) for e,m in pairs if m.get('Plugin')=='TOPOBIM']
terrain_id=max(int(m['TerrainId']) for e,m in pairs)
batch=[(e,m) for e,m in pairs if int(m['TerrainId'])==terrain_id]
source_topo=source.GetElement(idof(terrain_id))
if globals().get('SURVEY_POINTS'):
    areas,issues=floors.read_registered_areas(source,idof(batch[0][1]['CadId']),SURVEY_POINTS)
else:
    areas,issues=floors.read_areas(source,idof(batch[0][1]['CadId']),False)
layers=sorted(set(m['Layer'] for e,m in batch))
regions=[(layer,index,floors.internal_region(region,source.ActiveProjectLocation)) for layer in layers for index,region in enumerate(areas[layer])]
reference=floors.surface(source_topo)
editor=source_topo.GetSlabShapeEditor()
try:points=List[DB.XYZ]([v.Position for v in editor.SlabShapeVertices])
finally:editor.Dispose()
result=dict(Status='STARTED',SourceTerrainId=str(terrain_id),Count=0,Areas=[])
if hasattr(areas,'registration'):
    result['Registration']=areas.registration
doc=None
group=None
try:
    doc=HOST_APP.app.NewProjectDocument(DB.UnitSystem.Metric)
    group=DB.TransactionGroup(doc,'TOPOBIM QA actual CAD geometry')
    group.Start()
    setup=DB.Transaction(doc,'TOPOBIM QA setup')
    setup.Start()
    level=DB.Level.Create(doc,0)
    topo_type=next(iter(DB.FilteredElementCollector(doc).OfClass(DB.ToposolidType)))
    floor_type=next(iter(DB.FilteredElementCollector(doc).OfClass(DB.FloorType)))
    cs=floor_type.GetCompoundStructure()
    try:
        cs.SetLayerWidth(0,service.feet(0.15))
        floor_type.SetCompoundStructure(cs)
    finally:cs.Dispose()
    topo=DB.Toposolid.Create(doc,points,topo_type.Id,level.Id)
    doc.Regenerate()
    service.preserve_elevations(doc,topo,list(points))
    setup.Commit()
    for layer,index,region in regions:
        result['CurrentArea']=dict(Layer=layer,Index=index)
        transaction=DB.Transaction(doc,'TOPOBIM QA '+layer+str(index))
        transaction.Start()
        warnings=qa.TemporaryWarnings()
        options=transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(warnings)
        options.SetClearAfterRollback(True)
        options.SetForcedModalHandling(True)
        transaction.SetFailureHandlingOptions(options)
        try:
            design=geom.contour_surface(region) if areas.elevated_regions[layer][index] else reference
            floor,report=floors.create_one(doc,design,region,floor_type.Id,level.Id)
            report['Excavation']=floors.excavate(doc,topo,floor)
            if transaction.Commit()!=DB.TransactionStatus.Committed:raise ValueError('QA commit failed')
            report['AfterCommitErrorMetres']=floors.verify_contact(doc.GetElement(floor.Id),design,region)
            report.update(Layer=layer,Index=index,Warnings=warnings.messages)
            result['Areas'].append(report)
            result['Count']+=1
        finally:
            if transaction.GetStatus()==DB.TransactionStatus.Started:transaction.RollBack()
            transaction.Dispose()
    result['Status']='OK'
except Exception:
    detail=traceback.format_exc()
    if isinstance(detail,str):detail=detail.decode('utf-8','replace')
    result.update(Status='FAILED',Error=detail)
finally:
    if group is not None:
        group.RollBack()
        group.Dispose()
    if doc is not None:doc.Close(False)
    File.WriteAllText(os.path.join(os.environ['LOCALAPPDATA'],'Temp','omnibim-topobim-qa','real-floor-geometry-result.json'),json.dumps(result,ensure_ascii=False,default=unicode,indent=2))
print('Actual CAD geometry test: {0}, {1} floors'.format(result['Status'],result['Count']))
