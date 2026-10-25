# -*- coding: utf-8 -*-
"""Standalone IronPython/WPF checks, with a simulated pyRevit host.

Run using run_ironpython.ps1. This does not create a Revit document or validate
Revit geometry. Real WPF controls, XAML loading, events and bindings are used.
"""
from __future__ import unicode_literals
import os
import sys
import types
import clr

clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('pyRevitLabs.IronPython.Wpf')
import wpf
from System import Math, Action
from System.Windows import Window, Size, Rect, Visibility
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media import PixelFormats, Brushes, DrawingVisual
from System.Windows.Threading import DispatcherPriority
from System.Windows.Media.Imaging import RenderTargetBitmap, PngBitmapEncoder, BitmapFrame
from System.IO import FileStream, FileMode, StringReader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import topobim_core as core


class Record(object):
    def __init__(self, **values):
        self.__dict__.update(values)


class WPFWindow(Window):
    def __init__(self, path, literal_string=False):
        wpf.LoadComponent(self, StringReader(path) if literal_string else path)


def alert(message, **kwargs):
    raise AssertionError(message)


host = types.ModuleType('pyrevit')
host.forms = Record(WPFWindow=WPFWindow, alert=alert)
host.DB = Record(ImportInstance=type('ImportInstance', (), {}),
                 ToposolidType=type('ToposolidType', (), {}), Level=type('Level', (), {}))
sys.modules['pyrevit'] = host
import topobim_revit as service
service.choices = lambda doc, kind: [Record(Id=1, Name='Exemplo', Label='Exemplo [ID 1]')]
service.needs_location = lambda doc, analysis: False
original_geographic_settings = service.geographic_settings


def simulated_geography(doc, settings):
    if not settings['NewLocation']:
        settings = dict(settings, NewLocation=True, East=780025.0, North=9840040.0, Elevation=25.0)
    return original_geographic_settings(doc, settings)


service.geographic_settings = simulated_geography
import topobim_ui as ui
import topobim_floors as floors
import topobim_floor_geometry as floor_geometry


def layout(window):
    width, height = globals().get('QA_WIDTH', 1050), globals().get('QA_HEIGHT', 790)
    window.Content.Measure(Size(width, height))
    window.Content.Arrange(Rect(0, 0, width, height))
    window.Content.UpdateLayout()
    window.Dispatcher.Invoke(Action(lambda: None), DispatcherPriority.ApplicationIdle)
    window.Content.UpdateLayout()


def render(window, name):
    if 'QA_OUTPUT' not in globals():
        return
    layout(window)
    width, height = globals().get('QA_WIDTH', 1050), globals().get('QA_HEIGHT', 790)
    dpi = globals().get('QA_DPI', 96)
    bitmap = RenderTargetBitmap(int(width*dpi/96), int(height*dpi/96), dpi, dpi, PixelFormats.Pbgra32)
    background = DrawingVisual()
    context = background.RenderOpen()
    context.DrawRectangle(window.FindResource('PageBrush'), None, Rect(0,0,width,height))
    context.Close()
    bitmap.Render(background)
    bitmap.Render(window.Content)
    encoder = PngBitmapEncoder()
    encoder.Frames.Add(BitmapFrame.Create(bitmap))
    stream = FileStream(os.path.join(QA_OUTPUT, name), FileMode.Create)
    try:
        encoder.Save(stream)
    finally:
        stream.Dispose()


doc = Record(ActiveProjectLocation=Record(Name='Localização existente'))
logger = Record(exception=lambda text: None)
window = ui.TopoBimWindow(Record(Document=doc), logger)
layout(window)
assert window.SourceMode.SelectedIndex == 0
assert window.CadPanel.Visibility == Visibility.Collapsed
assert window.TopoTypes.Items.Count == 1
assert window.CreateFloors.IsChecked != True
assert window.FloorCoordinates.SelectedIndex == 2
assert window.floor_settings() is None
assert window.FloorPanel.Visibility == Visibility.Collapsed
render(window, 'entrada.png')

