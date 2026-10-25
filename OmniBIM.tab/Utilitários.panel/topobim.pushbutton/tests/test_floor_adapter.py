# -*- coding: utf-8 -*-
"""CAD traversal contracts using a simulated API; not a native DWG test."""
from __future__ import division, unicode_literals
import sys
import types
import unittest
from test_site_adapter import Record, XYZ, Geometry, Location, Position, load_adapter


class Transform(object):
    def __init__(self, x=0,y=0,z=0):
        self.Origin = XYZ(x,y,z)
        self.BasisX,self.BasisY,self.BasisZ=XYZ.BasisX,XYZ.BasisY,XYZ.BasisZ

    def OfVector(self,p):
        return XYZ(p.X*self.BasisX.X+p.Y*self.BasisY.X+p.Z*self.BasisZ.X,
                   p.X*self.BasisX.Y+p.Y*self.BasisY.Y+p.Z*self.BasisZ.Y,
                   p.X*self.BasisX.Z+p.Y*self.BasisY.Z+p.Z*self.BasisZ.Z)

    def OfPoint(self,p):
        q=self.OfVector(p)
        return XYZ(q.X+self.Origin.X,q.Y+self.Origin.Y,q.Z+self.Origin.Z)

    def Multiply(self,other):
        result=Transform()
        result.Origin=self.OfPoint(other.Origin)
        result.BasisX,result.BasisY,result.BasisZ=[self.OfVector(p) for p in (other.BasisX,other.BasisY,other.BasisZ)]
        return result

    @property
    def Inverse(self):
        result=Transform()
        result.BasisX=XYZ(self.BasisX.X,self.BasisY.X,self.BasisZ.X)
        result.BasisY=XYZ(self.BasisX.Y,self.BasisY.Y,self.BasisZ.Y)
        result.BasisZ=XYZ(self.BasisX.Z,self.BasisY.Z,self.BasisZ.Z)
        result.Origin=result.OfVector(XYZ(-self.Origin.X,-self.Origin.Y,-self.Origin.Z))
        return result


class Factory(object):
    @property
    def Identity(self):
        return Transform()


class PolyLine(object):
    GraphicsStyleId=-1
    def __init__(self,points):
        self.points=points
    def GetCoordinates(self):
        return self.points


class Curve(object):
    pass


class Instance(object):
    GraphicsStyleId=-1
    def __init__(self,geometry,transform):
        self.geometry,self.Transform=Geometry(geometry),transform
    def GetSymbolGeometry(self):
        return self.geometry


class Cad(object):
    ViewSpecific=False
    def __init__(self,geometry,transform):
        self.geometry,self.transform=Geometry(geometry),transform
    def get_Geometry(self,options):
        return self.geometry
    def GetTransform(self):
        return self.transform


def load_floors():
    service=load_adapter()
    db=service.DB
    db.Transform=Factory()
    db.ImportInstance,db.PolyLine,db.Curve,db.GeometryInstance=Cad,PolyLine,Curve,Instance
    db.GraphicsStyle=type('GraphicsStyle',(),{})
    names=('pyrevit','System','System.Collections','System.Collections.Generic','topobim_revit','topobim_floors')
    old={n:sys.modules.get(n) for n in names}
    try:
        for name in names[:4]:
            sys.modules[name]=types.ModuleType(name)
        sys.modules['pyrevit'].DB=db
        sys.modules['System.Collections.Generic'].List=list
        sys.modules['topobim_revit']=service
        sys.modules.pop('topobim_floors',None)
        return __import__('topobim_floors')
    finally:
        for name,module in old.items():
            if module is None:
                sys.modules.pop(name,None)
            else:
                sys.modules[name]=module


floors=load_floors()


