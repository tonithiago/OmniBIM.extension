# -*- coding: utf-8 -*-
"""Modal pyRevit UI; Revit API calls stay on the command's UI thread."""
from __future__ import division, unicode_literals

import math
import os
import codecs
from System import Int64, Uri
from System.Collections.Generic import List
from System.Windows import Visibility, Point, RoutedEventHandler, SystemParameters
from System.Windows.Controls import Canvas, TextBlock, ComboBox, CheckBox, SelectionChangedEventHandler
from System.Windows.Controls.Primitives import Selector, ToggleButton
from System.Windows.Input import Cursors, MouseButtonState, Keyboard, Key
from System.Windows.Media import Brushes, Color, SolidColorBrush
from System.Windows.Shapes import Ellipse, Polyline
from Microsoft.Win32 import OpenFileDialog, SaveFileDialog
from pyrevit import forms, DB
import topobim_core as core
import topobim_revit as service
import topobim_floors as floors
import topobim_floor_geometry as floor_geometry
from topobim_view3d import TerrainView
from topobim_measure_ui import MeasurementTools

HERE = os.path.dirname(__file__)


def window_xaml(filename):
    # Load shared resources relative to this bundle, independent of Revit's cwd.
    with codecs.open(os.path.join(HERE, filename), 'r', 'utf-8') as stream:
        source = stream.read()
    return source.replace('Source="TopoBimTheme.xaml"',
                          'Source="{0}"'.format(Uri(os.path.join(HERE, 'TopoBimTheme.xaml')).AbsoluteUri))


def fit_work_area(window):
    # WPF work-area sizes are device-independent units, including Windows DPI.
    area = SystemParameters.WorkArea
    window.MinWidth = min(window.MinWidth, max(320, area.Width-32))
    window.MinHeight = min(window.MinHeight, max(320, area.Height-32))
    window.Width = max(window.MinWidth, min(window.Width, area.Width-32))
    window.Height = max(window.MinHeight, min(window.Height, area.Height-32))


class FloorLayerRow(object):
    def __init__(self, layer, regions, types, changed):
        self.Layer, self.Regions, self.Types = layer, regions, types
        self.Label = '{0} · {1} área(s) · {2:.2f} m²'.format(layer, len(regions), sum(floor_geometry.region_area(r) for r in regions))
        self._enabled, self._type = False, None
        self.changed = changed

    @property
    def Enabled(self):
        return self._enabled

    @Enabled.setter
    def Enabled(self, value):
        self._enabled = bool(value)
        self.changed(None, None)

    @property
    def SelectedType(self):
        return self._type

    @SelectedType.setter
    def SelectedType(self, value):
        self._type = value
        self.changed(None, None)


class OccurrenceRow(object):
    def __init__(self, index, row):
        self.Numero = index
        self.Tipo, self.Detalhe, self.Orientacao = row


class OccurrencesWindow(forms.WPFWindow):
    def __init__(self, owner, rows):
        forms.WPFWindow.__init__(self, window_xaml('Occurrences.xaml'), literal_string=True)
        fit_work_area(self)
        self.Owner = owner
        self.rows = rows
        self.reload_requested = False
        self.Table.ItemsSource = [OccurrenceRow(i, row) for i, row in enumerate(rows, 1)]
        self.Export.IsEnabled = bool(rows)
        self.Export.Click += self.export
        self.Reload.Click += self.reload_source
        self.CloseButton.Click += self.close_window

    def export(self, sender, event):
        dialog = SaveFileDialog()
        dialog.Filter = 'Relatório CSV|*.csv'
        dialog.FileName = 'TOPOBIM_ocorrencias.csv'
        if dialog.ShowDialog(self) == True:
            self.Owner.guard(lambda: core.write_occurrences(dialog.FileName, self.rows))

    def reload_source(self, sender, event):
        self.reload_requested = True
        self.Close()

    def close_window(self, sender, event):
        self.Close()