window.csv_path = os.path.join(ROOT, 'bruto_para_coverter', 'samples', 'terreno_exemplo_ENZ.csv')
window.load_source()
layout(window)
assert window.ready()
assert len(window.analysis.points) == 54
assert 'Nenhuma ocorrência encontrada' in window.Quality.Text
assert window.Tabs.SelectedIndex == 1
assert window.Preview.Children.Count == 56
measure = window.measurements
survey = list(window.analysis.points)
corners = [min(survey, key=lambda p: p.E+p.N),
           max(survey, key=lambda p: p.E-p.N),
           max(survey, key=lambda p: p.E+p.N),
           min(survey, key=lambda p: p.E-p.N)]
def measure_click(point):
    position = ui.Point(*measure.project(point))
    window.pan_start(None, Record(ClickCount=1, GetPosition=lambda control: position, Handled=False))
    window.pan_end(None, None)

measure.start('distance')
measure_click(corners[0])
assert measure.active == 'distance'
measure_click(corners[1])
assert measure.active is None
assert len(measure.points['distance']) == 2
assert window.DistanceValue.Text == '50.000 m'
assert 'Horizontal' in window.DistanceDetail.Text
assert '50.000000 m' in window.DistanceValue.ToolTip
measure.undo()
assert len(measure.points['distance']) == 1
measure_click(corners[1])
measure.start('area')
for point in corners:
    measure_click(point)
assert window.FinishArea.IsEnabled
measure.finish_area()
assert window.AreaValue.Text == '4000.000 m²'
assert measure.area_closed
measure.start('level')
measure_click(survey[20])
assert window.LevelValue.Text == '{0.Z:.3f} m'.format(survey[20])
assert window.MeasureOverlay.Children.Count > 0
window.PreviewMode.SelectedIndex = 1
layout(window)
assert window.MeasureOverlay.Children.Count == 0
# Picking follows the camera after orbit, zoom and translation.
window.yaw, window.pitch = 25.0, 55.0
window.zoom, window.offset = 1.3, (12.0,-7.0)
window.draw()
probe = survey[20]
screen = window.terrain_view.project(probe)
picked = window.terrain_view.pick(*screen)
assert picked is not None
assert abs(picked.E-probe.E) < 0.00001
assert abs(picked.N-probe.N) < 0.00001
assert abs(picked.Z-probe.Z) < 0.00001
measure.start('level')
assert window.PreviewMode.SelectedIndex == 0
measure_click(probe)
assert window.LevelValue.Text == '{0.Z:.3f} m'.format(probe)
measure.start('level')
measure.click(ui.Point(-10000,-10000))
assert measure.points['level'] == []
assert 'vértice' in window.MeasureStatus.Text
# No elevation is invented at an unsurveyed point between vertices.
middle = ui.Point(*measure.project(core.Point(corners[0].E+5, corners[0].N+5, 0)))
measure.click(middle)
assert measure.points['level'] == []
assert 'Nenhum vértice' in window.MeasureStatus.Text
measure.hover(ui.Point(*measure.project(probe)))
assert measure.hovered is probe
assert 'Vértice original' in window.MeasureStatus.Text
window.PreviewMode.SelectedIndex = 1
assert measure.active is None
assert window.MeasureOverlay.Children.Count == 0
measure.start('level')
assert window.PreviewMode.SelectedIndex == 0
# Dragging while a tool is armed navigates without adding a measurement point.
window.pan_start(None, Record(ClickCount=1, GetPosition=lambda c: ui.Point(100,100), Handled=False))
window.pan_move(None, Record(LeftButton=ui.MouseButtonState.Pressed, GetPosition=lambda c: ui.Point(140,120)))
window.pan_end(None,None)
assert measure.points['level'] == []
measure.navigate()
measure.start('level')
measure_click(probe)
assert measure.points['level'][0] is probe
window.fit(None,None)
window.DistanceCell.BringIntoView()
render(window, 'afericoes.png')
measure.reset()
assert not window.MeasureClear.IsEnabled
assert window.MeasureOverlay.Children.Count == 0
# A changed survey discards measurements rather than keeping stale elevations.
measure.start('distance')
measure_click(corners[0])
window.reset_review()
assert not any(measure.points.values())
assert not window.MeasureDistance.IsEnabled
window.set_analysis(survey)
window.PreviewMode.SelectedIndex = 0
window.PreviewHost.BringIntoView()
layout(window)
render(window, 'conferencia.png')
# A real WPF mesh and camera are created without touching a Revit document.
window.PreviewMode.SelectedIndex = 1
layout(window)
assert window.terrain_view.ready
assert window.TerrainViewport.Visibility == Visibility.Visible
assert window.Preview.Visibility == Visibility.Collapsed
assert window.terrain_view.point_count == 54
visual = window.TerrainViewport.Children[0]
camera = window.TerrainViewport.Camera
assert visual.Content.Children[2].Geometry.TriangleIndices.Count > 0
render(window, 'conferencia-3d.png')
window.drag = ui.Point(100, 100)
window.pan_move(None, Record(LeftButton=ui.MouseButtonState.Pressed,
                            GetPosition=lambda control: ui.Point(160, 120)))
