using Autodesk.Revit.DB;
using System.Globalization;
using System.Text.Json;

namespace TopoBim;

public sealed record Choice(ElementId Id, string Name);
public sealed record CadPoint(SurveyPoint Point, string Layer);
public sealed record GeoSettings(bool NewLocation, double East, double North, double Elevation, string Datum, int Zone, string Hemisphere);

public static class RevitService
{
    public static double Feet(double metres) => UnitUtils.ConvertToInternalUnits(metres, UnitTypeId.Meters);
    public static double Metres(double feet) => UnitUtils.ConvertFromInternalUnits(feet, UnitTypeId.Meters);
    public static List<Choice> Choices(Document doc, Type type) => new FilteredElementCollector(doc)
        .OfClass(type).Select(e => new Choice(e.Id, e.Name)).OrderBy(e => e.Name).ToList();

    // Constrói a transformação a partir da API que reporta coordenadas compartilhadas.
    // Evita depender de uma interpretação de GetTotalTransform para ProjectLocation.
    public static Transform InternalToShared(ProjectLocation location)
    {
        XYZ Shared(XYZ p)
        {
            using var pos = location.GetProjectPosition(p);
            return new XYZ(pos.EastWest, pos.NorthSouth, pos.Elevation);
        }
        var origin = Shared(XYZ.Zero);
        var t = Transform.Identity;
        t.Origin = origin;
        t.BasisX = Shared(XYZ.BasisX) - origin;
        t.BasisY = Shared(XYZ.BasisY) - origin;
        t.BasisZ = Shared(XYZ.BasisZ) - origin;
        return t;
    }

    public static List<CadPoint> ReadCad(Document doc, ElementId id, bool originalCoordinates = false)
    {
        var cad = doc.GetElement(id) as ImportInstance ?? throw new ArgumentException("Selecione um DWG do projeto.");
        if (cad.ViewSpecific) throw new ArgumentException("O DWG está restrito à vista. Vincule-o com 'Somente vista atual' desmarcado.");
        var output = new List<CadPoint>();
        var shared = originalCoordinates ? cad.GetTransform().Inverse : InternalToShared(doc.ActiveProjectLocation);
        void Add(XYZ p, string layer)
        {
            var q = shared.OfPoint(p);
            output.Add(new(new(Metres(q.X), Metres(q.Y), Metres(q.Z)), layer));
            if (output.Count > 100000) throw new InvalidOperationException("O DWG excede 100.000 vértices. Simplifique o arquivo.");
        }
        void Walk(GeometryElement geometry, Transform transform, string inheritedLayer)
        {
            foreach (GeometryObject obj in geometry)
            {
                string layer = (doc.GetElement(obj.GraphicsStyleId) as GraphicsStyle)?.GraphicsStyleCategory?.Name ?? inheritedLayer;
                if (obj is GeometryInstance instance)
                    Walk(instance.GetSymbolGeometry(), transform.Multiply(instance.Transform), layer);
                else if (obj is PolyLine poly)
                    foreach (var p in poly.GetCoordinates()) Add(transform.OfPoint(p), layer);
                else if (obj is Curve curve)
                    foreach (var p in curve.Tessellate()) Add(transform.OfPoint(p), layer);
                else if (obj is Autodesk.Revit.DB.Point point) Add(transform.OfPoint(point.Coord), layer);
                else if (obj is Mesh mesh)
                    foreach (var p in mesh.Vertices) Add(transform.OfPoint(p), layer);
            }
        }
        var geo = cad.get_Geometry(new Options { IncludeNonVisibleObjects = true, DetailLevel = ViewDetailLevel.Fine });
        if (geo == null) throw new ArgumentException("O DWG não disponibilizou geometria.");
        Walk(geo, Transform.Identity, "Sem camada");
        if (output.Count == 0) throw new ArgumentException("Não foram encontrados pontos, curvas ou malhas. Objetos proxy Civil 3D precisam ser convertidos em geometria CAD comum.");
        return output;
    }

