#!/usr/bin/env python3
"""
device_miner.py — Scan a machine, fill the palace. Cold start killer.

Discovers everything meaningful on the device — git repos, languages,
frameworks, tools, shell profile, cloud connections, AI sessions,
documents, knowledge bases — and files it all as verbatim drawers.

No mempalace.yaml needed. No init step. Just point it at your home
directory and it builds wings from what it finds.

Usage:
    mempalace mine-device                     # scan home directory
    mempalace mine-device --wing self         # override wing name
    mempalace mine-device --dry-run           # preview without filing
"""

import hashlib
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import chromadb

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
MIN_CHUNK_SIZE = 50

SKIP_DIRS = {
    "node_modules", ".Trash", "Library", ".npm", ".cache",
    "__pycache__", "venv", ".venv", "vendor", "Pods", ".cocoapods",
    "dist", "build", ".next", ".nuxt", "target", "DerivedData",
}

LANG_EXTENSIONS = {
    "ts": "TypeScript", "tsx": "TypeScript", "js": "JavaScript", "jsx": "JavaScript",
    "py": "Python", "rs": "Rust", "go": "Go", "rb": "Ruby", "java": "Java",
    "kt": "Kotlin", "swift": "Swift", "cs": "C#", "cpp": "C++", "c": "C",
    "lua": "Lua", "zig": "Zig", "ex": "Elixir", "hs": "Haskell",
    "sh": "Shell", "zsh": "Shell", "bash": "Shell",
    "php": "PHP", "dart": "Dart", "r": "R", "scala": "Scala",
    "vue": "Vue", "svelte": "Svelte", "sol": "Solidity",
}


# ── Helpers ──


def _run(cmd: str, timeout: int = 15) -> str:
    """Run a shell command, return stdout or empty string on failure."""
    try:
        return subprocess.check_output(
            cmd, shell=True, stderr=subprocess.DEVNULL,
            timeout=timeout, text=True,
        ).strip()
    except Exception:
        return ""


def _chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> list[str]:
    if not text or len(text) < MIN_CHUNK_SIZE:
        return []
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunk = text[start:end]
        if len(chunk.strip()) >= MIN_CHUNK_SIZE:
            chunks.append(chunk)
        start = end - overlap
    return chunks


def get_collection(palace_path: str):
    """Get or create the palace collection."""
    os.makedirs(palace_path, exist_ok=True)
    client = chromadb.PersistentClient(path=palace_path)
    try:
        return client.get_collection("mempalace_drawers")
    except Exception:
        return client.create_collection("mempalace_drawers")


def add_drawer(collection, wing: str, room: str, content: str,
               source_file: str, chunk_index: int, agent: str) -> bool:
    """Add one drawer to the palace. Returns True if added, False if duplicate."""
    drawer_id = (
        f"drawer_{wing}_{room}_"
        f"{hashlib.md5((source_file + str(chunk_index)).encode()).hexdigest()[:16]}"
    )
    try:
        collection.add(
            documents=[content],
            ids=[drawer_id],
            metadatas=[{
                "wing": wing,
                "room": room,
                "source_file": source_file,
                "chunk_index": chunk_index,
                "added_by": agent,
                "filed_at": datetime.now().isoformat(),
                "ingest_mode": "device",
            }],
        )
        return True
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            return False
        raise


def _file_content(collection, wing, room, content, source, agent):
    """Chunk content and file all drawers. Returns count of drawers added."""
    chunks = _chunk_text(content)
    added = 0
    for i, chunk in enumerate(chunks):
        if add_drawer(collection, wing, room, chunk, source, i, agent):
            added += 1
    return added


# ── Scanners ──


def _find_git_repos(home: str, max_depth: int = 8) -> list[str]:
    """Find all git repos under home directory."""
    excludes = " -o ".join(f'-name "{d}"' for d in [
        "node_modules", ".Trash", ".npm", ".cache", "__pycache__",
        "venv", ".venv", "vendor", "Pods", "dist", "build",
        ".next", "target", "DerivedData",
    ])
    cmd = (
        f'find "{home}" -maxdepth {max_depth} '
        f'\\( {excludes} \\) -prune '
        f'-o -name ".git" -type d -print 2>/dev/null | head -500'
    )
    git_dirs = [d for d in _run(cmd, timeout=60).split("\n") if d]
    return [str(Path(d).parent.resolve()) for d in git_dirs]


