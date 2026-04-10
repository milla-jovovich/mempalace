# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.0] - 2026-04-09

### Added

- `mempalace migrate` command to recover palaces from different ChromaDB versions
- OpenClaw/ClawHub skill integration
- Codex plugin support with hooks and commands
- `mempalace mcp` command with setup guidance
- AGENTS.md and CODEOWNERS
- Dependabot configuration

### Fixed

- HNSW index bloat from duplicate add() calls
- Stale drawer purge before re-mine to avoid hnswlib segfault
- Codex hook message counting
- MCP null args hang, repair infinite recursion, OOM on large files
- Windows mtime test compatibility
- Shell injection in hooks
- MCP protocol version negotiation (hardcoded to negotiated)

### Changed

- Honest AAAK stats with word-based token estimator and lossy labels
- Test coverage increased from 30% to 85%
- Coverage threshold set to 80%
- ChromaDB version range tightened

## [3.0.0] - 2026-04-07

### Added

- Initial public release
- Palace architecture: wings, halls, rooms, closets, drawers
- 4-layer memory stack (L0-L3)
- MCP server with 19 tools
- Knowledge graph with temporal triples
- AAAK dialect compression
- Conversation and project mining
- Benchmark suite (LongMemEval, LoCoMo, MemBench)
- Claude Code plugin

[3.1.0]: https://github.com/milla-jovovich/mempalace/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/milla-jovovich/mempalace/releases/tag/v3.0.0
