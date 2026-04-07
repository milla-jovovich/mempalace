namespace MemPalace.Core;

public sealed class AppConfig
{
    public string PalacePath { get; init; } = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".mempalace", "palace");
    public string IndexPath { get; init; } = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".mempalace", "index");
    public string Version { get; init; } = "0.1.0-csharp";
}

public sealed class SearchResult
{
    public required string Title { get; init; }
    public required string Snippet { get; init; }
    public double Score { get; init; }
}

public sealed class MemoryDocument
{
    public required string Id { get; init; }
    public required string SourcePath { get; init; }
    public required string Content { get; init; }
    public required string Hall { get; init; }
    public required string Room { get; init; }
    public DateTimeOffset IndexedAt { get; init; } = DateTimeOffset.UtcNow;
}
