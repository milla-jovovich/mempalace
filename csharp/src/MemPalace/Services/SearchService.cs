using System.Text.Json;
using MemPalace.Core;

namespace MemPalace.Services;

public sealed class SearchService
{
    private readonly AppConfig _config;

    public SearchService(AppConfig config)
    {
        _config = config;
    }

    public async Task<IReadOnlyList<SearchResult>> SearchAsync(string query)
    {
        if (!Directory.Exists(_config.IndexPath))
        {
            return Array.Empty<SearchResult>();
        }

        var queryTerms = query.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var results = new List<SearchResult>();

        foreach (var file in Directory.EnumerateFiles(_config.IndexPath, "index-*.json"))
        {
            var json = await File.ReadAllTextAsync(file);
            var docs = JsonSerializer.Deserialize<List<MemoryDocument>>(json) ?? new List<MemoryDocument>();

            foreach (var doc in docs)
            {
                var score = queryTerms.Count(term => doc.Content.Contains(term, StringComparison.OrdinalIgnoreCase));
                if (score <= 0)
                {
                    continue;
                }

                results.Add(new SearchResult
                {
                    Title = $"{doc.Hall}/{doc.Room}",
                    Snippet = doc.Content[..Math.Min(180, doc.Content.Length)],
                    Score = score / (double)Math.Max(1, queryTerms.Length),
                });
            }
        }

        return results
            .OrderByDescending(r => r.Score)
            .ThenBy(r => r.Title)
            .Take(10)
            .ToArray();
    }
}
