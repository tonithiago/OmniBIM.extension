using System.IO;
using Line = System.Windows.Shapes.Line;
using Ellipse = System.Windows.Shapes.Ellipse;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Microsoft.Win32;
using System.Globalization;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using WPoint = System.Windows.Point;
using WPolyline = System.Windows.Shapes.Polyline;
using WColor = System.Windows.Media.Color;

namespace TopoBim;

public partial class MainWindow : Window
{
    private readonly UIDocument ui;
    private readonly Document doc;
    private string? csv;
    private string source = "";
    private int page = 1;
    private Analysis? analysis;
    private List<string> readErrors = new();
    private List<CadPoint>? cad;
    private bool changingLayers;
    private double previewZoom = 1;
    private System.Windows.Vector previewOffset;
    private WPoint? previewDrag;
    private bool initialized;
    private bool created;
    private string report = "";

    public MainWindow(UIDocument ui)
    {
        this.ui = ui; doc = ui.Document;
        InitializeComponent();
        Separator.SelectedIndex = 0; Units.SelectedIndex = 0; Hemisphere.SelectedIndex = 0;
        GeoMode.SelectedIndex = 0;
        CadFiles.ItemsSource = RevitService.Choices(doc, typeof(ImportInstance));
        TopoTypes.ItemsSource = RevitService.Choices(doc, typeof(ToposolidType));
        Levels.ItemsSource = RevitService.Choices(doc, typeof(Level));
        TopoTypes.SelectedIndex = 0; Levels.SelectedIndex = 0; CadFiles.SelectedIndex = 0;
        VersionLabel.Text = $"REVIT {doc.Application.VersionNumber}   •   v0.2 / VALIDAÇÃO";
        CurrentLocation.Text = "Localização ativa: " + doc.ActiveProjectLocation.Name;
        initialized = true;
        foreach (var field in new[] { EastColumn, NorthColumn, ZColumn }) field.TextChanged += (_, _) => ResetReview();
        Separator.SelectionChanged += (_, _) => ResetReview();
        Units.SelectionChanged += (_, _) => ResetReview();
        Header.Checked += (_, _) => ResetReview(); Header.Unchecked += (_, _) => ResetReview();
        Navigate(1);
    }

