# MemPalace C# Port

This directory contains a C#/.NET implementation of MemPalace's core CLI workflow, plus tests and benchmark runners.

## Included

- CLI commands: `init`, `mine`, `search`, `status`, `wake-up`
- Local JSON indexing and lexical search
- Service modules mirroring Python package areas:
  - config, miner, searcher, normalization, room detection
  - dialect/AAAK, entities, registry, graph, layers, MCP stubs
- C# test runner (`csharp/tests/MemPalace.Tests`)
- C# benchmark runner (`csharp/benchmarks/MemPalace.Benchmarks`) with LongMemEval/LoCoMo/ConvoMem/MemBench modes

## Run

```bash
dotnet run --project csharp/src/MemPalace -- init .
dotnet run --project csharp/src/MemPalace -- mine . --mode projects
dotnet run --project csharp/src/MemPalace -- search "auth migration decision"
dotnet run --project csharp/tests/MemPalace.Tests
dotnet run --project csharp/benchmarks/MemPalace.Benchmarks -- longmemeval /path/to/data.json
```
