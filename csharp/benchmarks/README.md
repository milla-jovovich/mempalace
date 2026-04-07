# MemPalace C# Benchmarks

The C# benchmark runner supports the same benchmark families as the Python repo:

- `longmemeval`
- `locomo`
- `convomem`
- `membench`

## Run

```bash
dotnet run --project csharp/benchmarks/MemPalace.Benchmarks -- longmemeval /path/to/data.json --top-k 5
dotnet run --project csharp/benchmarks/MemPalace.Benchmarks -- locomo /path/to/data.json --top-k 10
dotnet run --project csharp/benchmarks/MemPalace.Benchmarks -- convomem /path/to/data.json --limit 100
dotnet run --project csharp/benchmarks/MemPalace.Benchmarks -- membench /path/to/data.jsonl
```

## Dataset contract

Each row should include a question-like field (`question`, `query`, or `prompt`) and content/evidence fields.
The runner resolves common aliases and reports `Recall@K`.
