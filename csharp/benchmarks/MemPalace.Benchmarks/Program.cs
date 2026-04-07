using System.Text.Json;
using MemPalace.Core;
using MemPalace.Services;

if (args.Length < 2)
{
    Console.WriteLine("Usage: mempalace-bench <longmemeval|locomo|convomem|membench> <dataset-path> [--top-k N] [--limit N]");
    return 1;
}

var bench = args[0].ToLowerInvariant();
var dataset = args[1];
var topK = GetIntFlag(args, "--top-k", 5);
var limit = GetIntFlag(args, "--limit", 0);

if (!File.Exists(dataset))
{
    Console.Error.WriteLine($"Dataset not found: {dataset}");
    return 1;
}

var workspace = Path.Combine(Path.GetTempPath(), "mempalace-bench-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(workspace);

var config = new AppConfig
{
    PalacePath = Path.Combine(workspace, "palace"),
    IndexPath = Path.Combine(workspace, "index"),
    Version = "bench"
};

await ConfigService.InitializePalaceAsync(config, workspace);
var miner = new MinerService(config);
var search = new SearchService(config);

var records = LoadRecords(dataset);
if (limit > 0) records = records.Take(limit).ToList();

var corpusDir = Path.Combine(workspace, "corpus");
Directory.CreateDirectory(corpusDir);
for (var i = 0; i < records.Count; i++)
{
    await File.WriteAllTextAsync(Path.Combine(corpusDir, $"doc-{i}.txt"), records[i].Context);
}

await miner.MineAsync(corpusDir, bench);

var hits = 0;
foreach (var record in records)
{
    var results = await search.SearchAsync(record.Question);
    var matched = results.Take(topK).Any(r => r.Snippet.Contains(record.Evidence, StringComparison.OrdinalIgnoreCase));
    if (matched) hits++;
}

var recall = records.Count == 0 ? 0 : hits / (double)records.Count;
Console.WriteLine($"Benchmark: {bench}");
Console.WriteLine($"Items: {records.Count}");
Console.WriteLine($"Recall@{topK}: {recall:F3}");

Directory.Delete(workspace, true);
return 0;

static int GetIntFlag(string[] args, string flag, int defaultValue)
{
    for (var i = 0; i < args.Length - 1; i++)
    {
        if (args[i] == flag && int.TryParse(args[i + 1], out var parsed))
        {
            return parsed;
        }
    }

    return defaultValue;
}

static List<BenchmarkRecord> LoadRecords(string datasetPath)
{
    var json = File.ReadAllText(datasetPath);

    if (datasetPath.EndsWith(".jsonl", StringComparison.OrdinalIgnoreCase))
    {
        return File.ReadLines(datasetPath)
            .Where(line => !string.IsNullOrWhiteSpace(line))
            .Select(ParseNode)
            .ToList();
    }

    using var doc = JsonDocument.Parse(json);
    if (doc.RootElement.ValueKind == JsonValueKind.Array)
    {
        return doc.RootElement.EnumerateArray().Select(ParseElement).ToList();
    }

    return new List<BenchmarkRecord>();
}

static BenchmarkRecord ParseNode(string line)
{
    using var doc = JsonDocument.Parse(line);
    return ParseElement(doc.RootElement);
}

static BenchmarkRecord ParseElement(JsonElement e)
{
    var question = GetAny(e, "question", "query", "prompt");
    var context = GetAny(e, "context", "document", "conversation", "session");
    var evidence = GetAny(e, "evidence", "answer", "target", "expected");

    return new BenchmarkRecord(
        string.IsNullOrWhiteSpace(question) ? "unknown question" : question,
        string.IsNullOrWhiteSpace(context) ? evidence : context,
        string.IsNullOrWhiteSpace(evidence) ? context : evidence
    );
}

static string GetAny(JsonElement e, params string[] keys)
{
    foreach (var key in keys)
    {
        if (e.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.String)
        {
            return value.GetString() ?? string.Empty;
        }
    }

    return string.Empty;
}

record BenchmarkRecord(string Question, string Context, string Evidence);