class TopoBimWindow(forms.WPFWindow):
    def __init__(self, uidoc, logger):
        self.ui, self.doc, self.logger = uidoc, uidoc.Document, logger
        self.busy = True
        self.created = False
        self.requested_review_view_id = None
        self.csv_path = None
        self.source = ''
        self.cad = None
        self.analysis = None
        self.preview_values = None
        self.preview_boundary = []
        self.read_errors = []
        self.geometry_error = None
        self.report = None
        self.floor_rows = []
        self.floor_issues = []
        self.zoom = 1.0
        self.offset = (0.0, 0.0)
        self.drag = None
        self.yaw, self.pitch = -60.0, 35.0
        self.preview_mesh_failed = False
        self.pending_pick = None
        forms.WPFWindow.__init__(self, window_xaml('TopoBim.xaml'), literal_string=True)
        fit_work_area(self)
        self.terrain_view = TerrainView(self.TerrainViewport)
        self.measurements = MeasurementTools(self)
        self.CadFiles.ItemsSource = service.choices(self.doc, DB.ImportInstance)
        self.TopoTypes.ItemsSource = service.choices(self.doc, DB.ToposolidType)
        self.Levels.ItemsSource = service.choices(self.doc, DB.Level)
        self.FloorCad.ItemsSource = service.choices(self.doc, DB.ImportInstance)
        self.FloorLevel.ItemsSource = service.choices(self.doc, DB.Level)
        self.FloorCad.SelectedIndex = 0
        self.FloorLevel.SelectedIndex = 0
        self.CadFiles.SelectedIndex = 0
        self.TopoTypes.SelectedIndex = 0
        self.Levels.SelectedIndex = 0
        self.CurrentLocation.Text = 'Localização ativa: ' + self.doc.ActiveProjectLocation.Name
        for control in (self.SourceMode, self.Separator, self.Units, self.CadFiles, self.CadCoordinates):
            control.SelectionChanged += self.input_changed
        for control in (self.EastColumn, self.NorthColumn, self.ZColumn):
            control.TextChanged += self.input_changed
        self.Header.Checked += self.input_changed
        self.Header.Unchecked += self.input_changed
        for control in (self.Datum, self.Zone, self.AnchorE, self.AnchorN, self.AnchorZ, self.Latitude, self.Longitude):
            control.TextChanged += self.settings_changed
        for control in (self.TopoTypes, self.Levels, self.Hemisphere, self.GeoMode, self.GeographicMode):
            control.SelectionChanged += self.settings_changed
        self.ChooseFile.Click += self.choose_file
        self.ReadSource.Click += self.read_source
        self.Reload.Click += self.read_source
        self.Layers.SelectionChanged += self.layers_changed
        self.ApplyLayers.Click += self.apply_layers
        self.ReviewIssues.Click += self.review_issues
        self.CreateFloors.Checked += self.floor_settings_changed
        self.CreateFloors.Unchecked += self.floor_settings_changed
        self.FloorCad.SelectionChanged += self.floor_source_changed
        self.FloorCoordinates.SelectionChanged += self.floor_source_changed
        self.FloorLevel.SelectionChanged += self.floor_settings_changed
        self.FindFloors.Click += self.find_floors
        # Explicit routed handlers are reliable for IronPython dynamic rows;
        # WPF cannot always write back through Python property descriptors.
        self.FloorTable.AddHandler(Selector.SelectionChangedEvent, SelectionChangedEventHandler(self.floor_type_changed))
        self.FloorTable.AddHandler(ToggleButton.CheckedEvent, RoutedEventHandler(self.floor_row_checked))
        self.FloorTable.AddHandler(ToggleButton.UncheckedEvent, RoutedEventHandler(self.floor_row_checked))
        self.Tabs.SelectionChanged += self.tab_changed
        self.Back.Click += self.go_back
        self.Next.Click += self.go_next
        self.SaveReport.Click += self.save_report
        self.ViewCreated.Click += self.view_created
        self.Fit.Click += self.fit
        self.PreviewMode.SelectionChanged += self.preview_mode_changed
        self.PreviewHost.SizeChanged += self.resize_preview
        self.PreviewHost.MouseWheel += self.preview_zoom
        self.PreviewHost.MouseLeftButtonDown += self.pan_start
        self.PreviewHost.MouseLeftButtonUp += self.pan_end
        self.PreviewHost.MouseMove += self.pan_move
        self.PreviewHost.LostMouseCapture += self.pan_lost
        self.PreviewKeyDown += self.preview_key
        self.busy = False

    def floor_settings_changed(self, sender, event):
        if self.busy or self.created:
            return
        self.FloorPanel.Visibility = Visibility.Visible if self.CreateFloors.IsChecked == True else Visibility.Collapsed
        self.Reviewed.IsChecked = False
        self.GeoConsent.IsChecked = False

    def floor_type_changed(self, sender, event):
        control = event.OriginalSource
        if isinstance(control, ComboBox) and isinstance(control.DataContext, FloorLayerRow):
            control.DataContext.SelectedType = control.SelectedItem

    def floor_row_checked(self, sender, event):
        control = event.OriginalSource
        if isinstance(control, CheckBox) and isinstance(control.DataContext, FloorLayerRow):
            control.DataContext.Enabled = control.IsChecked == True

    def floor_source_changed(self, sender, event):
        if self.busy or self.created:
            return
        self.floor_rows = []
        self.floor_issues = []
        self.FloorTable.ItemsSource = None
        self.FloorSummary.Text = 'Origem alterada. Identifique as áreas novamente.'
        self.FloorIssues.Text = ''
        self.floor_settings_changed(sender, event)

    def find_floors(self, sender, event):
        def identify():
            self.floor_source_changed(None, None)
            choice = self.FloorCad.SelectedItem
            if choice is None:
                raise ValueError('Vincule um DWG de modelo com os contornos de piso e reabra o TOPOBIM.')
            if self.FloorCoordinates.SelectedIndex == 2:
                if self.analysis is None:
                    raise ValueError('Leia e aplique os pontos do levantamento antes de identificar os pisos.')
                areas, issues = floors.read_registered_areas(self.doc, choice.Id, self.analysis.points)
            else:
                areas, issues = floors.read_areas(self.doc, choice.Id, self.FloorCoordinates.SelectedIndex == 0)
            types = floors.floor_choices(self.doc)
            if not types:
                raise ValueError('O projeto não contém tipos de piso. Carregue ou crie um tipo de piso no Revit.')
            self.floor_rows = [FloorLayerRow(layer, areas[layer], types, self.floor_settings_changed) for layer in sorted(areas)]
            self.floor_issues = issues
            self.FloorTable.ItemsSource = self.floor_rows
            self.FloorSummary.Text = '{0} camada(s) com áreas fechadas. Marque os layers de piso e escolha os tipos.'.format(len(areas))
            if hasattr(areas, 'registration'):
                self.FloorSummary.Text += ' Referência conferida: {0:.1%} dos vértices do levantamento coincidem com o layer {1} (2 mm).'.format(areas.registration['Coverage'], areas.registration['Layer'])
            self.FloorIssues.Text = '\n'.join(issues)
        self.guard(identify)

    def floor_settings(self):
        self.FloorTable.CommitEdit()
        if self.CreateFloors.IsChecked != True:
            return None
        selected = [row for row in self.floor_rows if row.Enabled]
        if not selected:
            raise ValueError('Identifique as áreas e marque pelo menos um layer de piso na aba Conferência.')
        if any(row.SelectedType is None for row in selected):
            raise ValueError('Escolha o tipo de piso de cada layer marcado.')
        level, cad = self.FloorLevel.SelectedItem, self.FloorCad.SelectedItem
        if level is None or cad is None:
            raise ValueError('Escolha o DWG e o nível de referência dos pisos.')
        if self.FloorCoordinates.SelectedIndex == 2 and self.analysis is None:
            raise ValueError('Leia o levantamento e identifique os pisos novamente.')
        return dict(CadId=cad.Id, Original=self.FloorCoordinates.SelectedIndex != 1,
                    RegisterSurvey=self.FloorCoordinates.SelectedIndex == 2,
                    SurveyPoints=list(self.analysis.points) if self.analysis is not None else [],
                    LevelId=level.Id, Layers=[(r.Layer, r.SelectedType.Id) for r in selected],
                    Signature=floors.signature({r.Layer: r.Regions for r in selected}, [r.Layer for r in selected]))

    def guard(self, action):
        try:
            action()
        except Exception as error:
            self.logger.exception('TOPOBIM')
            self.Status.Text = 'Confira os dados para continuar.'
            forms.alert(core.text_type(error), title='TOPOBIM')

    def reset_review(self):
        self.analysis = None
        self.preview_values = None
        self.preview_boundary = []
        self.geometry_error = None
        self.Reviewed.IsChecked = False
        self.GeoConsent.IsChecked = False
        self.zoom, self.offset, self.drag = 1.0, (0.0, 0.0), None
        self.yaw, self.pitch = -60.0, 35.0
        self.terrain_view.clear()
        self.preview_mesh_failed = False
        self.PreviewNote.Text = 'Leia o levantamento para visualizar o terreno em 3D.'
        self.Preview.Children.Clear()
        self.measurements.reset()
        for control in (self.UniquePointsValue, self.DuplicatesValue, self.ExtentValue,
                        self.ReliefValue, self.MinElevationValue, self.MaxElevationValue):
            control.Text = '—'
        self.Quality.Text = 'Aguardando leitura.'
        self.GeographicPreview.Text = 'Leia o levantamento para conferir a localização geográfica.'

    def input_changed(self, sender, event):
        if self.busy or self.created:
            return
        self.reset_review()
        self.floor_source_changed(None, None)
        self.read_errors = []
        self.cad = None
        self.source = ''
        self.busy = True
        self.Layers.ItemsSource = None
        self.LayerPanel.Visibility = Visibility.Collapsed
        self.busy = False
        csv_mode = self.SourceMode.SelectedIndex == 0
        self.CsvPanel.Visibility = Visibility.Visible if csv_mode else Visibility.Collapsed
        self.CadPanel.Visibility = Visibility.Collapsed if csv_mode else Visibility.Visible
        self.Status.Text = 'Configuração alterada. Clique em Ler e conferir.'

    def settings_changed(self, sender, event):
        if self.busy or self.created:
            return
        self.Reviewed.IsChecked = False
        self.GeoConsent.IsChecked = False
        self.AnchorPanel.Visibility = Visibility.Visible if self.GeoMode.SelectedIndex == 1 else Visibility.Collapsed
        self.ManualGeography.Visibility = Visibility.Visible if self.GeographicMode.SelectedIndex == 1 else Visibility.Collapsed
        self.update_geography()

    def creation_settings(self):
        new_location = self.GeoMode.SelectedIndex == 1
        settings = dict(NewLocation=new_location, Datum=self.Datum.Text.strip(),
                        Zone=int(self.Zone.Text), Hemisphere=('Sul', 'Norte')[self.Hemisphere.SelectedIndex],
                        East=core.number(self.AnchorE.Text) if new_location else 0.0,
                        North=core.number(self.AnchorN.Text) if new_location else 0.0,
                        Elevation=core.number(self.AnchorZ.Text) if new_location else 0.0,
                        GeographicMode='manual' if self.GeographicMode.SelectedIndex == 1 else 'utm')
        if settings['GeographicMode'] == 'manual':
            settings.update(Latitude=core.number(self.Latitude.Text), Longitude=core.number(self.Longitude.Text))
        return settings

    def update_geography(self):
        if not self.ready():
            self.GeographicPreview.Text = 'Leia e confira o levantamento para definir a localização geográfica.'
            return
        try:
            geographic = service.geographic_settings(self.doc, self.creation_settings())
            self.GeographicPreview.Text = ('Latitude: {Latitude:.8f}° · Longitude: {Longitude:.8f}°\n'
                                          'Origem compartilhada: E {East:.3f} · N {North:.3f} · Z {Elevation:.3f} m\n'
                                          'Os dois pontos base ficarão juntos na cota da superfície do terreno.').format(**geographic)
        except (ValueError, OverflowError) as error:
            self.GeographicPreview.Text = 'Confira a localização: ' + core.text_type(error)

    def choose_file(self, sender, event):
        def choose():
            dialog = OpenFileDialog()
            dialog.Filter = 'Pontos CSV/TXT|*.csv;*.txt'
            dialog.Multiselect = False
            if dialog.ShowDialog(self) != True:
                return
            self.csv_path = dialog.FileName
            self.FileLabel.Text = self.csv_path
            self.input_changed(None, None)
            detected = core.detect_columns(self.csv_path)
            if detected:
                self.busy = True
                try:
                    separator, columns = detected
                    self.Separator.SelectedIndex = (';', ',', '\t').index(separator)
                    for field, index in zip((self.EastColumn, self.NorthColumn, self.ZColumn), columns):
                        field.Text = str(index + 1)
                    self.Header.IsChecked = True
                finally:
                    self.busy = False
            self.Status.Text = 'Arquivo selecionado. Confira colunas e unidades antes de ler.'
        self.guard(choose)

    def read_source(self, sender, event):
        self.guard(self.load_source)

    def load_source(self):
        self.input_changed(None, None)
        if self.SourceMode.SelectedIndex == 0:
            if not self.csv_path:
                raise ValueError('Selecione um arquivo CSV/TXT.')
            columns = tuple(int(c.Text) - 1 for c in (self.EastColumn, self.NorthColumn, self.ZColumn))
            result = core.read_points(self.csv_path, (';', ',', '\t')[self.Separator.SelectedIndex],
                                      columns, self.Header.IsChecked == True,
                                      (1.0, 0.01, 0.001, 0.3048)[self.Units.SelectedIndex])
            self.read_errors = result.errors
            self.source = self.csv_path
            self.set_analysis(result.points)
        else:
            choice = self.CadFiles.SelectedItem
            if choice is None:
                raise ValueError('Nenhum DWG disponível. Vincule-o ao projeto e reabra o TOPOBIM.')
            original = self.CadCoordinates.SelectedIndex == 0
            self.cad = service.read_cad(self.doc, choice.Id, original)
            self.source = 'DWG: {0} / {1}'.format(choice.Label, 'WCS original' if original else 'compartilhadas atuais')
            self.busy = True
            try:
                self.Layers.ItemsSource = sorted(set(p.layer for p in self.cad))
                self.Layers.UnselectAll()
                self.LayerPanel.Visibility = Visibility.Visible
            finally:
                self.busy = False
            self.Status.Text = 'Marque uma ou mais camadas do levantamento e aplique a seleção.'
        self.Tabs.SelectedIndex = 1

    def layers_changed(self, sender, event):
        if self.busy or self.cad is None:
            return
        self.reset_review()
        self.Status.Text = 'Seleção alterada. Clique em Aplicar camadas selecionadas.'

    def apply_layers(self, sender, event):
        def apply():
            if self.cad is None:
                return
            self.reset_review()
            layers = set(self.Layers.SelectedItems)
            if not layers:
                raise ValueError('Marque pelo menos uma camada do levantamento.')
            self.set_analysis([p.point for p in self.cad if p.layer in layers])
        self.guard(apply)

    def set_analysis(self, points):
        self.terrain_view.clear()
        self.preview_mesh_failed = False
        self.measurements.reset()
        self.analysis = core.deduplicate(points)
        try:
            core.validate_analysis(self.analysis)
        except ValueError as error:
            self.geometry_error = core.text_type(error)
        if self.analysis.points:
            values = core.summary(self.analysis)
            self.preview_values = values
            self.preview_boundary = core.hull(self.analysis.points)
            self.UniquePointsValue.Text = '{count}'.format(**values)
            self.DuplicatesValue.Text = '{duplicates}'.format(**values)
            self.ExtentValue.Text = '{width:.2f} × {height:.2f} m'.format(**values)
            self.ReliefValue.Text = '{relief:.3f} m'.format(**values)
            self.MinElevationValue.Text = '{min_z:.3f} m'.format(**values)
            self.MaxElevationValue.Text = '{max_z:.3f} m'.format(**values)
            self.busy = True
            try:
                self.AnchorE.Text = '{0:.3f}'.format(values['anchor_e'])
                self.AnchorN.Text = '{0:.3f}'.format(values['anchor_n'])
                self.AnchorZ.Text = '0.000'
                self.GeoMode.SelectedIndex = 0
                self.AnchorPanel.Visibility = Visibility.Collapsed
            finally:
                self.busy = False
            flat = '\nAtenção: pontos na mesma cota. Confira se o DWG está em Z=0.' if values['relief'] < 0.001 else ''
        else:
            flat = ''
        self.Quality.Text = '{0} erro(s) de leitura · {1} aviso(s) de cota.{2}{3}'.format(
            len(self.read_errors), len(self.analysis.conflicts),
            '\n' + self.geometry_error if self.geometry_error else '', flat)
        if not self.read_errors and not self.analysis.conflicts and not self.geometry_error and not flat:
            self.Quality.Text = 'Conferência concluída · Nenhuma ocorrência encontrada.'
        self.Status.Text = ('Corrija os erros e releia a origem.' if self.read_errors or self.geometry_error
                            else 'Confira os pontos, as ocorrências e a referência espacial.')
        self.measurements.refresh()
        self.draw()
        self.update_geography()

    def review_issues(self, sender, event):
        conflicts = self.analysis.conflicts if self.analysis else []
        rows = core.occurrence_rows(self.read_errors, conflicts, self.geometry_error)
        if self.CreateFloors.IsChecked == True:
            rows.extend(('DWG / pisos', issue, 'Confira os contornos e layers na aba Conferência.') for issue in self.floor_issues)
        window = OccurrencesWindow(self, rows)
        window.ShowDialog()
        if window.reload_requested:
            self.read_source(None, None)

    def ready(self):
        return self.analysis is not None and not self.read_errors and not self.geometry_error

    def tab_changed(self, sender, event):
        if self.busy or event.Source != self.Tabs:
            return
        index = self.Tabs.SelectedIndex
        if index == 2:
            if not self.ready():
                self.Tabs.SelectedIndex = 1
                self.Status.Text = 'Leia e confira o levantamento; corrija os erros antes de criar.'
                return
            self.guard(self.prepare_location)
        self.Back.IsEnabled = index > 0 and not self.created
        self.Next.Content = 'Criar terreno' if index == 2 else 'Continuar'
        if index == 1:
            self.draw()

    def prepare_location(self):
        if self.GeoMode.SelectedIndex == 0 and service.needs_location(self.doc, self.analysis):
            self.GeoMode.SelectedIndex = 1
            self.Status.Text = 'Terreno distante: confira e confirme as novas coordenadas de Terreno Padrão.'
        self.update_geography()

    def go_back(self, sender, event):
        self.Tabs.SelectedIndex = max(0, self.Tabs.SelectedIndex - 1)

    def go_next(self, sender, event):
        if self.created:
            self.Close()
        elif self.Tabs.SelectedIndex < 2:
            self.Tabs.SelectedIndex += 1
        else:
            self.guard(self.create)

    def create(self):
        if not self.ready():
            raise ValueError('Confira o levantamento e corrija os erros antes de criar.')
        floor_settings = self.floor_settings()
        if self.Reviewed.IsChecked != True:
            raise ValueError('Marque a confirmação de conferência dos dados.')
        if self.GeoMode.SelectedIndex == 0 and service.needs_location(self.doc, self.analysis):
            self.prepare_location()
            raise ValueError('Foram sugeridas novas coordenadas para Terreno Padrão. Confira os valores e confirme a alteração.')
        new_location = self.GeoMode.SelectedIndex == 1
        if new_location and self.GeoConsent.IsChecked != True:
            raise ValueError('Confirme a alteração da localização compartilhada.')
        topo_type, level = self.TopoTypes.SelectedItem, self.Levels.SelectedItem
        if topo_type is None or level is None:
            raise ValueError('O projeto precisa de um nível e de um tipo de sólido topográfico.')
        settings = self.creation_settings()
        self.Next.IsEnabled = False
        self.Status.Text = 'Criando e conferindo o sólido topográfico…'
        try:
            element_id, report = service.create(self.doc, self.analysis, topo_type.Id, level.Id, settings, self.source, floor_settings)
        finally:
            self.Next.IsEnabled = True
        # Mark committed before any optional UI/report work: never create twice.
        self.created, self.report = True, report
        self.Tabs.IsEnabled = False
        self.Back.IsEnabled = False
        self.Next.Content = 'Concluir'
        self.SaveReport.Visibility = Visibility.Visible
        self.Status.Text = 'Terreno criado · elemento {0}. Pontos base juntos na cota {1:.3f} m.'.format(
            element_id, report['BasePoints']['SharedPositionMetres'][2])
        if report.get('Floors'):
            self.Status.Text += ' {0} piso(s) criado(s).'.format(len(report['Floors']))
        if report.get('ReviewViewId'):
            self.ViewCreated.Visibility = Visibility.Visible
        try:
            ids = List[DB.ElementId]()
            ids.Add(element_id)
            for floor_report in report.get('Floors',[]):
                ids.Add(DB.ElementId(Int64.Parse(floor_report['ElementId'])))
            self.ui.Selection.SetElementIds(ids)
        except Exception as error:
            self.logger.exception('TOPOBIM: seleção após criação')
            forms.alert('Terreno criado, mas não foi possível selecioná-lo: ' + core.text_type(error), title='TOPOBIM')

    def view_created(self,sender,event):
        self.requested_review_view_id = self.report['ReviewViewId']
        self.Close()

    def save_report(self, sender, event):
        dialog = SaveFileDialog()
        dialog.Filter = 'Relatório JSON|*.json'
        dialog.FileName = 'TopoBim_relatorio.json'
        if dialog.ShowDialog(self) == True:
            try:
                core.write_report(dialog.FileName, self.report)
                self.Status.Text = 'Terreno criado. Relatório salvo.'
            except Exception as error:
                self.logger.exception('TOPOBIM: relatório após criação')
                forms.alert('O terreno foi criado. Não foi possível salvar o relatório: ' + core.text_type(error), title='TOPOBIM')

    def fit(self, sender, event):
        self.zoom, self.offset = 1.0, (0.0, 0.0)
        self.yaw, self.pitch = -60.0, 35.0
        self.draw()

    def preview_mode_changed(self, sender, event):
        if self.busy:
            return
        is_3d = self.PreviewMode.SelectedIndex == 1
        if is_3d and self.measurements.active is not None:
            self.measurements.navigate()
        self.Preview.Visibility = Visibility.Collapsed if is_3d else Visibility.Visible
        self.TerrainViewport.Visibility = Visibility.Visible if is_3d else Visibility.Collapsed
        self.ViewLabel.Visibility = Visibility.Visible if is_3d else Visibility.Collapsed
        self.PreviewNote.Visibility = Visibility.Visible if is_3d else Visibility.Collapsed
        self.PreviewHint.Text = ('Arraste: girar · Shift + arraste: mover · roda: zoom · duplo clique: enquadrar'
                                 if is_3d else 'Planta E/N · roda: zoom · arraste: mover · duplo clique: enquadrar')
        self.PreviewNote.Text = 'Leia o levantamento para visualizar o terreno em 3D.'
        self.fit(sender, event)

    def resize_preview(self, sender, event):
        if not self.busy:
            self.draw()

    def preview_zoom(self, sender, event):
        if self.analysis is None:
            return
        self.pending_pick = None
        mouse = event.GetPosition(self.PreviewHost)
        cx, cy = self.PreviewHost.ActualWidth / 2, self.PreviewHost.ActualHeight / 2
        new_zoom = min(100.0, max(0.1, self.zoom * math.pow(1.2, event.Delta / 120.0)))
        ratio = new_zoom / self.zoom
        self.offset = (mouse.X - cx - (mouse.X - cx - self.offset[0]) * ratio,
                       mouse.Y - cy - (mouse.Y - cy - self.offset[1]) * ratio)
        self.zoom = new_zoom
        self.draw()
        event.Handled = True

    def pan_start(self, sender, event):
        self.pending_pick = None
        if event.ClickCount == 2 and self.measurements.active is None:
            self.fit(sender, event)
        elif event.ClickCount == 2:
            event.Handled = True
            return
        else:
            self.drag = event.GetPosition(self.PreviewHost)
            if self.measurements.active is not None:
                self.pending_pick = self.drag
            self.PreviewHost.CaptureMouse()
            self.PreviewHost.Cursor = Cursors.SizeAll
        event.Handled = True

    def pan_move(self, sender, event):
        if self.drag is None or event.LeftButton != MouseButtonState.Pressed:
            self.measurements.hover(event.GetPosition(self.PreviewHost))
            return
        point = event.GetPosition(self.PreviewHost)
        if self.pending_pick is not None:
            if math.hypot(point.X-self.pending_pick.X, point.Y-self.pending_pick.Y) < 4:
                return
            self.pending_pick = None
        dx, dy = point.X - self.drag.X, point.Y - self.drag.Y
        shift = Keyboard.IsKeyDown(Key.LeftShift) or Keyboard.IsKeyDown(Key.RightShift)
        if self.PreviewMode.SelectedIndex == 1 and not shift:
            self.yaw = (self.yaw - dx * 0.5) % 360
            self.pitch = min(85.0, max(-85.0, self.pitch + dy * 0.5))
        else:
            self.offset = (self.offset[0] + dx, self.offset[1] + dy)
        self.drag = point
        self.draw()

    def pan_end(self, sender, event):
        pending = self.pending_pick
        self.PreviewHost.ReleaseMouseCapture()
        self.pan_lost(sender, event)
        if pending is not None:
            self.measurements.click(pending)

    def pan_lost(self, sender, event):
        self.drag = None
        self.pending_pick = None
        self.PreviewHost.Cursor = Cursors.Cross if self.measurements.active else Cursors.Hand

    def preview_key(self, sender, event):
        if event.Key == Key.Escape and self.measurements.active is not None:
            self.pending_pick = None
            self.measurements.navigate()
            event.Handled = True

    def draw_3d(self):
        if self.preview_mesh_failed:
            self.PreviewNote.Text = 'Não foi possível montar a prévia 3D. Confira os pontos na vista Planta.'
            return
        if self.analysis is None or not self.analysis.points:
            return
        if not self.terrain_view.ready:
            try:
                if not self.terrain_view.build(self.analysis.points):
                    raise ValueError('São necessários pontos que formem uma superfície.')
            except Exception:
                self.preview_mesh_failed = True
                self.logger.exception('TopoBim: prévia 3D')
                self.PreviewNote.Text = 'Não foi possível montar a prévia 3D. Confira os pontos na vista Planta.'
                return
        count = self.terrain_view.point_count
        sampled = ' · {0} de {1} pontos na prévia'.format(count, len(self.analysis.points)) if count < len(self.analysis.points) else ''
        self.PreviewNote.Text = 'Superfície ilustrativa{0}. A triangulação final será definida pelo Revit.'.format(sampled)
        self.terrain_view.camera(self.PreviewHost.ActualWidth, self.PreviewHost.ActualHeight,
                                 self.zoom, self.offset, self.yaw, self.pitch)

    def draw(self):
        if self.PreviewMode.SelectedIndex == 1:
            self.draw_3d()
            self.measurements.draw()
            return
        self.Preview.Children.Clear()
        if self.analysis is None or not self.analysis.points or self.Preview.ActualWidth < 50:
            return
        points = self.analysis.points
        values = self.preview_values
        width, height = self.Preview.ActualWidth, self.Preview.ActualHeight
        scale = min((width - 36) / max(values['width'], 0.001),
                    (height - 36) / max(values['height'], 0.001)) * self.zoom

        def mapped(point):
            return Point(width / 2 + (point.E - values['anchor_e']) * scale + self.offset[0],
                         height / 2 - (point.N - values['anchor_n']) * scale + self.offset[1])
        outline = Polyline()
        outline.Stroke = Brushes.LightGray
        outline.StrokeThickness = 1.5
        boundary = self.preview_boundary
        if boundary:
            for point in boundary + boundary[:1]:
                outline.Points.Add(mapped(point))
        self.Preview.Children.Add(outline)
        # Only the display is sampled. All accepted points go to Toposolid.Create.
        stride = max(1, int(math.ceil(len(points) / 3000.0)))
        for point in points[::stride]:
            position = mapped(point)
            if not (0 <= position.X <= width and 0 <= position.Y <= height):
                continue
            shade = int(100 + 155 * (point.Z - values['min_z']) / max(0.001, values['relief']))
            dot = Ellipse()
            dot.Width, dot.Height = 3.5, 3.5
            dot.Fill = SolidColorBrush(Color.FromRgb(shade, shade, shade))
            Canvas.SetLeft(dot, position.X - 1.75)
            Canvas.SetTop(dot, position.Y - 1.75)
            self.Preview.Children.Add(dot)
        north = TextBlock()
        north.Text, north.Foreground = 'N ↑', Brushes.White
        Canvas.SetRight(north, 8)
        Canvas.SetTop(north, 8)
        self.Preview.Children.Add(north)
        self.measurements.draw()
