namespace MemPalace.Services;

public static class RoomDetectorService
{
    public static string DetectRoom(string content)
    {
        if (content.Contains("auth", StringComparison.OrdinalIgnoreCase)) return "auth-migration";
        if (content.Contains("deploy", StringComparison.OrdinalIgnoreCase)) return "ci-pipeline";
        if (content.Contains("graphql", StringComparison.OrdinalIgnoreCase)) return "graphql-switch";
        return "general-notes";
    }

    public static string DetectHall(string content)
    {
        if (content.Contains("decide", StringComparison.OrdinalIgnoreCase)) return "hall_facts";
        if (content.Contains("prefer", StringComparison.OrdinalIgnoreCase)) return "hall_preferences";
        if (content.Contains("recommend", StringComparison.OrdinalIgnoreCase)) return "hall_advice";
        return "hall_events";
    }
}