def _repo_info(repo_path: str) -> dict:
    """Extract metadata from a git repo."""
    def git(cmd):
        return _run(f'git -C "{repo_path}" {cmd}', timeout=10)

    name = Path(repo_path).name
    remote = git("remote get-url origin") or ""

    # Languages from tracked files
    langs = defaultdict(int)
    for f in git("ls-files").split("\n"):
        ext = Path(f).suffix.lstrip(".").lower()
        if ext in LANG_EXTENSIONS:
            langs[LANG_EXTENSIONS[ext]] += 1

    # Core metadata
    commit_count = int(git("rev-list --count HEAD") or "0")
    last_commit = (git('log -1 --format="%aI"') or "")[:10]
    first_commit = (git('log --reverse --format="%aI" | head -1') or "")[:10]
    contributors = [c for c in git('log --format="%aN" | sort -u | head -15').split("\n") if c]

    # Description from package.json or README
    description = ""
    for desc_file in ["package.json", "Cargo.toml", "pyproject.toml"]:
        p = Path(repo_path) / desc_file
        if p.exists():
            try:
                content = p.read_text()[:2000]
                if desc_file == "package.json":
                    import json
                    desc = json.loads(content).get("description", "")
                    if desc and not desc.startswith("<"):
                        description = desc
                else:
                    import re
                    m = re.search(r'description\s*=\s*"([^"]+)"', content)
                    if m:
                        description = m[1]
            except Exception:
                pass
            if description:
                break

    # Framework detection from package.json
    framework = ""
    pkg_path = Path(repo_path) / "package.json"
    if pkg_path.exists():
        try:
            import json
            pkg = json.loads(pkg_path.read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for name_check, fw in [
                ("next", "Next.js"), ("react", "React"), ("vue", "Vue"),
                ("svelte", "Svelte"), ("hono", "Hono"), ("express", "Express"),
                ("fastify", "Fastify"), ("@angular/core", "Angular"),
            ]:
                if name_check in deps:
                    framework = fw
                    break
        except Exception:
            pass

    # Python framework
    if not framework:
        for check_file in ["pyproject.toml", "requirements.txt"]:
            p = Path(repo_path) / check_file
            if p.exists():
                try:
                    text = p.read_text().lower()
                    for kw, fw in [("fastapi", "FastAPI"), ("django", "Django"),
                                   ("flask", "Flask"), ("streamlit", "Streamlit")]:
                        if kw in text:
                            framework = fw
                            break
                except Exception:
                    pass
            if framework:
                break

    # Project type
    project_type = "unknown"
    if (Path(repo_path) / "package.json").exists(): project_type = "node"
    elif (Path(repo_path) / "pyproject.toml").exists(): project_type = "python"
    elif (Path(repo_path) / "Cargo.toml").exists(): project_type = "rust"
    elif (Path(repo_path) / "go.mod").exists(): project_type = "go"

    return {
        "name": name,
        "path": repo_path,
        "remote": remote,
        "description": description,
        "project_type": project_type,
        "framework": framework,
        "languages": dict(sorted(langs.items(), key=lambda x: -x[1])[:8]),
        "commit_count": commit_count,
        "first_commit": first_commit,
        "last_commit": last_commit,
        "contributors": contributors,
        "is_active": last_commit >= (datetime.now().strftime("%Y-%m-") + "00")[:7]
                      if last_commit else False,
    }


def _infer_wing(repo: dict) -> str:
    """Assign a wing based on remote URL or path."""
    remote = repo.get("remote", "")
    path = repo.get("path", "")

    # Skip plugin/config/dotfile repos
    for skip in ["/.claude/", "/.zsh/", "/.nvm", "/.cargo/git/", "/.codex/"]:
        if skip in path:
            return ""

    # By GitHub org
    import re
    org_match = re.search(r"github\.com[:/]([^/]+)/", remote)
    if org_match:
        return org_match.group(1).lower().replace("-", "_")

    return "local"


def _detect_languages() -> list[dict]:
    """Detect installed language runtimes."""
    checks = [
        ("Node.js", "node --version"),
        ("Python", "python3 --version"),
        ("Rust", "rustc --version"),
        ("Go", "go version"),
        ("Ruby", "ruby --version"),
        ("Java", "java -version 2>&1"),
        ("Bun", "bun --version"),
        ("Deno", "deno --version"),
    ]
    runtimes = []
    for name, cmd in checks:
        raw = _run(cmd, 5)
        if raw:
            import re
            version = re.search(r"(\d+\.\d+[\.\d]*)", raw)
            runtimes.append({"name": name, "version": version.group(1) if version else "?"})
    return runtimes


def _detect_package_managers() -> list[str]:
    """Detect installed package managers and CLIs."""
    tools = []
    for name, cmd in [
        ("npm", "npm --version"), ("yarn", "yarn --version"),
        ("pnpm", "pnpm --version"), ("bun", "bun --version"),
        ("pip", "pip3 --version"), ("uv", "uv --version"),
        ("poetry", "poetry --version"), ("cargo", "cargo --version"),
        ("brew", "brew --version"), ("docker", "docker --version"),
        ("gh", "gh --version"), ("kubectl", "kubectl version --client --short 2>&1"),
    ]:
        if _run(cmd, 5):
            tools.append(name)
    return tools


def _shell_profile() -> dict:
    """Extract shell profile data."""
    shell = os.environ.get("SHELL", "unknown")
    home = Path.home()

    hist_file = home / ".zsh_history" if "zsh" in shell else home / ".bash_history"
    hist_count = int(_run(f'wc -l < "{hist_file}"') or "0")

    # Top commands
    if "zsh" in shell:
        cmd = f"""cat "{hist_file}" | sed 's/^: [0-9]*:[0-9]*;//' | awk '{{print $1}}' | sort | uniq -c | sort -rn | head -15"""
    else:
        cmd = f"""cat "{hist_file}" | awk '{{print $1}}' | sort | uniq -c | sort -rn | head -15"""

    top_cmds = []
    for line in _run(cmd, 10).split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].isidentifier():
            top_cmds.append(f"{parts[1]}: {parts[0]}")

    # Dotfiles
    dotfiles = [
        f for f in [
            ".zshrc", ".bashrc", ".bash_profile", ".gitconfig",
            ".npmrc", ".editorconfig", ".vimrc", ".tmux.conf",
        ]
        if (home / f).exists()
    ]

    return {
        "shell": shell,
        "history_count": hist_count,
        "top_commands": top_cmds[:15],
        "dotfiles": dotfiles,
    }


