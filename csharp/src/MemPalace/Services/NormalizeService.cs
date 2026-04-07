namespace MemPalace.Services;

public static class NormalizeService
{
    public static string NormalizeWhitespace(string input)
    {
        return string.Join(' ', input.Split((char[])null!, StringSplitOptions.RemoveEmptyEntries));
    }

    public static string NormalizeRoomName(string value)
    {
        var normalized = NormalizeWhitespace(value).Trim().ToLowerInvariant();
        return normalized.Replace(' ', '-');
    }
}
