# MemPalace in Docker

This example runs MemPalace in a long-lived container and exposes the MCP
server through `docker exec`. That fits stdio-based MCP clients while keeping
the palace data in Docker volumes.

## Why use Docker for MemPalace?

Running MemPalace locally with `pip install mempalace` is still the simplest
option for a single machine.

Docker becomes attractive when you want one or more of these properties:

- **Multiple clients, one palace** — several MCP clients can point at the same
  remote MemPalace container instead of each machine keeping its own separate
  local index.
- **Operational resilience** — with `restart: unless-stopped`, the container
  comes back after host reboots or Docker daemon restarts. This is not full HA,
  but it is often enough for an always-on homelab or utility box.
- **Isolation** — MemPalace and Chroma dependencies stay inside the container
  rather than mixing with the host Python environment.
- **Portable storage** — palace data and config live in named Docker volumes,
  which makes backup, restore, migration, and rollback easier to reason about.
- **Dedicated remote host** — you can keep memory on a separate always-on
  machine and let laptops/workstations connect to it over SSH.

## Start the container

```bash
cd examples/docker
docker compose up -d
```

The example stores data in two named volumes:

- `mempalace-data` → `/data`
- `mempalace-config` → `/root/.mempalace`

The active palace path inside the container is `/data/palace`.

## Connect an MCP client locally

```bash
docker exec -i mempalace python -m mempalace.mcp_server --palace /data/palace
```

For Claude Code:

```bash
claude mcp add mempalace -- docker exec -i mempalace python -m mempalace.mcp_server --palace /data/palace
```

## Connect to a remote Docker host

If the container runs on another machine, wrap the same command in SSH:

```bash
ssh user@host docker exec -i mempalace python -m mempalace.mcp_server --palace /data/palace
```

## Operational note

`python -m mempalace.mcp_server` is a stdio MCP server. In this deployment
model, each client connection launches its own server process inside the
container, and that process lives for as long as the client keeps the stdio
connection open.

That is often exactly what you want for local or light remote use, but if you
run many long-lived sessions in parallel, expect one MemPalace MCP process per
client.
