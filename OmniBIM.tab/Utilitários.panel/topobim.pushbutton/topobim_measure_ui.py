# -*- coding: utf-8 -*-
"""2D measurements snapped to original survey vertices; no preview interpolation."""
from __future__ import division, unicode_literals
import math
from System.Windows import Point, Visibility
from System.Windows.Controls import Canvas, TextBlock
from System.Windows.Input import Cursors
from System.Windows.Media import Brushes, Color, SolidColorBrush
from System.Windows.Shapes import Ellipse, Polyline
from topobim_measure import distance, polygon_area, snap_vertex
from topobim_core import text_type


class MeasurementTools(object):
    def __init__(self, window):
        self.window = window
        self.active = None
        self.last = None
        self.points = dict(distance=[], area=[], level=[])
        self.area_closed = False
        window.MeasureDistance.Click += lambda s,e: self.start('distance')
        window.MeasureArea.Click += lambda s,e: self.start('area')
        window.MeasureLevel.Click += lambda s,e: self.start('level')
        window.FinishArea.Click += self.finish_area
        window.MeasureNavigate.Click += self.navigate
        window.MeasureUndo.Click += self.undo
        window.MeasureClear.Click += lambda s,e: self.reset()
        self.reset()

    def reset(self):
        self.active = self.last = None
        self.points = dict(distance=[], area=[], level=[])
        self.area_closed = False
        self.hovered = None
        self.window.MeasureStatus.Text = 'Aferições em planta: selecione vértices do levantamento. Use zoom para distinguir pontos próximos.'
        self.refresh()
        self.draw()

    def start(self, kind):
        self.window.PreviewMode.SelectedIndex = 0
        self.active = self.last = kind
        self.hovered = None
        self.points[kind] = []
        if kind == 'area':
            self.area_closed = False
        self.window.MeasureStatus.Text = {
            'distance': 'Distância 2D: selecione os vértices inicial e final. A medida usa Este/Norte.',
            'area': 'Área 2D: selecione os vértices em sequência e depois Concluir área.',
            'level': 'Cota de nível: selecione um vértice para consultar seu Z original.'}[kind]
        self.refresh()
        self.window.draw()

    def navigate(self, sender=None, event=None):
        self.active = None
        self.hovered = None
        self.window.MeasureStatus.Text = 'Navegação liberada. As marcações permanecem na prévia.'
        self.refresh()
        self.draw()

    def undo(self, sender=None, event=None):
        kind = self.last
        if kind and self.points[kind]:
            self.window.PreviewMode.SelectedIndex = 0
            self.hovered = None
            self.points[kind].pop()
            self.active = kind
            if kind == 'area':
                self.area_closed = False
            self.window.MeasureStatus.Text = 'Último ponto removido. Continue selecionando no terreno.'
            self.refresh()
            self.draw()

    def finish_area(self, sender=None, event=None):
        try:
            polygon_area(self.points['area'])
        except ValueError as error:
            self.window.MeasureStatus.Text = text_type(error)
            return
        self.area_closed = True
        self.active = None
        self.hovered = None
        self.window.MeasureStatus.Text = 'Área concluída em projeção horizontal (E/N), em metros quadrados.'
        self.refresh()
        self.draw()

    def refresh(self):
        w = self.window
        ready = w.analysis is not None and len(w.analysis.points) >= 3 and not w.geometry_error
        for control in (w.MeasureDistance, w.MeasureArea, w.MeasureLevel):
            control.IsEnabled = ready
        w.FinishArea.IsEnabled = self.active == 'area' and len(self.points['area']) >= 3
        w.MeasureNavigate.IsEnabled = self.active is not None
        w.MeasureUndo.IsEnabled = bool(self.last and self.points[self.last])
        w.MeasureClear.IsEnabled = any(self.points.values()) or self.active is not None
        for kind, cell in (('distance',w.DistanceCell), ('area',w.AreaCell), ('level',w.LevelCell)):
            cell.BorderBrush = w.FindResource('TextBrush' if self.active == kind else 'BorderBrush')
            cell.Background = w.FindResource('PageBrush' if self.active == kind else 'SurfaceBrush')
        w.PreviewHost.Cursor = Cursors.Cross if self.active else Cursors.Hand
        w.MeasurePrompt.Visibility = Visibility.Visible if self.active else Visibility.Collapsed
        pair = self.points['distance']
        w.DistanceValue.Text = '— m' if not pair else '1 / 2 pontos'
        w.DistanceDetail.Text = 'Horizontal em planta (E/N)'
        w.DistanceValue.ToolTip = None
        w.AreaValue.ToolTip = None
        w.LevelValue.ToolTip = None
        if len(pair) == 2:
            spatial, horizontal = distance(*pair)
            w.DistanceValue.Text = '{0:.3f} m'.format(horizontal)
            w.DistanceValue.ToolTip = '{0:.6f} m · calculados pelas coordenadas E/N originais'.format(horizontal)
        w.AreaValue.Text = '{0:.3f} m²'.format(polygon_area(self.points['area'])) if self.area_closed else '— m²'
        if self.area_closed:
            w.AreaValue.ToolTip = '{0:.6f} m² · projeção horizontal'.format(polygon_area(self.points['area']))
        if self.points['area'] and not self.area_closed:
            w.AreaValue.Text = '{0} pontos'.format(len(self.points['area']))
        w.LevelValue.Text = '{0.Z:.3f} m'.format(self.points['level'][0]) if self.points['level'] else '— m'
        if self.points['level']:
            w.LevelValue.ToolTip = 'E: {0.E:.6f} m\nN: {0.N:.6f} m\nZ: {0.Z:.6f} m'.format(self.points['level'][0])

    def plan_scale(self):
        w = self.window
        values = w.preview_values
        return min((w.PreviewHost.ActualWidth-36)/max(values['width'],0.001),
                   (w.PreviewHost.ActualHeight-36)/max(values['height'],0.001))*w.zoom

    def project(self, point):
        w = self.window
        if w.PreviewMode.SelectedIndex == 1:
            return w.terrain_view.project(point)
        scale = self.plan_scale()
        return (w.PreviewHost.ActualWidth/2 + (point.E-w.preview_values['anchor_e'])*scale+w.offset[0],
                w.PreviewHost.ActualHeight/2 - (point.N-w.preview_values['anchor_n'])*scale+w.offset[1])

    def pick(self, x, y):
        w = self.window
        if w.PreviewMode.SelectedIndex != 0:
            return None, 'As aferições são feitas somente na vista Planta.'
        if not (0 <= x <= w.PreviewHost.ActualWidth and 0 <= y <= w.PreviewHost.ActualHeight):
            return None, 'Clique em um vértice dentro da vista Planta.'
        scale = self.plan_scale()
        if scale <= 0:
            return None, 'Amplie a janela para selecionar os vértices.'
        east = w.preview_values['anchor_e']+(x-w.PreviewHost.ActualWidth/2-w.offset[0])/scale
        north = w.preview_values['anchor_n']-(y-w.PreviewHost.ActualHeight/2-w.offset[1])/scale
        point, ambiguous = snap_vertex(w.analysis.points, east, north, 8/scale, 2/scale)
        if ambiguous:
            return None, 'Há vértices muito próximos. Aumente o zoom antes de selecionar.'
        if point is None:
            return None, 'Nenhum vértice próximo. Aproxime o cursor de um ponto do levantamento.'
        return point, 'Vértice original · E: {0.E:.3f} · N: {0.N:.3f} · Z: {0.Z:.3f} m'.format(point)

    def hover(self, position):
        if self.active is None or self.window.analysis is None:
            return
        self.hovered, message = self.pick(position.X, position.Y)
        self.window.MeasureStatus.Text = message
        self.draw()

    def click(self, position):
        if self.active is None or self.window.analysis is None:
            return
        try:
            point, reference = self.pick(position.X, position.Y)
        except Exception:
            self.window.logger.exception('TopoBim: aferição da prévia')
            self.window.MeasureStatus.Text = 'Não foi possível medir nesse ponto. Confira o levantamento e tente novamente.'
            return
        if point is None:
            self.window.MeasureStatus.Text = reference
            return
        kind = self.active
        selected = self.points[kind]
        if any(distance(p, point)[1] < 0.0001 for p in selected):
            self.window.MeasureStatus.Text = 'Esse ponto já foi selecionado. Para fechar a área, use Concluir área.'
            return
        selected.append(point)
        self.hovered = None
        if kind == 'distance' and len(selected) == 2:
            self.active = None
            message = 'Distância horizontal concluída. '
        elif kind == 'level':
            self.active = None
            message = 'Cota consultada na referência do levantamento. '
        elif kind == 'area':
            message = '{0} vértices. Continue ou use Concluir área. '.format(len(selected))
        else:
            message = 'Ponto inicial marcado. Clique no ponto final. '
        self.window.MeasureStatus.Text = message + reference
        self.refresh()
        self.draw()

    def draw(self):
        w = self.window
        overlay = w.MeasureOverlay
        overlay.Children.Clear()
        if w.preview_values is None or w.PreviewMode.SelectedIndex != 0:
            return
        if self.hovered is not None:
            xy = self.project(self.hovered)
            halo = Ellipse()
            halo.Width = halo.Height = 14
            halo.Stroke, halo.StrokeThickness = w.FindResource('MarkerBrush'), 2
            Canvas.SetLeft(halo, xy[0]-7)
            Canvas.SetTop(halo, xy[1]-7)
            overlay.Children.Add(halo)
        for kind, brush, prefix in (('distance',w.FindResource('MarkerBrush'),'D'),
                                    ('area',w.FindResource('MarkerSecondaryBrush'),'A'),
                                    ('level',w.FindResource('MarkerBrush'),'Z')):
            positions = [(p,self.project(p)) for p in self.points[kind]]
            positions = [(p,xy) for p,xy in positions if xy is not None]
            if len(positions) > 1:
                line = Polyline()
                line.Stroke, line.StrokeThickness = brush, 2
                for p,xy in positions:
                    line.Points.Add(Point(*xy))
                if kind == 'area' and self.area_closed:
                    line.Points.Add(Point(*positions[0][1]))
                    line.Fill = w.FindResource('OverlayFillBrush')
                overlay.Children.Add(line)
            for index,(p,xy) in enumerate(positions):
                dot = Ellipse()
                dot.Width = dot.Height = 8
                dot.Fill, dot.Stroke = brush, Brushes.Black
                Canvas.SetLeft(dot,xy[0]-4)
                Canvas.SetTop(dot,xy[1]-4)
                overlay.Children.Add(dot)
                label = TextBlock()
                label.Text = '{0.Z:.3f} m'.format(p) if kind == 'level' else prefix+str(index+1)
                label.Foreground, label.Background = brush, Brushes.Black
                Canvas.SetLeft(label,xy[0]+5)
                Canvas.SetTop(label,xy[1]-18)
                overlay.Children.Add(label)