assert window.yaw != -60.0
assert window.TerrainViewport.Camera.Position != camera.Position
assert window.TerrainViewport.Children[0] is visual
window.pan_lost(None, None)
wheel = Record(GetPosition=lambda control: ui.Point(120, 100), Delta=120, Handled=False)
previous_width = window.TerrainViewport.Camera.Width
window.preview_zoom(None, wheel)
assert window.TerrainViewport.Camera.Width < previous_width
assert wheel.Handled
window.fit(None, None)
assert window.zoom == 1.0 and window.offset == (0.0, 0.0)
assert window.pitch == 35.0 and window.yaw == -60.0
window.PreviewMode.SelectedIndex = 0
layout(window)
assert window.Preview.Visibility == Visibility.Visible
assert window.Preview.Children.Count == 56
floor_type_a = Record(Id=10, Name='Concreto', Label='Concreto · 100 mm · Concreto')
floor_type_b = Record(Id=11, Name='Asfalto', Label='Asfalto · 50 mm · Asfalto')
floor_region = floor_geometry.Region([core.Point(1,1,0),core.Point(4,1,0),core.Point(4,4,0),core.Point(1,4,0)], [])
floors.floor_choices = lambda doc: [floor_type_a, floor_type_b]
floors.read_areas = lambda *args: ({'PAVIMENTACAO': [floor_region]}, ['Outra camada: curvas abertas ignoradas.'])
def registered_areas(doc, cad_id, survey):
    assert len(survey) == 54
    areas = floors.AreaMap({'PAVIMENTACAO':[floor_region]})
    areas.registration = dict(Coverage=1.0,Layer='CurvasTG')
    return areas, ['Outra camada: curvas abertas ignoradas.']
floors.read_registered_areas = registered_areas
window.Reviewed.IsChecked = True
window.CreateFloors.IsChecked = True
assert not window.Reviewed.IsChecked
assert window.FloorPanel.Visibility == Visibility.Visible
window.find_floors(None,None)
layout(window)
assert len(window.floor_rows) == 1
row = window.floor_rows[0]
assert row.Enabled == False
assert row.SelectedType is None
try:
    window.floor_settings()
    assert False, 'Must require explicit layer selection'
except ValueError:
    pass
row.Enabled = True
try:
    window.floor_settings()
    assert False, 'Must require explicit type selection'
except ValueError:
    pass
# Exercise a real WPF ComboBox binding in the table, not just the Python model.
from System.Windows.Media import VisualTreeHelper
from System.Windows.Controls import ComboBox
from System.Windows.Controls import CheckBox
def descendants(root):
    for index in range(VisualTreeHelper.GetChildrenCount(root)):
        child = VisualTreeHelper.GetChild(root,index)
        yield child
        for nested in descendants(child):
            yield nested
