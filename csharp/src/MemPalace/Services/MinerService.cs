using System.Text.Json;
using MemPalace.Core;

namespace MemPalace.Services;

public sealed class MinerService
{
    private readonly AppConfig _config;

    public MinerService(AppConfig config)
    {
        _config = config;
    }

    public async Task MineAsync(string path, string mode)
    {
        if (!Directory.Exists(path) && !File.Exists(path))
        {
            Console.Error.WriteLine($"Path does not exist: {path}");
            return;
        }

        var files = File.Exists(path)
            ? new[] { path }
            : Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories)
                .Where(p => !p.Contains(".git", StringComparison.OrdinalIgnoreCase))
                .Take(5000)
                .ToArray();

        var docs = new List<MemoryDocument>();
        foreach (var file in files)
        {
            string content;
            try
            {
                content = await File.ReadAllTextAsync(file);
            }
            catch
            {
                continue;
            }

            if (string.IsNullOrWhiteSpace(content))
            {
                continue;
            }

            var normalized = NormalizeService.NormalizeWhitespace(content);
            var room = NormalizeService.NormalizeRoomName(RoomDetectorService.DetectRoom(normalized));
            var hall = RoomDetectorService.DetectHall(normalized);

            docs.Add(new MemoryDocument
            {
                Id = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(file + normalized[..Math.Min(100, normalized.Length)]))),
                SourcePath = file,
                Content = normalized,
                Hall = hall,
                Room = room,
            });
        }

        Directory.CreateDirectory(_config.IndexPath);
        var indexFile = Path.Combine(_config.IndexPath, $"index-{mode}.json");
        await File.WriteAllTextAsync(indexFile, JsonSerializer.Serialize(docs));
        Console.WriteLine($"Indexed {docs.Count} documents in mode '{mode}'.");
    }
}