def _cloud_providers() -> list[str]:
    """Detect cloud provider configurations."""
    home = Path.home()
    providers = []
    for path, name in [
        (".aws", "AWS"), (".config/gcloud", "Google Cloud"),
        (".azure", "Azure"), (".vercel", "Vercel"),
        (".railway", "Railway"), (".config/flyctl", "Fly.io"),
        (".netlify", "Netlify"), (".supabase", "Supabase"),
        (".kube/config", "Kubernetes"),
    ]:
        if (home / path).exists():
            providers.append(name)
    return providers


def _agent_sessions() -> list[dict]:
    """
    Discover AI coding agent sessions and extract project context.

    Scans for Claude Code, Cursor, and Codex session directories.
    Reads CLAUDE.md files from discovered projects (these are designed
    to be shared context). Does NOT read actual conversation content.
    """
    home = Path.home()
    sessions = []

    # ── Claude Code (~/.claude/projects/) ──
    claude_projects_dir = home / ".claude" / "projects"
    if claude_projects_dir.is_dir():
        claude_data = {"agent": "claude-code", "projects": [], "claude_md_files": {}}
        try:
            for entry in claude_projects_dir.iterdir():
                if not entry.is_dir():
                    continue
                # Claude Code encodes paths: -Users-name-project → /Users/name/project
                decoded = "/" + entry.name.replace("-", "/")
                if Path(decoded).is_dir():
                    project_name = Path(decoded).name

                    # Read CLAUDE.md if it exists (meant to be shared context)
                    claude_md = Path(decoded) / "CLAUDE.md"
                    if claude_md.exists():
                        try:
                            content = claude_md.read_text()[:5000]
                            claude_data["claude_md_files"][project_name] = content
                        except Exception:
                            pass

                    # Count sessions
                    session_dir = entry / "sessions"
                    session_count = 0
                    if session_dir.is_dir():
                        session_count = len(list(session_dir.iterdir()))

                    claude_data["projects"].append({
                        "name": project_name,
                        "path": decoded,
                        "sessions": session_count,
                        "has_claude_md": claude_md.exists(),
                    })
        except Exception:
            pass

        if claude_data["projects"]:
            sessions.append(claude_data)

    # ── Cursor (~/.cursor/) ──
    cursor_dir = home / ".cursor"
    if cursor_dir.is_dir():
        cursor_data = {"agent": "cursor", "projects": []}
        # Cursor stores workspace state
        ws_dir = cursor_dir / "User" / "workspaceStorage"
        if ws_dir.is_dir():
            try:
                cursor_data["projects"] = [
                    {"name": d.name} for d in ws_dir.iterdir() if d.is_dir()
                ]
            except Exception:
                pass
        if cursor_data["projects"]:
            sessions.append(cursor_data)

    # ── Codex (~/.codex/) ──
    codex_dir = home / ".codex"
    if codex_dir.is_dir():
        sessions.append({"agent": "codex", "projects": []})

    return sessions