    private void Guard(Action action)
    {
        try { action(); }
        catch (Exception ex)
        {
            Status.Text = "Confira os dados para continuar.";
            MessageBox.Show(this, ex.Message, "TOPOBIM", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }
    private void ResetReview()
    {
        previewZoom = 1; previewOffset = new System.Windows.Vector(); previewDrag = null;
        analysis = null; Reviewed.IsChecked = false; GeoConsent.IsChecked = false;
        Preview.Children.Clear(); Issues.Text = "";
        foreach (var field in new[] { PointCountValue, DuplicateCountValue, ExtentValue, MinElevationValue, MaxElevationValue, ReliefValue }) field.Text = "—";
        DataQualityValue.Text = "Aguardando leitura";
    }
    private void Navigate(int step)
    {
        if (step > 1 && analysis == null && !(step == 2 && cad != null)) { Status.Text = "Leia o CSV/TXT ou DWG antes de continuar."; return; }
        if (step == 3 && (analysis == null || readErrors.Count > 0)) { Status.Text = "Corrija os erros do levantamento antes de criar."; return; }
        if (step == 3) PrepareSurveyLocation();
        page = step;
        Page1.Visibility = step == 1 ? System.Windows.Visibility.Visible : System.Windows.Visibility.Collapsed;
        Page2.Visibility = step == 2 ? System.Windows.Visibility.Visible : System.Windows.Visibility.Collapsed;
        Page3.Visibility = step == 3 ? System.Windows.Visibility.Visible : System.Windows.Visibility.Collapsed;
        var buttons = new[] { Nav1, Nav2, Nav3 };
        for (int i = 0; i < buttons.Length; i++)
        {
            buttons[i].Background = new SolidColorBrush(i + 1 == step ? WColor.FromRgb(24, 24, 24) : Colors.White);
            buttons[i].Foreground = new SolidColorBrush(i + 1 == step ? Colors.White : WColor.FromRgb(80, 80, 80));
        }
        Back.IsEnabled = step > 1;
        Next.Content = step == 3 ? "Criar terreno" : "Continuar →";
        if (step == 2) Dispatcher.BeginInvoke(new Action(Draw));
    }
    private void Step1(object sender, RoutedEventArgs e) => Navigate(1);
    private void Step2(object sender, RoutedEventArgs e) => Navigate(2);
    private void Step3(object sender, RoutedEventArgs e) => Navigate(3);
    private void GoBack(object sender, RoutedEventArgs e) => Navigate(Math.Max(1, page - 1));
    private void GoNext(object sender, RoutedEventArgs e)
    {
        if (created) { Close(); return; }
        if (page < 3) Navigate(page + 1); else Guard(Create);
    }
    private void ChooseFile(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Filter = "Pontos CSV/TXT|*.csv;*.txt", Multiselect = false };
        if (dialog.ShowDialog(this) == true)
        {
            csv = dialog.FileName; FileLabel.Text = csv; ResetReview();
            DetectCsvColumns(csv);
            Status.Text = "Arquivo selecionado. Configure as colunas e clique em Ler e conferir.";
        }
    }
    private void DetectCsvColumns(string path)
    {
        var first = File.ReadLines(path).FirstOrDefault(line => !string.IsNullOrWhiteSpace(line));
        if (first == null) return;
        foreach (var separator in new[] { ';', ',', '\t' })
        {
            List<string> fields;
            try { fields = Survey.Split(first, separator); } catch (FormatException) { continue; }
            var names = fields.Select(f => f.Trim().Trim('\uFEFF').ToUpperInvariant()).ToList();
            int east = names.FindIndex(n => new[] { "X", "E", "ESTE", "LESTE", "EASTING", "X_LESTE", "X_ESTE" }.Contains(n));
            int north = names.FindIndex(n => new[] { "Y", "N", "NORTE", "NORTHING", "Y_NORTE" }.Contains(n));
            int elevation = names.FindIndex(n => new[] { "Z", "COTA", "ELEVACAO", "ELEVAÇÃO", "ELEVATION", "Z_COTA" }.Contains(n));
            if (east < 0 || north < 0 || elevation < 0) continue;
            Separator.SelectedIndex = separator == ';' ? 0 : separator == ',' ? 1 : 2;
            EastColumn.Text = (east + 1).ToString(); NorthColumn.Text = (north + 1).ToString(); ZColumn.Text = (elevation + 1).ToString();
            Header.IsChecked = true;
            return;
        }
    }
    private void LoadCsv(object sender, RoutedEventArgs e) => Guard(() =>
    {
        ResetReview(); cad = null;
        if (csv == null) throw new ArgumentException("Selecione um arquivo CSV/TXT.");
        char separator = new[] { ';', ',', '\t' }[Separator.SelectedIndex];
        double factor = new[] { 1d, .01, .001, .3048 }[Units.SelectedIndex];
        var result = Survey.Read(csv, separator, int.Parse(EastColumn.Text) - 1, int.Parse(NorthColumn.Text) - 1,
            int.Parse(ZColumn.Text) - 1, Header.IsChecked == true, factor);
        readErrors = result.Errors; source = csv;
        changingLayers = true; Layers.ItemsSource = null; changingLayers = false;
        SetAnalysis(result.Points);
        Navigate(2);
    });
    private void LoadCad(object sender, RoutedEventArgs e) => Guard(() =>
    {
        ResetReview();
        if (CadFiles.SelectedItem is not Choice choice) throw new ArgumentException("Nenhum DWG disponível. Vincule um arquivo ao projeto e reabra o plugin.");
        cad = RevitService.ReadCad(doc, choice.Id, CadCoordinates.SelectedIndex == 0);
        readErrors.Clear(); source = "DWG: " + choice.Name + " / instância " + choice.Id + (CadCoordinates.SelectedIndex == 0 ? " / WCS original" : " / coordenadas compartilhadas atuais");
        changingLayers = true;
        Layers.ItemsSource = cad.Select(p => p.Layer).Distinct().OrderBy(s => s).ToList();
        Layers.UnselectAll(); changingLayers = false;
        Navigate(2);
        Status.Text = "Marque a layer do levantamento em Camadas de origem e aplique a seleção.";
    });
    private void LayerChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!initialized || changingLayers || cad == null) return;
        ResetReview();
        Status.Text = $"{Layers.SelectedItems.Count} camada(s) marcada(s). Clique em Aplicar camadas selecionadas.";
    }
    private void CadCoordinatesChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!initialized || cad == null) return;
        LoadCad(sender, e);
    }
    private void ApplyLayers(object sender, RoutedEventArgs e) => Guard(() =>
    {
        if (cad == null) { Status.Text = "CSV: são usadas todas as coordenadas lidas; não há layers para selecionar."; return; }
        ResetReview();
        var layers = Layers.SelectedItems.Cast<string>().ToHashSet();
        if (layers.Count == 0) { Status.Text = "Marque pelo menos uma layer do levantamento."; return; }
        SetAnalysis(cad.Where(p => layers.Contains(p.Layer)).Select(p => p.Point).ToList());
    });
    private void SetAnalysis(List<SurveyPoint> points)
    {
        analysis = Survey.Analyze(points);
        var p = analysis.Points;
        double width = p.Max(q => q.E) - p.Min(q => q.E), height = p.Max(q => q.N) - p.Min(q => q.N);
        double relief = p.Max(q => q.Z) - p.Min(q => q.Z);
        var format = CultureInfo.GetCultureInfo("pt-BR");
        PointCountValue.Text = p.Count.ToString("N0", format);
        DuplicateCountValue.Text = analysis.Duplicates.ToString("N0", format);
        ExtentValue.Text = $"{width.ToString("N2", format)} × {height.ToString("N2", format)} m";
        MinElevationValue.Text = p.Min(q => q.Z).ToString("N2", format) + " m";
        MaxElevationValue.Text = p.Max(q => q.Z).ToString("N2", format) + " m";
        ReliefValue.Text = relief.ToString("N2", format) + " m";
        int errorCount = readErrors.Count;
        int warningCount = analysis.Conflicts.Count;
        DataQualityValue.Text = errorCount > 0 ? $"{errorCount.ToString("N0", format)} erro(s) de leitura para revisar" : warningCount > 0 ? $"{warningCount.ToString("N0", format)} diferença(s) de cota aceita(s) • criação liberada" : "Leitura sem erros • confira os pontos de controle";
        var issues = new List<string>();
        issues.AddRange(readErrors); issues.AddRange(analysis.Conflicts.Select(s => "Aviso aceito — primeira cota mantida: " + s));
        if (relief < .001) issues.Add("ATENÇÃO: todos os pontos estão na mesma cota. Verifique se o DWG está em Z=0.");
        issues.Add("Limite automático: fecho convexo. Divisas côncavas e linhas de quebra não são preservadas nesta versão.");
        Issues.Text = string.Join("\n", issues.Take(80));
        if (issues.Count > 80) Issues.Text += $"\n… mais {issues.Count - 80} ocorrências. Clique no aviso de ocorrências para abrir a lista completa.";
        AnchorE.Text = ((p.Min(q => q.E) + p.Max(q => q.E)) / 2).ToString("F3", CultureInfo.InvariantCulture);
        AnchorN.Text = ((p.Min(q => q.N) + p.Max(q => q.N)) / 2).ToString("F3", CultureInfo.InvariantCulture);
        // Preserva Z absoluto: não subtrai a menor cota do levantamento.
        AnchorZ.Text = "0.000";
        Status.Text = readErrors.Count == 0 ? "Leitura concluída. Confira a referência e o contorno." : "Há erros que precisam ser resolvidos antes da criação.";
        Draw();
    }
    public sealed record OccurrenceRow(int Numero, string Tipo, string Detalhe, string Orientacao);

    private List<OccurrenceRow> Occurrences()
    {
        var rows = new List<OccurrenceRow>();
        foreach (var error in readErrors)
            rows.Add(new(rows.Count + 1, "Erro de leitura", error,
                "Corrija a linha no arquivo de origem. Confira separador, cabeçalho, colunas E/N/Z e números sem separadores de milhar. Depois releia os dados."));
        if (analysis != null)
            foreach (var conflict in analysis.Conflicts)
                rows.Add(new(rows.Count + 1, "Aviso aceito", conflict,
                    "Diferença de cota aceita automaticamente na mesma posição XY (grade de 1 mm). A primeira cota lida foi mantida e a posterior foi ignorada. Este aviso não bloqueia a criação e não exige correção."));
        return rows;
    }

    private void ReviewOccurrences(object sender, RoutedEventArgs e) => Guard(() =>
    {
        var rows = Occurrences();
        var window = new Window { Title = "TOPOBIM • Revisão de ocorrências", Owner = this,
            Width = 1040, Height = 650, MinWidth = 760, MinHeight = 420,
            WindowStartupLocation = WindowStartupLocation.CenterOwner, Background = Brushes.White };
        var layout = new DockPanel { Margin = new Thickness(24) };
        var heading = new TextBlock { Text = $"{rows.Count:N0} ocorrência(s) para revisar", FontSize = 22,
            FontWeight = FontWeights.SemiBold, Margin = new Thickness(0, 0, 0, 10) };
        DockPanel.SetDock(heading, Dock.Top); layout.Children.Add(heading);
        var instruction = new TextBlock { Text = "Revise os detalhes e corrija a origem. Somente erros de leitura bloqueiam a criação. Diferenças de cota são avisos aceitos: a primeira cota lida é mantida.",
            TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 16) };
        DockPanel.SetDock(instruction, Dock.Top); layout.Children.Add(instruction);
        var actions = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 16, 0, 0) };
        var export = new Button { Content = "Exportar relatório CSV", IsEnabled = rows.Count > 0 };
        export.Click += (_, _) => Guard(() =>
        {
            var dialog = new SaveFileDialog { Filter = "Relatório CSV|*.csv", FileName = "TOPOBIM_ocorrencias.csv" };
            if (dialog.ShowDialog(window) != true) return;
            static string Quote(string value) => "\"" + value.Replace("\"", "\"\"") + "\"";
            var lines = new List<string> { "Número;Tipo;Detalhe;Orientação" };
            lines.AddRange(rows.Select(r => $"{r.Numero};{Quote(r.Tipo)};{Quote(r.Detalhe)};{Quote(r.Orientacao)}"));
            File.WriteAllLines(dialog.FileName, lines, new System.Text.UTF8Encoding(true));
        });
        actions.Children.Add(export);
        var reload = new Button { Content = "Reler dados", IsEnabled = csv != null || cad != null };
        reload.Click += (_, _) => { window.Close(); if (cad != null) LoadCad(sender, e); else LoadCsv(sender, e); };
        actions.Children.Add(reload);
        var close = new Button { Content = "Fechar" }; close.Click += (_, _) => window.Close(); actions.Children.Add(close);
        DockPanel.SetDock(actions, Dock.Bottom); layout.Children.Add(actions);
        var table = new DataGrid { ItemsSource = rows, IsReadOnly = true, AutoGenerateColumns = false,
            CanUserAddRows = false, CanUserDeleteRows = false, EnableRowVirtualization = true,
            RowBackground = Brushes.White, AlternatingRowBackground = new SolidColorBrush(WColor.FromRgb(245, 245, 245)),
            HeadersVisibility = DataGridHeadersVisibility.Column, SelectionMode = DataGridSelectionMode.Single };
        var wrap = new Style(typeof(TextBlock)); wrap.Setters.Add(new Setter(TextBlock.TextWrappingProperty, TextWrapping.Wrap));
        wrap.Setters.Add(new Setter(TextBlock.MarginProperty, new Thickness(6)));
        void Column(string title, string property, double width) => table.Columns.Add(new DataGridTextColumn {
            Header = title, Binding = new System.Windows.Data.Binding(property), Width = new DataGridLength(width, DataGridLengthUnitType.Star), ElementStyle = wrap });
        Column("Nº", "Numero", .35); Column("Tipo", "Tipo", 1); Column("Linha / coordenadas e problema", "Detalhe", 2); Column("Como revisar", "Orientacao", 2.4);
        layout.Children.Add(table); window.Content = layout; window.ShowDialog();
    });

    private void FitPreview(object sender, RoutedEventArgs e)
    {
        previewZoom = 1; previewOffset = new System.Windows.Vector(); Draw();
    }
    private void PreviewZoom(object sender, System.Windows.Input.MouseWheelEventArgs e)
    {
        if (analysis == null) return;
        var mouse = e.GetPosition(Preview);
        var center = new WPoint(Preview.ActualWidth / 2, Preview.ActualHeight / 2);
        double next = Math.Clamp(previewZoom * Math.Pow(1.2, e.Delta / 120.0), .1, 100);
        double ratio = next / previewZoom;
        previewOffset = (mouse - center) - ((mouse - center) - previewOffset) * ratio;
        previewZoom = next; Draw(); e.Handled = true;
    }
    private void PreviewPanStart(object sender, System.Windows.Input.MouseButtonEventArgs e)
    {
        if (e.ClickCount == 2) { FitPreview(sender, e); e.Handled = true; return; }
        previewDrag = e.GetPosition(Preview); Preview.CaptureMouse();
        Preview.Cursor = System.Windows.Input.Cursors.SizeAll; e.Handled = true;
    }
    private void PreviewPanMove(object sender, System.Windows.Input.MouseEventArgs e)
    {
        if (previewDrag is not WPoint previous || e.LeftButton != System.Windows.Input.MouseButtonState.Pressed) return;
        var current = e.GetPosition(Preview); previewOffset += current - previous; previewDrag = current; Draw();
    }
    private void PreviewPanEnd(object sender, System.Windows.Input.MouseButtonEventArgs e)
    {
        Preview.ReleaseMouseCapture(); previewDrag = null; Preview.Cursor = System.Windows.Input.Cursors.Hand;
    }
    private void PreviewPanLost(object sender, System.Windows.Input.MouseEventArgs e)
    {
        previewDrag = null; Preview.Cursor = System.Windows.Input.Cursors.Hand;
    }
    private void ResizePreview(object sender, SizeChangedEventArgs e) { if (initialized) Draw(); }
    private void Draw()
    {
        Preview.Children.Clear();
        if (analysis == null || Preview.ActualWidth < 50) return;
        var p = analysis.Points;
        double minE = p.Min(q => q.E), minN = p.Min(q => q.N), minZ = p.Min(q => q.Z);
        double dx = p.Max(q => q.E) - minE, dy = p.Max(q => q.N) - minN;
        double dz = Math.Max(.001, p.Max(q => q.Z) - minZ);
        double width = Preview.ActualWidth, height = Preview.ActualHeight;
        double scale = Math.Min((width - 36) / Math.Max(dx, .001), (height - 36) / Math.Max(dy, .001));
        WPoint Map(SurveyPoint q) => new(width / 2 + ((q.E - minE) - dx / 2) * scale * previewZoom + previewOffset.X, height / 2 - ((q.N - minN) - dy / 2) * scale * previewZoom + previewOffset.Y);
        for (int x = 18; x < width; x += 24) Preview.Children.Add(new Line { X1 = x, X2 = x, Y1 = 0, Y2 = height, Stroke = new SolidColorBrush(WColor.FromRgb(43, 43, 43)), StrokeThickness = .6 });
        for (int y = 18; y < height; y += 24) Preview.Children.Add(new Line { X1 = 0, X2 = width, Y1 = y, Y2 = y, Stroke = new SolidColorBrush(WColor.FromRgb(43, 43, 43)), StrokeThickness = .6 });
        var hull = Survey.Hull(p); var outline = new WPolyline { Stroke = new SolidColorBrush(WColor.FromRgb(220, 220, 220)), StrokeThickness = 1.5, Fill = new SolidColorBrush(WColor.FromArgb(20, 235, 235, 235)) };
        foreach (var q in hull) outline.Points.Add(Map(q));
        outline.Points.Add(Map(hull[0])); Preview.Children.Add(outline);
        // Limita apenas o desenho da prévia; não descarta pontos da criação.
        int stride = Math.Max(1, (int)Math.Ceiling(p.Count / 3000d));
        for (int i = 0; i < p.Count; i += stride)
        {
            var q = p[i]; double f = (q.Z - minZ) / dz; var pos = Map(q);
            var dot = new Ellipse { Width = 3.5, Height = 3.5, Fill = new SolidColorBrush(WColor.FromRgb((byte)(100 + 155 * f), (byte)(100 + 155 * f), (byte)(100 + 155 * f))) };
            Canvas.SetLeft(dot, pos.X - 1.75); Canvas.SetTop(dot, pos.Y - 1.75); Preview.Children.Add(dot);
        }
        var north = new TextBlock { Text = "N ↑", Foreground = Brushes.LightGray, FontSize = 11 }; Canvas.SetRight(north, 8); Canvas.SetTop(north, 8); Preview.Children.Add(north);
    }
    private void PrepareSurveyLocation()
    {
        if (analysis == null || GeoMode.SelectedIndex != 0) return;
        var inverse = RevitService.InternalToShared(doc.ActiveProjectLocation).Inverse;
        bool distant = analysis.Points.Any(p =>
        {
            var point = inverse.OfPoint(new XYZ(RevitService.Feet(p.E), RevitService.Feet(p.N), RevitService.Feet(p.Z)));
            return !XYZ.IsWithinLengthLimits(point) || point.GetLength() > RevitService.Feet(15000);
        });
        // Uma localização criada por versões anteriores pode deslocar todo o Z.
        bool verticalOffset = cad == null && csv != null &&
            Math.Abs(RevitService.InternalToShared(doc.ActiveProjectLocation).Origin.Z) > RevitService.Feet(.001);
        if (!distant && !verticalOffset) return;
        GeoMode.SelectedIndex = 1;
        GeoConsent.IsChecked = false;
        Status.Text = "Nova localização preparada: Este/Norte próximos do terreno e origem vertical 0 m para manter as cotas do levantamento. Confirme na etapa Criação.";
    }
    private void GeoChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!initialized) return;
        AnchorPanel.Visibility = GeoMode.SelectedIndex == 1 ? System.Windows.Visibility.Visible : System.Windows.Visibility.Collapsed;
        Reviewed.IsChecked = false; GeoConsent.IsChecked = false;
    }
    private void Create()
    {
        if (analysis == null || readErrors.Count > 0) throw new ArgumentException("Confira o levantamento antes de criar.");
        if (Reviewed.IsChecked != true) throw new ArgumentException("Marque a confirmação de conferência dos dados.");
        bool originalMode = GeoMode.SelectedIndex == 0;
        PrepareSurveyLocation();
        if (originalMode && GeoMode.SelectedIndex == 1)
            throw new ArgumentException("Foi preparada uma nova localização para preservar as coordenadas do levantamento perto da origem interna. Confira os valores e confirme a alteração da referência compartilhada antes de criar.");
        bool newLocation = GeoMode.SelectedIndex == 1;
        if (newLocation && GeoConsent.IsChecked != true) throw new ArgumentException("Confirme a alteração da localização compartilhada.");
        if (TopoTypes.SelectedItem is not Choice type || Levels.SelectedItem is not Choice level) throw new ArgumentException("O projeto precisa de um nível e de um tipo de sólido topográfico.");
        if (string.IsNullOrWhiteSpace(Datum.Text)) throw new ArgumentException("Informe o datum declarado pelo levantamento.");
        if (!int.TryParse(Zone.Text, out int zone) || zone < 1 || zone > 60) throw new ArgumentException("Zona UTM deve ser de 1 a 60.");
        var settings = new GeoSettings(newLocation, newLocation ? Survey.Number(AnchorE.Text) : 0,
            newLocation ? Survey.Number(AnchorN.Text) : 0, newLocation ? Survey.Number(AnchorZ.Text) : 0,
            Datum.Text.Trim(), zone, Hemisphere.SelectedIndex == 0 ? "Sul" : "Norte");
        Status.Text = "Criando sólido topográfico…";
        var id = RevitService.Create(doc, analysis, type.Id, level.Id, settings, source);
        created = true;
        report = JsonSerializer.Serialize(new { Version = "0.2", Revit = doc.Application.VersionNumber, Date = DateTimeOffset.Now,
            Source = source, ElementId = id.ToString(), Location = doc.ActiveProjectLocation.Name, Settings = settings,
            Points = analysis.Points.Count, analysis.Duplicates, Errors = readErrors, analysis.Conflicts,
            Boundary = "Convex hull", Reprojection = false }, new JsonSerializerOptions { WriteIndented = true });
        ui.Selection.SetElementIds(new List<ElementId> { id });
        Status.Text = $"Terreno criado • elemento {id}. Revise a geometria e as cotas no Revit.";
        Next.Content = "Concluir"; Back.IsEnabled = false;
        Nav1.IsEnabled = false; Nav2.IsEnabled = false; Nav3.IsEnabled = false; Page3.IsEnabled = false;
        var save = new Button { Content = "Salvar relatório JSON", HorizontalAlignment = HorizontalAlignment.Left };
        save.Click += (_, _) => Guard(() =>
        {
            var dialog = new SaveFileDialog { Filter = "Relatório JSON|*.json", FileName = "TopoBim_relatorio.json" };
            if (dialog.ShowDialog(this) == true) File.WriteAllText(dialog.FileName, report);
        });
        // Fora de Page3 desabilitada, no topo do painel de conteúdo.
        Page3.IsEnabled = true;
        foreach (var child in Page3.Children.OfType<UIElement>()) child.IsEnabled = false;
        Page3.Children.Add(save);
    }
}


