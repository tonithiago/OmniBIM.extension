# -*- coding: utf-8 -*-
"""Run from an IronPython pyRevit console in a disposable Revit 2026 project.

No file is saved. A TransactionGroup rolls back ALL test elements and locations,
including on failure. This script must run in API context without an outer
transaction. It does not test the ribbon, actual DWG files or interactive Undo.
"""
from __future__ import unicode_literals
import os
import sys
import math
from pyrevit import revit, DB, HOST_APP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import topobim_core as core
import topobim_revit as service


def run(doc=None):
    doc = doc or revit.doc
    if str(HOST_APP.version) != '2026' or doc is None or doc.IsFamilyDocument:
        raise ValueError('Abra um projeto descartável no Revit 2026.')
    if doc.IsModifiable or doc.IsReadOnly:
        raise ValueError('Execute fora de uma transação, em um projeto editável.')
    types = service.choices(doc, DB.ToposolidType)
    levels = service.choices(doc, DB.Level)
    if not types or not levels:
        raise ValueError('O projeto de teste precisa de um nível e de um tipo de Toposolid.')
    points = core.read_points(os.path.join(ROOT, 'bruto_para_coverter', 'samples', 'terreno_exemplo_ENZ.csv')).points
    analysis = core.analyze(points)
    previous_location = doc.ActiveProjectLocation.Id
    previous_count = DB.FilteredElementCollector(doc).GetElementCount()
    previous_geography = (doc.SiteLocation.Latitude, doc.SiteLocation.Longitude, doc.SiteLocation.TimeZone)
    project_point = DB.BasePoint.GetProjectBasePoint(doc)
    survey_point = DB.BasePoint.GetSurveyPoint(doc)
    previous_bases = [(p.Id, p.Position, p.Pinned) for p in (project_point, survey_point)]
    previous_clipped = survey_point.Clipped
    group = DB.TransactionGroup(doc, 'TOPOBIM - testes temporários (reverter)')
    assert group.Start() == DB.TransactionStatus.Started
    created = []
    passed = []
    try:
        # Two genuinely different thicknesses and levels exercise Z correction.
        setup = DB.Transaction(doc, 'TOPOBIM - preparar casos temporários')
        setup.Start()
        try:
            # Start with separated markers; creation must align them without moving the model.
            for base, target in ((project_point, DB.XYZ(20, 40, 3)), (survey_point, DB.XYZ(-30, 10, 5))):
                base.Pinned = False
                if base.IsShared:
                    base.Clipped = False
                DB.ElementTransformUtils.MoveElement(doc, base.Id, target.Subtract(base.Position))
                base.Pinned = True
            survey_point.Clipped = True
            elevated_level = DB.Level.Create(doc, service.feet(8))
            type_original = doc.GetElement(types[0].Id)
            thick_type = type_original.Duplicate('TOPOBIM teste ' + str(elevated_level.Id))
            structure = thick_type.GetCompoundStructure()
            if structure is None or structure.LayerCount == 0:
                raise ValueError('Escolha um tipo de Toposolid com estrutura composta para testar espessuras.')
            layer = next(i for i in range(structure.LayerCount) if structure.GetLayerWidth(i) > 0)
            structure.SetLayerWidth(layer, structure.GetLayerWidth(layer) + service.feet(0.5))
            thick_type.SetCompoundStructure(structure)
            assert setup.Commit() == DB.TransactionStatus.Committed
        finally:
            if setup.GetStatus() == DB.TransactionStatus.Started:
                setup.RollBack()
            setup.Dispose()
        for angle, elevation in ((0.0, 0.0), (0.0, 100.0), (0.37, 25.0)):
            setup = DB.Transaction(doc, 'TOPOBIM - referência temporária')
            setup.Start()
            try:
                location = doc.ActiveProjectLocation.Duplicate('TOPOBIM teste ref {0} {1}'.format(angle, elevation))
                position = DB.ProjectPosition(service.feet(780025), service.feet(9840040), service.feet(elevation), angle)
                try:
                    location.SetProjectPosition(DB.XYZ.Zero, position)
                finally:
                    position.Dispose()
                doc.ActiveProjectLocation = location
                legacy_id = location.Id
                assert setup.Commit() == DB.TransactionStatus.Committed
            finally:
                if setup.GetStatus() == DB.TransactionStatus.Started:
                    setup.RollBack()
                setup.Dispose()
            assert not service.needs_location(doc, analysis), 'Referência compartilhada válida foi rejeitada.'
            for type_id, level_id in ((types[0].Id, levels[0].Id), (thick_type.Id, elevated_level.Id)):
                settings = dict(NewLocation=False, East=0.0, North=0.0, Elevation=0.0,
                                Datum='SIRGAS 2000', Zone=22, Hemisphere='Sul')
                element_id, report = service.create(doc, analysis, type_id, level_id, settings, 'Teste automatizado')
                created.append(element_id)
                assert doc.ActiveProjectLocation.Name == service.DEFAULT_LOCATION_NAME
                assert doc.GetElement(legacy_id) is None
                position = doc.ActiveProjectLocation.GetProjectPosition(DB.XYZ.Zero)
                try:
                    assert abs(position.Angle - angle) < 1e-9
                    assert abs(service.metres(position.Elevation) - elevation) < 1e-6
                finally:
                    position.Dispose()
                surface_target = service.surface_base_point(doc.GetElement(element_id))
                for base in (project_point, survey_point):
                    assert base.Position.DistanceTo(surface_target) < service.feet(0.000001)
                    assert base.Pinned
                assert survey_point.Clipped
                assert project_point.SharedPosition.DistanceTo(survey_point.SharedPosition) < service.feet(0.000001)
                shared_elevation = service.metres(project_point.SharedPosition.Z)
                assert min(p.Z for p in analysis.points) <= shared_elevation <= max(p.Z for p in analysis.points)
                assert report['BasePoints']['VerifiedAfterCommit']
                geographic = report['GeographicLocation']
                assert abs(doc.SiteLocation.Latitude - math.radians(geographic['Latitude'])) < 1e-10
                assert abs(doc.SiteLocation.Longitude - math.radians(geographic['Longitude'])) < 1e-10
                assert report['Points'] == 54 and report['Errors'] == []
                passed.append('Criação: rotação {0}, origem Z {1}, tipo {2}, nível {3}'.format(angle, elevation, type_id, level_id))
                # Keep cases independent; overlapping test solids trigger a Revit
                # warning dialog and do not help verify elevation/coordinate behavior.
                cleanup = DB.Transaction(doc, 'TOPOBIM - remover sólido temporário do teste')
                cleanup.Start()
                try:
                    doc.Delete(element_id)
                    assert cleanup.Commit() == DB.TransactionStatus.Committed
                finally:
                    if cleanup.GetStatus() == DB.TransactionStatus.Started:
                        cleanup.RollBack()
                    cleanup.Dispose()

        # A failure after replacing the default site's coordinates must restore them.
        location_before_failure = doc.ActiveProjectLocation.Id
        count_before_failure = DB.FilteredElementCollector(doc).GetElementCount()
        shared_before_failure = service.internal_to_shared(doc.ActiveProjectLocation)
        geography_before_failure = (doc.SiteLocation.Latitude, doc.SiteLocation.Longitude)
        settings = dict(NewLocation=True, East=0.0, North=0.0, Elevation=0.0,
                        Datum='SIRGAS 2000', Zone=22, Hemisphere='Sul',
                        GeographicMode='manual', Latitude=-1.451637, Longitude=-48.497723)
        try:
            service.create(doc, analysis, types[0].Id, levels[0].Id, settings, 'Teste fora dos limites')
        except ValueError:
            pass
        else:
            raise AssertionError('Deveria recusar coordenadas fora dos limites.')
        assert doc.ActiveProjectLocation.Id == location_before_failure
        assert DB.FilteredElementCollector(doc).GetElementCount() == count_before_failure
        assert service.internal_to_shared(doc.ActiveProjectLocation).Origin.DistanceTo(shared_before_failure.Origin) < service.feet(0.000001)
        passed.append('Falha após atualizar Terreno padrão: rollback completo')

        # Simulate a late surface-check failure, after geography/base points were changed.
        original_check = service.preserve_elevations

        def fail_surface(*args):
            raise ValueError('Falha de superfície simulada pelo teste')

        service.preserve_elevations = fail_surface
        settings.update(East=780035.0, North=9840050.0)
        try:
            try:
                service.create(doc, analysis, types[0].Id, levels[0].Id, settings, 'Teste rollback geográfico')
            except ValueError as error:
                assert 'simulada' in str(error)
            else:
                raise AssertionError('A falha simulada deveria cancelar a criação.')
        finally:
            service.preserve_elevations = original_check
        assert (doc.SiteLocation.Latitude, doc.SiteLocation.Longitude) == geography_before_failure
        assert DB.FilteredElementCollector(doc).GetElementCount() == count_before_failure
        assert service.internal_to_shared(doc.ActiveProjectLocation).Origin.DistanceTo(shared_before_failure.Origin) < service.feet(0.000001)
        passed.append('Falha após latitude/longitude e superfície: rollback completo')

        settings.update(East=780025.0, North=9840040.0, GeographicMode='utm')
        element_id, report = service.create(doc, analysis, types[0].Id, levels[0].Id, settings, 'Teste Terreno padrão')
        created.append(element_id)
        assert doc.ActiveProjectLocation.Id == location_before_failure
        assert doc.ActiveProjectLocation.Name == service.DEFAULT_LOCATION_NAME
        passed.append('Criação reutiliza Terreno padrão e não duplica localizações')

        # Exercise missing vertices and altered relief without weakening checks.
        topo = doc.GetElement(element_id)
        expected = service.to_internal(analysis.points, doc.ActiveProjectLocation)
        try:
            service.match_surface(topo, [expected[0].Add(DB.XYZ(service.feet(1000), 0, 0))])
        except ValueError:
            passed.append('Vértice ausente rejeitado')
        else:
            raise AssertionError('Vértice ausente não foi detectado.')
        changed = list(expected)
        changed[0] = changed[0].Add(DB.XYZ(0, 0, service.feet(1)))
        try:
            service.preserve_elevations(doc, topo, changed)
        except ValueError:
            passed.append('Desnível alterado rejeitado')
        else:
            raise AssertionError('Desnível alterado não foi detectado.')
    finally:
        if group.GetStatus() == DB.TransactionStatus.Started:
            group.RollBack()
        group.Dispose()
    assert doc.ActiveProjectLocation.Id == previous_location
    assert DB.FilteredElementCollector(doc).GetElementCount() == previous_count
    assert (doc.SiteLocation.Latitude, doc.SiteLocation.Longitude, doc.SiteLocation.TimeZone) == previous_geography
    for element_id, position, pinned in previous_bases:
        base = doc.GetElement(element_id)
        assert base.Position.DistanceTo(position) < service.feet(0.000001)
        assert base.Pinned == pinned
    assert DB.BasePoint.GetSurveyPoint(doc).Clipped == previous_clipped
    assert all(doc.GetElement(element_id) is None for element_id in created)
    for message in passed:
        print('OK: ' + message)
    print('OK: todas as alterações temporárias foram revertidas.')


if __name__ == '__main__':
    run()