class FloorAdapterTests(unittest.TestCase):
    def setUp(self):
        placement=Transform(100,200,5)
        placement.BasisX,placement.BasisY=XYZ(0,1,0),XYZ(-1,0,0)
        self.path=PolyLine([XYZ(x,y,0) for x,y in [(0,0),(10,0),(10,10),(0,10),(0,0)]])
        block=Instance([self.path],Transform(2,3,0))
        root=Instance([block],placement)
        root.GraphicsStyleId=100
        self.cad=Cad([root],placement)
        style=floors.DB.GraphicsStyle()
        style.GraphicsStyleCategory=Record(Name='PISO')
        self.doc=Record(GetElement=lambda i: self.cad if i==1 else style if i==100 else None,
                        ActiveProjectLocation=Location('Atual',1,Position(700,800,20,0.37)))

    def test_original_mode_removes_cad_placement_keeps_nested_block(self):
        areas,issues=floors.read_areas(self.doc,1,True)
        self.assertFalse(issues)
        p=areas['PISO'][0].outer[0]
        self.assertAlmostEqual(2*0.3048,p.E)
        self.assertAlmostEqual(3*0.3048,p.N)
        self.assertAlmostEqual(0,p.Z)

    def test_current_mode_includes_rotation_translation_shared_vertical(self):
        areas,issues=floors.read_areas(self.doc,1,False)
        model=self.cad.transform.OfPoint(XYZ(2,3,0))
        expected=floors.service.internal_to_shared(self.doc.ActiveProjectLocation).OfPoint(model)
        p=areas['PISO'][0].outer[0]
        for value,actual in zip((expected.X,expected.Y,expected.Z),(p.E,p.N,p.Z)):
            self.assertAlmostEqual(value*0.3048,actual)

    def test_view_specific_and_missing_geometry_rejected(self):
        self.cad.ViewSpecific=True
        self.assertRaises(ValueError,floors.read_areas,self.doc,1)
        self.cad.ViewSpecific=False
        self.cad.geometry=Geometry([])
        self.assertRaises(ValueError,floors.read_areas,self.doc,1)

    def test_prepare_rejects_changed_contour(self):
        areas,_=floors.read_areas(self.doc,1)
        settings=dict(CadId=1,Original=True,Layers=[('PISO',20)],LevelId=30,Signature=floors.signature(areas,['PISO']))
        prepared=floors.prepare(self.doc,settings)
        self.assertIn('PISO',prepared['Areas'])
        self.path.points[1]=XYZ(11,0,0)
        self.assertRaises(ValueError,floors.prepare,self.doc,settings)

    def test_prepare_does_not_mutate_ui_settings(self):
        areas,_=floors.read_areas(self.doc,1)
        settings=dict(CadId=1,Original=True,Layers=[('PISO',20)],LevelId=30,Signature=floors.signature(areas,['PISO']))
        floors.prepare(self.doc,settings)
        self.assertNotIn('Areas',settings)

    def test_current_placement_survives_a_new_shared_origin_during_creation(self):
        areas,_=floors.read_areas(self.doc,1,False)
        settings=dict(CadId=1,Original=False,Layers=[('PISO',20)],LevelId=30,Signature=floors.signature(areas,['PISO']))
        prepared=floors.prepare(self.doc,settings)
        self.assertNotIn('InternalAreas',settings)
        self.doc.ActiveProjectLocation=Location('Nova',2,Position(7000000,32000000,100,0.71))
        expected=self.cad.transform.OfPoint(XYZ(2,3,0))
        captured=[]
        original_surface,original_create,original_excavate=floors.surface,floors.create_one,floors.excavate
        old_parameters=getattr(floors.DB,'BuiltInParameter',None)
        try:
            floors.surface=lambda *args:None
            def create_one(doc,reference,region,type_id,level_id):
                captured.append(region)
                return Record(Id=50,get_Parameter=lambda p:None),dict(ElementId='50')
            floors.create_one=create_one
            floors.excavate=lambda *args:False
            floors.DB.BuiltInParameter=Record(ALL_MODEL_INSTANCE_COMMENTS='comments')
            reports=floors.create(self.doc,None,prepared)
            self.assertEqual(1,len(reports))
            p=captured[0].outer[0]
            for wanted,actual in zip((expected.X,expected.Y,expected.Z),(p.E,p.N,p.Z)):
                self.assertAlmostEqual(wanted*0.3048,actual)
        finally:
            floors.surface,floors.create_one,floors.excavate=original_surface,original_create,original_excavate
            if old_parameters is None:
                del floors.DB.BuiltInParameter
            else:
                floors.DB.BuiltInParameter=old_parameters

    def test_elevation_detection_ignores_placement_and_shared_vertical_offset(self):
        for original in (True,False):
            areas,_=floors.read_areas(self.doc,1,original)
            self.assertFalse(areas.elevated_regions['PISO'][0])
        self.path.points = [XYZ(p.X,p.Y,4) for p in self.path.points]
        for original in (True,False):
            areas,_=floors.read_areas(self.doc,1,original)
            self.assertTrue(areas.elevated_regions['PISO'][0])

    def test_registered_floor_uses_survey_frame_after_site_change(self):
        local = [floors.core.Point(x,y,12) for x,y in [(0,0),(2,1),(7,2),(8,9),(3,11),(-2,6),(1,3),(4,5)]]
        survey = [floors.core.Point(p.E+778468.5,p.N+9839410.8,p.Z) for p in local]
        previous = floors.service.read_cad
        try:
            floors.service.read_cad = lambda *args:[Record(layer='CURVAS',point=p) for p in local]
            areas,_ = floors.read_registered_areas(self.doc,1,survey)
            settings = dict(CadId=1,Original=True,RegisterSurvey=True,SurveyPoints=survey,
                            Layers=[('PISO',20)],LevelId=30,Signature=floors.signature(areas,['PISO']))
            prepared = floors.prepare(self.doc,settings)
            self.assertNotIn('InternalAreas',prepared)
            self.doc.ActiveProjectLocation = Location('Nova',2,Position(2500000,32000000,100,0.71))
            region = floors.internal_region(prepared['Areas']['PISO'][0],self.doc.ActiveProjectLocation)
            actual = floors.service.internal_to_shared(self.doc.ActiveProjectLocation).OfPoint(
                XYZ(*(v/0.3048 for v in region.outer[0])))
            self.assertAlmostEqual(778468.5+2*0.3048,actual.X*0.3048,delta=0.001)
            self.assertAlmostEqual(9839410.8+3*0.3048,actual.Y*0.3048,delta=0.001)
            self.path.points[1] = XYZ(11,0,0)
            self.assertRaises(ValueError,floors.prepare,self.doc,settings)
        finally:
            floors.service.read_cad = previous

    def test_changed_cad_z_invalidates_review(self):
        areas,_=floors.read_areas(self.doc,1)
        before=floors.signature(areas,['PISO'])
        self.path.points=[XYZ(p.X,p.Y,4) for p in self.path.points]
        after,_=floors.read_areas(self.doc,1)
        self.assertNotEqual(before,floors.signature(after,['PISO']))

    def test_upper_vertices_can_be_verified_without_a_face_mesh(self):
        g,p=floors.geom,floors.core.Point
        region=g.Region([p(0,0,10),p(10,0,10),p(0,10,10)],[])
        desired=g.Surface([tuple(region.outer)])
        editor=Record(SlabShapeVertices=[Record(Position=XYZ(q.E/0.3048,q.N/0.3048,q.Z/0.3048)) for q in region.outer], Dispose=lambda:None)
        floor=Record(Id=10,GetSlabShapeEditor=lambda:editor)
        original=floors.surface
        def missing(*args):
            raise floors.SurfaceUnavailable('no mesh')
        try:
            floors.surface=missing
            self.assertAlmostEqual(0,floors.verify_contact(floor,desired,region))
            editor.SlabShapeVertices[0].Position.Z+=1
            self.assertRaises(ValueError,floors.verify_contact,floor,desired,region)
        finally:
            floors.surface=original

    def test_contact_checks_overlap_even_when_all_floor_corners_are_outside(self):
        g = floors.geom
        p = floors.core.Point
        terrain = g.Surface([(p(0,0,10),p(10,0,10),p(0,10,10))])
        outer = [p(-2,-2,0),p(12,-2,0),p(12,12,0),p(-2,12,0)]
        region = g.Region(outer,[])
        original = floors.surface
        def bottom(z):
            vertices = [p(q.E,q.N,z) for q in outer]
            return g.Surface([(vertices[0],vertices[1],vertices[2]),
                              (vertices[0],vertices[2],vertices[3])])
        try:
            floors.surface = lambda *args: bottom(10)
            self.assertAlmostEqual(0,floors.verify_contact(None,terrain,region))
            floors.surface = lambda *args: bottom(11)
            self.assertRaises(ValueError,floors.verify_contact,None,terrain,region)
        finally:
            floors.surface = original

    def test_fully_external_floor_does_not_require_surveyed_support(self):
        g = floors.geom
        p = floors.core.Point
        terrain = g.Surface([(p(0,0,10),p(10,0,10),p(0,10,10))])
        outer = [p(20,20,0),p(30,20,0),p(30,30,0),p(20,30,0)]
        original = floors.surface
        try:
            floors.surface = lambda *args: g.Surface([(p(20,20,10),p(30,20,10),p(30,30,10)),
                                                     (p(20,20,10),p(30,30,10),p(20,30,10))])
            self.assertEqual(0,floors.verify_contact(None,terrain,g.Region(outer,[])))
        finally:
            floors.surface = original

    def test_external_floor_does_not_fail_when_its_mesh_misses_a_corner(self):
        g,p=floors.geom,floors.core.Point
        terrain=g.Surface([(p(0,0,10),p(10,0,10),p(0,10,10))])
        outer=[p(-778499.516,-9839411.232,10),p(-778489.516,-9839411.232,10),
               p(-778489.516,-9839401.232,10),p(-778499.516,-9839401.232,10)]
        region=g.Region(outer,[])
        # Simulate rounded mesh bounds that omit actual double-precision corners.
        mesh=g.Surface([
            (p(outer[0].E+0.1,outer[0].N+0.1,10),p(outer[1].E-0.1,outer[1].N+0.1,10),p(outer[2].E-0.1,outer[2].N-0.1,10))])
        editor=Record(SlabShapeVertices=[Record(Position=XYZ(q.E/0.3048,q.N/0.3048,q.Z/0.3048)) for q in outer],Dispose=lambda:None)
        floor=Record(Id=10,GetSlabShapeEditor=lambda:editor)
        original=floors.surface
        try:
            floors.surface=lambda *args:mesh
            self.assertAlmostEqual(0,floors.verify_contact(floor,terrain,region))
            editor.SlabShapeVertices[0].Position.Z+=1
            self.assertRaises(ValueError,floors.verify_contact,floor,terrain,region)
        finally:
            floors.surface=original


if __name__=='__main__':
    unittest.main()