window.FloorTable.BringIntoView()
layout(window)
combos = [c for c in descendants(window.FloorTable) if isinstance(c,ComboBox)]
assert len(combos) == 1
checkboxes = [c for c in descendants(window.FloorTable) if isinstance(c,CheckBox)]
assert len(checkboxes) == 1
checkboxes[0].IsChecked = True
layout(window)
assert row.Enabled
checkboxes[0].IsChecked = False
layout(window)
assert not row.Enabled
checkboxes[0].IsChecked = True
layout(window)
assert row.Enabled
window.Reviewed.IsChecked = True
combos[0].SelectedIndex = 1
layout(window)
assert row.SelectedType is floor_type_b
assert not window.Reviewed.IsChecked
config = window.floor_settings()
assert config['Layers'] == [('PAVIMENTACAO',11)]
assert len(config['Signature']) == 64
assert config['RegisterSurvey']
assert config['Original']
assert len(config['SurveyPoints']) == 54
render(window, 'conferencia-pisos.png')
window.Reviewed.IsChecked = True
window.FloorCoordinates.SelectedIndex = 0
assert not window.Reviewed.IsChecked
assert window.analysis is not None
assert window.floor_rows == []
window.CreateFloors.IsChecked = False
assert window.floor_settings() is None
window.Tabs.SelectedIndex = 2
layout(window)
assert window.GeoMode.SelectedIndex == 0
assert 'Latitude:' in window.GeographicPreview.Text
assert '-48.48350387' in window.GeographicPreview.Text
render(window, 'criacao.png')
window.GeographicMode.SelectedIndex = 1
assert window.ManualGeography.Visibility == Visibility.Visible
window.Latitude.Text = '-1.451637'
window.Longitude.Text = '-48.497723'
assert '-48.49772300' in window.GeographicPreview.Text
window.Reviewed.IsChecked = True
window.Latitude.Text = '-1.4'
assert not window.Reviewed.IsChecked
window.Latitude.Text = '91'
assert 'Confira a localização:' in window.GeographicPreview.Text
window.GeographicMode.SelectedIndex = 0
window.Reviewed.IsChecked = True
window.AnchorE.Text = '123'
assert not window.Reviewed.IsChecked
window.Units.SelectedIndex = 1
assert window.analysis is None
assert not window.terrain_view.ready
assert window.TerrainViewport.Children.Count == 0
assert not window.ready()
window.Tabs.SelectedIndex = 1
window.Tabs.SelectedIndex = 2
assert window.Tabs.SelectedIndex == 1
window.Units.SelectedIndex = 0

window.csv_path = os.path.join(ROOT, 'bruto_para_coverter', 'samples', 'erros_exemplo.csv')
window.load_source()
assert not window.ready()
assert len(window.read_errors) == 1
assert 'Nenhuma ocorrência' not in window.Quality.Text
assert len(window.analysis.conflicts) == 1
rows = core.occurrence_rows(window.read_errors, window.analysis.conflicts)
# Create a hidden handle so the child dialog can have an owner without showing UI.
WindowInteropHelper(window).EnsureHandle()
issues = ui.OccurrencesWindow(window, rows)
layout(issues)
assert issues.Table.Items.Count == 2
render(issues, 'ocorrencias.png')
issues.Close()

# Even a failed geometric analysis retains diagnostics and exportable rows.
window.reset_review()
window.set_analysis([core.Point(0, 0, 1), core.Point(0, 0, 5)])
assert window.geometry_error
assert len(window.analysis.conflicts) == 1
assert not window.ready()

window.SourceMode.SelectedIndex = 1
assert window.CsvPanel.Visibility == Visibility.Collapsed
assert window.read_errors == []
service.read_cad = lambda *args: [service.CadPoint(core.Point(0, 0, 1), 'Terreno'),
                                service.CadPoint(core.Point(10, 0, 2), 'Terreno'),
                                service.CadPoint(core.Point(0, 10, 3), 'Terreno'),
                                service.CadPoint(core.Point(0, 0, 99), 'Equipamentos')]