def _obsidian_vaults() -> list[dict]:
    """Find Obsidian vaults by looking for .obsidian directories."""
    home = Path.home()
    vaults = []

    # Search common locations
    search_roots = [str(home), str(home / "Documents")]
    for root in search_roots:
        obsidian_dirs = _run(
            f'find "{root}" -maxdepth 4 -name ".obsidian" -type d 2>/dev/null | head -10',
            timeout=10,
        )
        for obs_dir in obsidian_dirs.split("\n"):
            if not obs_dir:
                continue
            vault_dir = Path(obs_dir).parent
            md_count = int(_run(
                f'find "{vault_dir}" -maxdepth 3 -name "*.md" -type f 2>/dev/null | wc -l'
            ) or "0")
            if md_count > 0:
                # Read key files from vault root
                key_files = {}
                for kf in ["README.md", "index.md", "about.md"]:
                    kf_path = vault_dir / kf
                    if kf_path.exists():
                        try:
                            key_files[kf] = kf_path.read_text()[:3000]
                        except Exception:
                            pass
                vaults.append({
                    "path": str(vault_dir),
                    "name": vault_dir.name,
                    "note_count": md_count,
                    "key_files": key_files,
                })

    # Deduplicate
    seen = set()
    unique = []
    for v in vaults:
        if v["path"] not in seen:
            seen.add(v["path"])
            unique.append(v)
    return unique


# ── Main entry point ──


