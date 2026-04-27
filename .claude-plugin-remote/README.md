# mempalace-remote

Use a MemPalace install on a **central host** from a **remote client** machine, over SSH.

The default `mempalace` plugin runs the MCP server and auto-save hooks against a local mempalace install. On a remote machine that doesn't have mempalace installed (or shouldn't have its own palace), `mempalace-remote` proxies the same MCP tools and Stop / PreCompact hooks to a host that does, so all clients share one canonical palace.

## How it works

```
┌─────────────────┐     SSH      ┌─────────────────────┐
│  Remote client  │  ─────────▶  │  Central host       │
│  (this plugin)  │              │  mempalace + palace │
└─────────────────┘              └─────────────────────┘
```

- **MCP server** — Claude Code spawns `ssh $MEMPALACE_REMOTE_HOST mempalace-mcp`. The MCP stdin/stdout JSON-RPC stream rides the SSH channel transparently.
- **Stop / PreCompact hooks** — fire on the client, pipe the Claude Code hook JSON to `ssh $MEMPALACE_REMOTE_HOST mempalace hook run --hook {stop,precompact} --harness claude-code` on the host.

## Prerequisites

1. **mempalace installed on the central host.**
2. **Passwordless SSH key** from client to host. `ssh $HOST true` must succeed without prompts.
3. **`MEMPALACE_REMOTE_HOST`** env var set in the environment Claude Code launches in (e.g. `~/.bashrc`, `~/.zshrc`, or systemd unit env).

## Install

```sh
claude /plugin marketplace add MemPalace/mempalace
claude /plugin install mempalace-remote@mempalace
```

Then set the host:

```sh
export MEMPALACE_REMOTE_HOST=palace-host   # alias from ~/.ssh/config or hostname
```

Restart Claude Code. The MCP server should connect, and Stop / PreCompact hooks fire automatically.

## Configuration

| Env var | Required | Default | Description |
|---|---|---|---|
| `MEMPALACE_REMOTE_HOST` | yes | — | SSH target — alias from `~/.ssh/config` or fully qualified hostname |
| `MEMPALACE_REMOTE_BIN` | no | `mempalace` | Path to the `mempalace` CLI on the remote (used by Stop / PreCompact hooks) |
| `MEMPALACE_REMOTE_MCP_BIN` | no | `mempalace-mcp` | Path to the `mempalace-mcp` server on the remote (used by the MCP client) |

## Optional: SSH ControlMaster

Every MCP tool call and every hook fire spawns a fresh `ssh` process. Without connection multiplexing, each pays 200–500 ms of TCP+auth overhead — adding up to seconds per session under heavy use. Add to client `~/.ssh/config`:

```
Host palace-host
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 10m
```

After this, the second and subsequent SSH calls reuse the master connection (~10 ms overhead).

## PATH gotcha

`ssh host command` runs `command` in a **non-interactive, non-login** shell. On most Linux setups, that shell's `PATH` does **not** include `~/.local/bin` (where `pip install --user` and `pipx` put their binaries). If `mempalace` and `mempalace-mcp` are only on PATH for your interactive shell, the SSH calls fail with `command not found`.

The simplest fix is to point the plugin at the full paths on the remote:

```sh
export MEMPALACE_REMOTE_BIN=/home/youruser/.local/bin/mempalace
export MEMPALACE_REMOTE_MCP_BIN=/home/youruser/.local/bin/mempalace-mcp
```

Other options:

1. Install mempalace system-wide on the host so the binaries land in `/usr/local/bin` or `/usr/bin`.
2. Symlink the binaries into a system PATH directory:
   ```sh
   sudo ln -s ~/.local/bin/mempalace /usr/local/bin/mempalace
   sudo ln -s ~/.local/bin/mempalace-mcp /usr/local/bin/mempalace-mcp
   ```
3. Use `~/.ssh/environment` on the host (requires `PermitUserEnvironment yes` in `/etc/ssh/sshd_config`).

## Coexistence with the `mempalace` plugin

Don't enable both plugins on the same machine. Both register an MCP server named `mempalace`, and the second one to load will silently shadow the first. Choose one:

- Central host that owns the palace → `mempalace`
- Remote client that uses the host's palace → `mempalace-remote`

## Windows clients

The MCP wrapper (`bin/mempalace-mcp-ssh.sh`) and the hook scripts are bash. Windows doesn't ship bash, so install Git Bash or WSL and make sure `bash` is on the PATH that Claude Code launches in. Without it, the MCP server fails to start and the auto-save hooks silently no-op.

OpenSSH client ships with Windows 10+ (1809), so once `bash` is available the SSH plumbing works.

## Limitations

- If the central host is unreachable, MCP tool calls fail and hooks log SSH errors after every assistant turn. There's no offline cache or queue.
- Only `claude-code` harness wired today. The same hook scripts could be templated for `codex` if needed.
- `MEMPALACE_REMOTE_HOST` must be a host alias that works from the SSH context Claude Code spawns in. If your terminal SSH config diverges from the GUI launchd / systemd context, expand to a fully qualified hostname.
