using Autodesk.Revit.UI;
using Autodesk.Revit.DB;
using Autodesk.Revit.Attributes;
using System.Reflection;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace TopoBim;

public class App : IExternalApplication
{
    public Result OnStartup(UIControlledApplication application)
    {
        const string tab = "TOPOBIM";
        try { application.CreateRibbonTab(tab); } catch (Autodesk.Revit.Exceptions.ArgumentException) { }
        var panel = application.CreateRibbonPanel(tab, "Terreno e coordenadas");
        var data = new PushButtonData("TopoBim.Start", "TOPOBIM", Assembly.GetExecutingAssembly().Location, typeof(Command).FullName!);
        var button = (PushButton)panel.AddItem(data);
        button.LargeImage = CreateBrandIcon(32);
        button.Image = CreateBrandIcon(16);
        button.ToolTip = "Importe pontos CSV/TXT ou leia um DWG do projeto, confira o levantamento e crie um sólido topográfico.";
        return Result.Succeeded;
    }
    // Mesma geometria vetorial da marca no cabeçalho da interface.
    internal static BitmapSource CreateBrandIcon(int size)
    {
        var visual = new DrawingVisual();
        using (var drawing = visual.RenderOpen())
        {
            drawing.PushTransform(new ScaleTransform(size / 43.0, size / 43.0));
            drawing.DrawRoundedRectangle(new SolidColorBrush(System.Windows.Media.Color.FromRgb(24, 24, 24)), null,
                new System.Windows.Rect(0, 0, 43, 43), 5, 5);
            var contours = Geometry.Parse("M 8 28 L 15 13 L 27 8 L 35 17 L 32 32 L 20 36 Z M 13 26 L 18 17 L 26 13 L 31 19 L 28 28 L 20 31 Z M 18 24 L 21 20 L 25 18 L 27 22 L 24 26 Z");
            drawing.DrawGeometry(null, new Pen(Brushes.White, 1.1), contours);
            drawing.Pop();
        }
        var bitmap = new RenderTargetBitmap(size, size, 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(visual);
        bitmap.Freeze();
        return bitmap;
    }

    public Result OnShutdown(UIControlledApplication application) => Result.Succeeded;
}

[Transaction(TransactionMode.Manual)]
public class Command : IExternalCommand
{
    public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
    {
        var uidoc = data.Application.ActiveUIDocument;
        if (uidoc == null || uidoc.Document.IsFamilyDocument)
        {
            TaskDialog.Show("TOPOBIM", "Abra um projeto Revit para criar o terreno.");
            return Result.Cancelled;
        }
        try
        {
            var window = new MainWindow(uidoc);
            new WindowInteropHelper(window).Owner = data.Application.MainWindowHandle;
            window.ShowDialog();
            return Result.Succeeded;
        }
        catch (Exception ex) { message = ex.ToString(); return Result.Failed; }
    }
}


