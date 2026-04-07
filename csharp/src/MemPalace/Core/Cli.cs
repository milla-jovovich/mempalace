using MemPalace.Services;

namespace MemPalace.Core;

public static class Cli
{
    public static async Task<int> RunAsync(string[] args)
    {
        if (args.Length == 0)
        {
            PrintHelp();
            return 0;
        }

        var config = ConfigService.LoadOrCreate();
        var miner = new MinerService(config);
        var searcher = new SearchService(config);

        return args[0].ToLowerInvariant() switch
        {
            "init" => await RunInit(config, args),
            "mine" => await RunMine(miner, args),
            "search" => await RunSearch(searcher, args),
            "status" => RunStatus(config),
            "wake-up" => RunWakeUp(config),
            _ => UnknownCommand(args[0])
        };
    }

    private static async Task<int> RunInit(AppConfig config, string[] args)
    {
        var target = args.Length > 1 ? args[1] : Environment.CurrentDirectory;
        await ConfigService.InitializePalaceAsync(config, target);
        Console.WriteLine($"Initialized MemPalace at {config.PalacePath}");
        return 0;
    }

    private static async Task<int> RunMine(MinerService miner, string[] args)
    {
        if (args.Length < 2)
        {
            Console.Error.WriteLine("Usage: mempalace mine <path> [--mode projects|convos|general]");
            return 1;
        }

        var mode = "projects";
        for (var i = 2; i < args.Length - 1; i++)
        {
            if (args[i] == "--mode")
            {
                mode = args[i + 1];
                break;
            }
        }

        await miner.MineAsync(args[1], mode);
        return 0;
    }

    private static async Task<int> RunSearch(SearchService searcher, string[] args)
    {
        if (args.Length < 2)
        {
            Console.Error.WriteLine("Usage: mempalace search <query>");
            return 1;
        }

        var query = string.Join(' ', args.Skip(1));
        var results = await searcher.SearchAsync(query);
        foreach (var result in results)
        {
            Console.WriteLine($"- [{result.Score:F2}] {result.Title} :: {result.Snippet}");
        }

        return 0;
    }

    private static int RunStatus(AppConfig config)
    {
        Console.WriteLine($"Palace path: {config.PalacePath}");
        Console.WriteLine($"Index path: {config.IndexPath}");
        Console.WriteLine($"Version: {config.Version}");
        return 0;
    }

    private static int RunWakeUp(AppConfig config)
    {
        Console.WriteLine($"AAAK::palace={config.PalacePath};version={config.Version};halls=facts,events,discoveries,preferences,advice");
        return 0;
    }

    private static int UnknownCommand(string command)
    {
        Console.Error.WriteLine($"Unknown command: {command}");
        PrintHelp();
        return 1;
    }

    private static void PrintHelp()
    {
        Console.WriteLine("MemPalace (C# port)");
        Console.WriteLine("Commands: init, mine, search, status, wake-up");
    }
}