    // Confere vértices reais da superfície, não apenas os pontos de entrada.
    private static void PreserveSurfaceElevations(Document doc, Toposolid topo, List<XYZ> expected)
    {
        double tolerance = Feet(.001);
        List<(XYZ Expected, XYZ Actual)> Match()
        {
            using var editor = topo.GetSlabShapeEditor();
            var vertices = editor.SlabShapeVertices.Cast<SlabShapeVertex>().Select(v => v.Position).ToList();
            if (vertices.Count == 0) throw new InvalidOperationException("Não foi possível conferir as cotas da superfície criada.");
            (long, long) Key(XYZ p) => ((long)Math.Floor(p.X / tolerance), (long)Math.Floor(p.Y / tolerance));
            var buckets = vertices.GroupBy(Key).ToDictionary(g => g.Key, g => g.ToList());
            var matches = new List<(XYZ Expected, XYZ Actual)>();
            foreach (var point in expected)
            {
                var key = Key(point); XYZ? nearest = null; double best = tolerance * tolerance;
                for (long x = key.Item1 - 1; x <= key.Item1 + 1; x++)
                    for (long y = key.Item2 - 1; y <= key.Item2 + 1; y++)
                        if (buckets.TryGetValue((x, y), out var candidates))
                            foreach (var candidate in candidates)
                            {
                                double distance = Math.Pow(candidate.X - point.X, 2) + Math.Pow(candidate.Y - point.Y, 2);
                                if (distance <= best) { best = distance; nearest = candidate; }
                            }
                if (nearest == null) throw new InvalidOperationException("Um ponto do levantamento não foi preservado na superfície. A criação foi cancelada.");
                matches.Add((point, nearest));
            }
            return matches;
        }
        var matches = Match();
        double correction = matches[0].Expected.Z - matches[0].Actual.Z;
        if (matches.Any(m => Math.Abs((m.Expected.Z - m.Actual.Z) - correction) > tolerance))
            throw new InvalidOperationException("A superfície criada alterou os desníveis do levantamento. A criação foi cancelada.");
        if (Math.Abs(correction) > Feet(.000001))
        {
            ElementTransformUtils.MoveElement(doc, topo.Id, new XYZ(0, 0, correction));
            doc.Regenerate();
        }
        if (Match().Any(m => Math.Abs(m.Expected.Z - m.Actual.Z) > tolerance))
            throw new InvalidOperationException("As cotas da superfície diferem do levantamento em mais de 1 mm. A criação foi cancelada.");
    }

    public static ElementId Create(Document doc, Analysis analysis, ElementId typeId, ElementId levelId, GeoSettings settings, string source)
    {
        // Diferenças de cota são avisos; Analyze mantém a primeira cota por XY.
        if (doc.GetElement(typeId) is not ToposolidType || doc.GetElement(levelId) is not Level)
            throw new ArgumentException("Selecione um tipo de sólido topográfico e um nível válidos.");
        using var tx = new Transaction(doc, "TOPOBIM — criar terreno");
        tx.Start();
        try
        {
            if (settings.NewLocation)
            {
                // Uma nova localização muda a referência de todo o projeto; UI exige ciência explícita.
                string name = "TOPOBIM " + DateTime.Now.ToString("yyyyMMdd HHmmss fff", CultureInfo.InvariantCulture);
                var location = doc.ActiveProjectLocation.Duplicate(name);
                using var position = new ProjectPosition(Feet(settings.East), Feet(settings.North), Feet(settings.Elevation), 0);
                location.SetProjectPosition(XYZ.Zero, position);
                doc.ActiveProjectLocation = location;
                doc.Regenerate();
            }
            var sharedToInternal = InternalToShared(doc.ActiveProjectLocation).Inverse;
            var points = analysis.Points.Select(p => sharedToInternal.OfPoint(new XYZ(Feet(p.E), Feet(p.N), Feet(p.Z)))).ToList();
            foreach (var point in points)
                if (!XYZ.IsWithinLengthLimits(point) || point.GetLength() > Feet(15000))
                    throw new ArgumentException("O terreno ainda está a mais de 15 km da origem interna. Na etapa Criação, use Criar nova localização e confira Este, Norte e Elevação da origem. Se esse modo já estiver ativo, verifique as colunas e unidades do levantamento.");
            // O contorno será o fecho convexo; não tenta inferir divisas côncavas a partir de uma nuvem.
            var topo = Toposolid.Create(doc, points, typeId, levelId);
            doc.Regenerate();
            PreserveSurfaceElevations(doc, topo, points);
            // Confere 3 pontos conhecidos em coordenadas compartilhadas antes de concluir a transação.
            var toShared = InternalToShared(doc.ActiveProjectLocation);
            for (int i = 0; i < Math.Min(3, points.Count); i++)
            {
                var q = toShared.OfPoint(points[i]);
                var original = analysis.Points[i];
                if (Math.Abs(Metres(q.X) - original.E) > .002 || Math.Abs(Metres(q.Y) - original.N) > .002 || Math.Abs(Metres(q.Z) - original.Z) > .002)
                    throw new InvalidOperationException("Falha na conferência da transformação de coordenadas.");
            }
            var comment = topo.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
            if (comment != null && !comment.IsReadOnly)
                comment.Set(JsonSerializer.Serialize(new { Plugin = "TOPOBIM 0.2", Source = source, settings.Datum, settings.Zone, settings.Hemisphere, Points = analysis.Points.Count, Boundary = "Convex hull", CRSConversion = false, Elevations = "Cotas da superfície verificadas nos pontos do levantamento; tolerância 1 mm" }));
            var id = topo.Id;
            var status = tx.Commit();
            if (status != TransactionStatus.Committed) throw new InvalidOperationException("O Revit não confirmou a criação do sólido.");
            return id;
        }
        catch { if (tx.GetStatus() == TransactionStatus.Started) tx.RollBack(); throw; }
    }
}
