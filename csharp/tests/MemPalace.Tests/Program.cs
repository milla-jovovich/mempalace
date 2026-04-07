using MemPalace.Core;
using MemPalace.Services;

var failures = new List<string>();

void Assert(bool condition, string message)
{
    if (!condition) failures.Add(message);
}

var cfg = ConfigService.LoadOrCreate();
Assert(cfg.PalacePath.Contains("mempalace", StringComparison.OrdinalIgnoreCase), "default config should contain mempalace path");

var normalized = NormalizeService.NormalizeWhitespace("Hello   world\n\nSecond");
Assert(normalized == "Hello world Second", "whitespace normalization failed");

var room = RoomDetectorService.DetectRoom("we should migrate auth soon");
Assert(room == "auth-migration", "room detection failed");

var tempRoot = Path.Combine(Path.GetTempPath(), "mempalace-csharp-tests-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(tempRoot);
var sample = Path.Combine(tempRoot, "chat.txt");
await File.WriteAllTextAsync(sample, "> What is memory?\nMemory is persistence.");

var config = new AppConfig
{
    PalacePath = Path.Combine(tempRoot, "palace"),
    IndexPath = Path.Combine(tempRoot, "index"),
    Version = "test"
};

await ConfigService.InitializePalaceAsync(config, tempRoot);
var miner = new MinerService(config);
await miner.MineAsync(tempRoot, "convos");
var search = new SearchService(config);
var results = await search.SearchAsync("memory persistence");
Assert(results.Count > 0, "search should return at least one result after mining");

Directory.Delete(tempRoot, true);

if (failures.Count > 0)
{
    Console.Error.WriteLine("FAILED");
    foreach (var failure in failures) Console.Error.WriteLine("- " + failure);
    return 1;
}

Console.WriteLine("PASS");
return 0;
