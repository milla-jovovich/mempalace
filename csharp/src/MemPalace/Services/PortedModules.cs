namespace MemPalace.Services;

public static class DialectService
{
    public static string EncodeAaak(string input) => $"AAAK::{NormalizeService.NormalizeWhitespace(input)}";
    public static string DecodeAaak(string input) => input.Replace("AAAK::", string.Empty).Trim();
}

public static class SpellcheckService
{
    public static string Correct(string input) => input;
}

public static class EntityDetectorService
{
    public static IReadOnlyList<string> DetectEntities(string content)
    {
        return content.Split(' ', StringSplitOptions.RemoveEmptyEntries)
            .Where(token => token.Length > 2 && char.IsUpper(token[0]))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(20)
            .ToArray();
    }
}

public sealed class EntityRegistryService
{
    private readonly Dictionary<string, HashSet<string>> _registry = new(StringComparer.OrdinalIgnoreCase);

    public void Add(string entity, string source)
    {
        if (!_registry.TryGetValue(entity, out var sources))
        {
            sources = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            _registry[entity] = sources;
        }

        sources.Add(source);
    }

    public IReadOnlyDictionary<string, HashSet<string>> Snapshot() => _registry;
}

public static class KnowledgeGraphService
{
    public static IReadOnlyDictionary<string, IReadOnlyCollection<string>> BuildConnections(IEnumerable<string> entities)
    {
        var items = entities.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        var graph = new Dictionary<string, IReadOnlyCollection<string>>(StringComparer.OrdinalIgnoreCase);
        foreach (var entity in items)
        {
            graph[entity] = items.Where(x => !x.Equals(entity, StringComparison.OrdinalIgnoreCase)).Take(5).ToArray();
        }

        return graph;
    }
}

public static class PalaceGraphService
{
    public static string BuildWingPath(string wing, string hall, string room) => $"wing_{wing}/hall_{hall}/{room}";
}

public static class LayerService
{
    public static string[] DefaultHalls => ["facts", "events", "discoveries", "preferences", "advice"];
}

public static class ConversationMinerService
{
    public static IEnumerable<string> SplitTurns(string conversation) => conversation.Split('\n').Where(x => !string.IsNullOrWhiteSpace(x));
}

public static class GeneralExtractorService
{
    public static IEnumerable<string> ExtractHighlights(string content) => content.Split('.').Where(x => x.Contains("decide", StringComparison.OrdinalIgnoreCase));
}

public static class SplitMegaFilesService
{
    public static IEnumerable<string> Split(string content, int chunkSize = 2000)
    {
        for (var i = 0; i < content.Length; i += chunkSize)
        {
            yield return content[i..Math.Min(content.Length, i + chunkSize)];
        }
    }
}

public sealed class McpServerService
{
    public object DescribeTools() => new
    {
        name = "mempalace",
        tools = new[] { "mempalace_search", "mempalace_mine", "mempalace_status" }
    };
}
