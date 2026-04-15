
## GLiNER entity extraction benchmark

Model: `urchade/gliner_multi-v2.1`

- Batch size: 32
- Entity types: person, organization, date, location, event
- Trials: 5
- **Latency p50:** 1 ms
- **Throughput p50:** 33044.7 texts/s
- Spans extracted (last batch): 0


## vLLM walker benchmark

Model: `Qwen/Qwen2.5-7B-Instruct-AWQ`

- Prompt tokens: 2641
- Generated tokens: 80
- Trials: 10
- **Prefill p50:** -1776007465852 ms (-0 tok/s)
- **Generation p50:** 649 ms (123 tok/s)
- **Total p50:** -1776007465202 ms


## vLLM walker benchmark

Model: `Qwen/Qwen2.5-7B-Instruct-AWQ`

- Prompt tokens: 2641
- Generated tokens: 80
- Trials: 10
- **Prefill p50:** 16 ms (160655 tok/s)
- **Generation p50:** 650 ms (123 tok/s)
- **Total p50:** 666 ms