def mine_device(
    palace_path: str,
    home_dir: str = None,
    wing: str = None,
    agent: str = "mempalace",
    max_depth: int = 8,
    dry_run: bool = False,
):
    """
    Scan the machine and fill the palace. Solves the cold start problem.

    Discovers git repos, languages, tools, shell profile, cloud connections,
    knowledge bases, and files everything as verbatim drawers.
    """
    home = home_dir or str(Path.home())
    collection = get_collection(palace_path)
    before_count = collection.count()

    username = os.environ.get("USER", "user")
    total_drawers = 0
    wing_counts = defaultdict(int)
    room_counts = defaultdict(int)

    print(f"\n{'=' * 55}")
    print(f"  mempalace mine-device")
    print(f"  scanning: {home}")
    print(f"  palace:   {palace_path}")
    print(f"{'=' * 55}\n")

    # ── Agent sessions (Claude Code, Cursor, Codex) ──

    print("  Scanning for AI agent sessions...")
    agent_sessions = _agent_sessions()
    w = wing or "self"
    for session in agent_sessions:
        agent_name = session["agent"]
        projects = session.get("projects", [])
        claude_mds = session.get("claude_md_files", {})
        print(f"  ✓ {agent_name}: {len(projects)} projects")

        # File agent overview
        overview_lines = [f"AI coding agent: {agent_name}", f"Projects: {len(projects)}", ""]
        for p in projects:
            flags = []
            if p.get("has_claude_md"):
                flags.append("CLAUDE.md")
            if p.get("sessions"):
                flags.append(f"{p['sessions']} sessions")
            flag_str = f" ({', '.join(flags)})" if flags else ""
            overview_lines.append(f"  {p['name']}{flag_str}: {p.get('path', '')}")
        overview = "\n".join(overview_lines)

        if dry_run:
            print(f"    [DRY RUN] {agent_name} overview → wing:{w} room:{agent_name} "
                  f"({len(_chunk_text(overview))} drawers)")
        else:
            total_drawers += _file_content(collection, w, agent_name, overview,
                                           f"~/.{agent_name}", agent)
            room_counts[agent_name] += 1

        # File CLAUDE.md files (these are designed to be shared context)
        for project_name, content in claude_mds.items():
            room = f"{project_name}-context"
            if dry_run:
                print(f"    [DRY RUN] CLAUDE.md:{project_name} → wing:{w} room:{room} "
                      f"({len(_chunk_text(content))} drawers)")
            else:
                added = _file_content(collection, w, room, content,
                                      f"{project_name}/CLAUDE.md", agent)
                total_drawers += added
                room_counts[room] += 1

    # ── Obsidian vaults ──

    print("  Scanning for Obsidian vaults...")
    vaults = _obsidian_vaults()
    for vault in vaults:
        print(f"  ✓ Vault: {vault['name']} ({vault['note_count']} notes)")
        for filename, content in vault.get("key_files", {}).items():
            room = f"vault-{vault['name']}"
            if dry_run:
                print(f"    [DRY RUN] {filename} → wing:{w} room:{room} "
                      f"({len(_chunk_text(content))} drawers)")
            else:
                added = _file_content(collection, w, room, content,
                                      f"{vault['path']}/{filename}", agent)
                total_drawers += added
                room_counts[room] += 1

    # ── Git repos ──

    print("\n  Scanning for git repositories...")
    repo_paths = _find_git_repos(home, max_depth)
    # Deduplicate
    repo_paths = list(dict.fromkeys(repo_paths))
    print(f"  Found {len(repo_paths)} repos, analyzing...")

    for i, repo_path in enumerate(repo_paths):
        info = _repo_info(repo_path)
        if info["commit_count"] == 0:
            continue

        w = wing or _infer_wing(info)
        if not w:
            continue  # skip dotfile/plugin repos

        room = info["name"].lower().replace(" ", "-").replace(".", "-")

        # Build verbatim description
        lines = [f"Project: {info['name']}"]
        if info["description"]:
            lines.append(f"Description: {info['description']}")
        if info["remote"]:
            lines.append(f"Remote: {info['remote']}")
        if info["project_type"] != "unknown":
            lines.append(f"Type: {info['project_type']}")
        if info["framework"]:
            lines.append(f"Framework: {info['framework']}")
        if info["languages"]:
            top = list(info["languages"].items())[:5]
            lines.append(f"Languages: {', '.join(f'{l} ({c} files)' for l, c in top)}")
        lines.append(f"Commits: {info['commit_count']}")
        if info["first_commit"]:
            lines.append(f"Started: {info['first_commit']}")
        if info["last_commit"]:
            lines.append(f"Last commit: {info['last_commit']}")
        lines.append(f"Active: {'yes' if info['is_active'] else 'no'}")
        if info["contributors"]:
            lines.append(f"Contributors: {', '.join(info['contributors'][:10])}")

        content = "\n".join(lines)

        if dry_run:
            chunks = _chunk_text(content)
            print(f"  [{i+1:4}/{len(repo_paths)}] {info['name'][:40]:40} "
                  f"→ wing:{w} room:{room} ({len(chunks)} drawers)")
        else:
            added = _file_content(collection, w, room, content, repo_path, agent)
            total_drawers += added
            if added:
                print(f"  ✓ [{i+1:4}/{len(repo_paths)}] {info['name'][:40]:40} +{added}")

        wing_counts[w] += 1
        room_counts[room] += 1

    # ── Languages & tools ──

    print("\n  Scanning languages & tools...")
    w = wing or "self"

    runtimes = _detect_languages()
    if runtimes:
        content = "Installed language runtimes:\n" + "\n".join(
            f"  {r['name']} {r['version']}" for r in runtimes
        )
        if dry_run:
            print(f"    [DRY RUN] languages → {len(runtimes)} runtimes")
        else:
            total_drawers += _file_content(collection, w, "languages", content,
                                           "device-scan", agent)

    pkg_managers = _detect_package_managers()
    if pkg_managers:
        content = "Package managers & CLIs:\n" + "\n".join(f"  {t}" for t in pkg_managers)
        if dry_run:
            print(f"    [DRY RUN] tools → {len(pkg_managers)} managers")
        else:
            total_drawers += _file_content(collection, w, "tools", content,
                                           "device-scan", agent)

    # Brew casks
    casks = [c for c in _run("brew list --cask 2>/dev/null", 10).split("\n") if c]
    if casks:
        content = "Homebrew casks (GUI applications):\n" + "\n".join(f"  {c}" for c in casks)
        if not dry_run:
            total_drawers += _file_content(collection, w, "applications", content,
                                           "device-scan", agent)

    # ── Shell profile ──

    print("  Scanning shell profile...")
    shell = _shell_profile()
    shell_content = (
        f"Shell: {shell['shell']}\n"
        f"History: {shell['history_count']} commands\n"
        f"Dotfiles: {', '.join(shell['dotfiles'])}\n\n"
        f"Most used commands:\n" + "\n".join(f"  {c}" for c in shell["top_commands"])
    )
    if dry_run:
        print(f"    [DRY RUN] shell → {shell['history_count']} commands")
    else:
        total_drawers += _file_content(collection, w, "shell", shell_content,
                                       "device-scan", agent)

    # ── Cloud providers ──

    print("  Scanning cloud connections...")
    providers = _cloud_providers()
    if providers:
        content = "Cloud providers configured:\n" + "\n".join(f"  {p}" for p in providers)
        if dry_run:
            print(f"    [DRY RUN] cloud → {', '.join(providers)}")
        else:
            total_drawers += _file_content(collection, w, "cloud", content,
                                           "device-scan", agent)

    # ── Machine identity ──

    hostname = _run("hostname -s") or "unknown"
    os_ver = _run("sw_vers -productVersion 2>/dev/null") or _run("uname -r")
    arch = _run("uname -m")
    cpu = _run("sysctl -n machdep.cpu.brand_string 2>/dev/null") or _run("uname -p")

    machine_content = (
        f"Machine: {hostname}\n"
        f"OS: {sys.platform} {os_ver} ({arch})\n"
        f"CPU: {cpu}\n"
        f"User: {username}\n"
    )
    if not dry_run:
        total_drawers += _file_content(collection, w, "machine", machine_content,
                                       "device-scan", agent)

    # ── Summary ──

    after_count = collection.count()
    new_drawers = after_count - before_count

    print(f"\n{'=' * 55}")
    print("  Done.")
    print(f"  Repos scanned:   {len(repo_paths)}")
    print(f"  Drawers filed:   {new_drawers} new ({total_drawers - new_drawers} already existed)")
    print(f"  Palace total:    {after_count} drawers")
    print(f"\n  By wing:")
    for w_name, count in sorted(wing_counts.items(), key=lambda x: -x[1]):
        print(f"    {w_name:20} {count} repos")
    if agent_sessions:
        print(f"\n  Agent sessions:  {', '.join(s['agent'] for s in agent_sessions)}")
    if vaults:
        print(f"  Obsidian vaults: {', '.join(v['name'] for v in vaults)}")
    if providers:
        print(f"  Cloud providers: {', '.join(providers)}")
    print(f"  Runtimes:        {', '.join(r['name'] for r in runtimes)}")
    if dry_run:
        print("\n  (dry run — nothing was filed)")
    else:
        print(f'\n  Next: mempalace search "what you\'re looking for"')
    print(f"{'=' * 55}\n")
