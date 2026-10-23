using System.IO;
using System.Globalization;
using System.Text;

namespace TopoBim;

public readonly record struct SurveyPoint(double E, double N, double Z);
public sealed record ReadResult(List<SurveyPoint> Points, List<string> Errors);
public sealed record Analysis(List<SurveyPoint> Points, int Duplicates, List<string> Conflicts);

public static class Survey
{
    public static double Number(string text)
    {
        text = text.Trim();
        // Separador de milhar não é aceito: evita interpretar coordenadas silenciosamente.
        if (text.Contains(',') && text.Contains('.'))
            throw new FormatException("Use números sem separadores de milhar.");
        double value = double.Parse(text.Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture);
        if (!double.IsFinite(value)) throw new FormatException("Número não finito.");
        return value;
    }

    public static ReadResult Read(string path, char separator, int east, int north, int elevation, bool header, double factor)
    {
        if (east < 0 || north < 0 || elevation < 0 || new[] { east, north, elevation }.Distinct().Count() != 3)
            throw new ArgumentException("As três colunas devem ser diferentes e começar em 1.");
        var points = new List<SurveyPoint>();
        var errors = new List<string>();
        int lineNumber = 0;
        bool skippedHeader = false;
        foreach (string line in File.ReadLines(path, Encoding.UTF8))
        {
            lineNumber++;
            if (string.IsNullOrWhiteSpace(line)) continue;
            if (header && !skippedHeader) { skippedHeader = true; continue; }
            try
            {
                var fields = Split(line, separator);
                if (fields.Count <= Math.Max(east, Math.Max(north, elevation))) throw new FormatException("Colunas insuficientes.");
                points.Add(new(Number(fields[east]) * factor, Number(fields[north]) * factor, Number(fields[elevation]) * factor));
            }
            catch (Exception ex) when (ex is FormatException or OverflowException)
            {
                errors.Add($"Linha {lineNumber}: {ex.Message}");
            }
            if (points.Count > 100000) throw new InvalidOperationException("Limite desta versão: 100.000 pontos de entrada. Reduza o levantamento.");
        }
        return new(points, errors);
    }

    public static List<string> Split(string line, char separator)
    {
        var result = new List<string>();
        var field = new StringBuilder();
        bool quoted = false;
        for (int i = 0; i < line.Length; i++)
        {
            char c = line[i];
            if (c == '"')
            {
                if (quoted && i + 1 < line.Length && line[i + 1] == '"') { field.Append('"'); i++; }
                else quoted = !quoted;
            }
            else if (c == separator && !quoted) { result.Add(field.ToString()); field.Clear(); }
            else field.Append(c);
        }
        if (quoted) throw new FormatException("Aspas não fechadas. Campos multilinha não são suportados.");
        result.Add(field.ToString());
        return result;
    }

    public static Analysis Analyze(IEnumerable<SurveyPoint> input)
    {
        var map = new Dictionary<(double, double), SurveyPoint>();
        var conflicts = new List<string>();
        int duplicates = 0;
        foreach (var p in input)
        {
            if (!double.IsFinite(p.E) || !double.IsFinite(p.N) || !double.IsFinite(p.Z))
                throw new ArgumentException("Coordenada não finita.");
            // Grade de 1 mm: agrupamento determinístico, não raio de proximidade.
            var key = (Math.Round(p.E, 3), Math.Round(p.N, 3));
            if (map.TryGetValue(key, out var old))
            {
                // Aceita até 1 mm, com margem de 1 nm para arredondamento numérico.
                if (Math.Abs(old.Z - p.Z) > .001 + 1e-9)
                    conflicts.Add(FormattableString.Invariant($"E={p.E:F3}; N={p.N:F3}: cotas {old.Z:F3} / {p.Z:F3}"));
                else duplicates++;
            }
            else map[key] = p;
        }
        var points = map.Values.ToList();
        if (points.Count < 3) throw new ArgumentException("São necessários ao menos três pontos distintos em planta.");
        var hull = Hull(points);
        if (hull.Count < 3) throw new ArgumentException("Os pontos são colineares em planta.");
        if (points.Count > 20000) throw new ArgumentException("Limite de criação desta versão: 20.000 pontos. Reduza os dados antes de continuar.");
        return new(points, duplicates, conflicts);
    }

    public static List<SurveyPoint> Hull(IEnumerable<SurveyPoint> input)
    {
        var p = input.OrderBy(p => p.E).ThenBy(p => p.N).ToList();
        if (p.Count < 3) return p;
        static double Cross(SurveyPoint a, SurveyPoint b, SurveyPoint c) =>
            (b.E - a.E) * (c.N - a.N) - (b.N - a.N) * (c.E - a.E);
        var lower = new List<SurveyPoint>();
        foreach (var q in p) { while (lower.Count >= 2 && Cross(lower[^2], lower[^1], q) <= 1e-9) lower.RemoveAt(lower.Count - 1); lower.Add(q); }
        var upper = new List<SurveyPoint>();
        for (int i = p.Count - 1; i >= 0; i--) { var q = p[i]; while (upper.Count >= 2 && Cross(upper[^2], upper[^1], q) <= 1e-9) upper.RemoveAt(upper.Count - 1); upper.Add(q); }
        lower.RemoveAt(lower.Count - 1); upper.RemoveAt(upper.Count - 1); lower.AddRange(upper);
        return lower;
    }
}