window.load_source()
assert window.Layers.SelectedItems.Count == 0
assert not window.ready()
window.Layers.SelectedItems.Add('Terreno')
window.apply_layers(None, None)
assert window.ready()
assert not window.analysis.conflicts
service.needs_location = lambda doc, analysis: True
window.Tabs.SelectedIndex = 2
assert window.GeoMode.SelectedIndex == 1
assert not window.GeoConsent.IsChecked
render(window, 'criacao-origem.png')
window.Layers.SelectedItems.Add('Equipamentos')
assert not window.ready()
assert not window.GeoConsent.IsChecked
window.report = dict(ReviewViewId='42')
window.view_created(None,None)
assert window.requested_review_view_id == '42'

# Check ties-to-even against the real .NET Math.Round, including UTM values.
for origin in (0, 780000, 9840000, -780000):
    for index in range(-100, 101):
        value = origin + index * 0.0005
        assert core.grid_key(value) == Math.Round(value, 3), repr(value)
print('WPF state, events, XAML, rendering and .NET rounding: OK')

# Presentation QA uses real WPF controls with a simulated host. Raster DPI checks
# are not a substitute for moving a live Revit window between physical monitors.
if 'QA_OUTPUT' in globals():
    service.needs_location = lambda doc, analysis: False
    design = ui.TopoBimWindow(Record(Document=doc), logger)
    design.csv_path = os.path.join(ROOT, 'bruto_para_coverter', 'samples', 'terreno_exemplo_ENZ.csv')
    design.load_source()
    assert str(design.FontFamily) == 'Segoe UI'
    assert design.Next.Focusable and design.Back.Focusable
    assert design.Next.Background.Color == design.FindResource('PrimaryBrush').Color
    assert design.Next.Foreground.Color == design.FindResource('SurfaceBrush').Color
    assert design.FindResource('TextBrush').Color.R == 23
    for label, width, height in (('ampla',1050,790), ('compacta',750,650)):
        QA_WIDTH, QA_HEIGHT = width, height
        for QA_DPI in (96,120,144):
            design.ReviewScroll.ScrollToTop()
            layout(design)
            # Footer remains outside the scrolling area at every tested size.
            for button in (design.Back, design.Next):
                location = button.TranslatePoint(ui.Point(0,0), design.Content)
                assert location.X >= 0 and location.Y >= 0
                assert location.X+button.ActualWidth <= width+1
                assert location.Y+button.ActualHeight <= height+1
            assert design.PreviewHost.ActualWidth > 0
            assert design.PreviewMode.ActualWidth >= 110
            assert design.Fit.ActualWidth >= 70
            render(design, 'topobim-{0}-{1}.png'.format(label,int(QA_DPI/96.0*100)))
            # Scroll brings every measurement action fully into the viewport.
            for button in (design.MeasureDistance,design.MeasureArea,design.FinishArea,design.MeasureLevel):
                button.BringIntoView()
                layout(design)
                location = button.TranslatePoint(ui.Point(0,0),design.ReviewScroll)
                assert location.Y >= -1
                assert location.Y+button.ActualHeight <= design.ReviewScroll.ActualHeight+1
        render(design,'topobim-afericoes-{0}.png'.format(label))
    QA_WIDTH, QA_HEIGHT, QA_DPI = 1050,790,96
    design.ReviewScroll.ScrollToTop()
    design.PreviewMode.SelectedIndex = 1
    render(design,'topobim-modelo-3d.png')
    design.Tabs.SelectedIndex = 0
    render(design,'topobim-entrada.png')
    design.Tabs.SelectedIndex = 2
    render(design,'topobim-criacao.png')
    design.Close()
    print('Visual QA: wide/compact layouts, footer, scroll access and 96/120/144 DPI rendering: OK')
