#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/setup_private_repo.sh [options]

Options:
  --repo-name NAME        Name of the GitHub repository to create or use.
  --owner USER            GitHub owner. Auto-detected from gh when omitted.
  --repo-url URL          Use an existing repository URL instead of creating one with gh.
  --remote-name NAME      Remote name for your private repository. Default: origin.
  --upstream-name NAME    Remote name to keep the original source. Default: upstream.
  --no-keep-upstream      Replace the current origin instead of preserving the source repo.
  --public                Create a public repository instead of a private one.
  --push-branches         Push all local branches after setup.
  --help                  Show this help message.

Examples:
  scripts/setup_private_repo.sh --repo-name supamem_koo
  scripts/setup_private_repo.sh --repo-url https://github.com/you/supamem_koo.git
EOF
}

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        exit 1
    fi
}

repo_name=""
owner=""
repo_url=""
remote_name="origin"
upstream_name="upstream"
visibility="private"
keep_upstream=1
push_branches=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-name)
            repo_name="$2"
            shift 2
            ;;
        --owner)
            owner="$2"
            shift 2
            ;;
        --repo-url)
            repo_url="$2"
            shift 2
            ;;
        --remote-name)
            remote_name="$2"
            shift 2
            ;;
        --upstream-name)
            upstream_name="$2"
            shift 2
            ;;
        --no-keep-upstream)
            keep_upstream=0
            shift
            ;;
        --public)
            visibility="public"
            shift
            ;;
        --push-branches)
            push_branches=1
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage
            exit 1
            ;;
    esac
done

require_command git

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Run this script from inside the repository you want to publish." >&2
    exit 1
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

default_branch="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)"
if [[ -z "$default_branch" ]]; then
    default_branch="$(git branch --show-current)"
fi
if [[ -z "$default_branch" ]]; then
    default_branch="main"
fi

current_origin=""
if git remote get-url origin >/dev/null 2>&1; then
    current_origin="$(git remote get-url origin)"
fi

if [[ -z "$repo_url" ]]; then
    require_command gh
    if ! gh auth status >/dev/null 2>&1; then
        cat <<'EOF' >&2
GitHub CLI is not authenticated.
Run: gh auth login
Or rerun this script with --repo-url https://github.com/<you>/<repo>.git
EOF
        exit 1
    fi

    if [[ -z "$owner" ]]; then
        owner="$(gh api user --jq .login)"
    fi

    if [[ -z "$repo_name" ]]; then
        repo_name="$(basename "$repo_root")"
    fi

    repo_url="https://github.com/${owner}/${repo_name}.git"

    if ! gh repo view "${owner}/${repo_name}" >/dev/null 2>&1; then
        gh repo create "${owner}/${repo_name}" --"${visibility}" --source=. --remote=__tmp_private__ --push=false >/dev/null
        git remote remove __tmp_private__ >/dev/null 2>&1 || true
        echo "Created ${visibility} repository: ${owner}/${repo_name}"
    else
        echo "Repository already exists: ${owner}/${repo_name}"
    fi
else
    if [[ -z "$repo_name" ]]; then
        repo_name="$(basename "${repo_url%.git}")"
    fi
fi

if [[ "$keep_upstream" -eq 1 && -n "$current_origin" && "$current_origin" != "$repo_url" ]]; then
    if git remote get-url "$upstream_name" >/dev/null 2>&1; then
        existing_upstream="$(git remote get-url "$upstream_name")"
        if [[ "$existing_upstream" != "$current_origin" ]]; then
            echo "Remote '$upstream_name' already exists and points elsewhere: $existing_upstream" >&2
            exit 1
        fi
    else
        if [[ "$remote_name" == "origin" ]]; then
            git remote rename origin "$upstream_name"
        else
            git remote add "$upstream_name" "$current_origin"
        fi
        echo "Preserved source repository as '$upstream_name'"
    fi
fi

if git remote get-url "$remote_name" >/dev/null 2>&1; then
    git remote set-url "$remote_name" "$repo_url"
else
    git remote add "$remote_name" "$repo_url"
fi

echo "Configured '$remote_name' -> $repo_url"

git fetch "$remote_name" >/dev/null 2>&1 || true

git push -u "$remote_name" "$default_branch"

if [[ "$push_branches" -eq 1 ]]; then
    while IFS= read -r branch_name; do
        if [[ "$branch_name" != "$default_branch" ]]; then
            git push -u "$remote_name" "$branch_name"
        fi
    done < <(git for-each-ref --format='%(refname:short)' refs/heads)
fi

cat <<EOF

Private repository setup complete.

Repository root : $repo_root
Primary remote  : $remote_name -> $repo_url
Default branch  : $default_branch
EOF

if [[ "$keep_upstream" -eq 1 && -n "$current_origin" && "$current_origin" != "$repo_url" ]]; then
    echo "Upstream remote : $upstream_name -> $current_origin"
fi

cat <<'EOF'

Recommended next steps:
  1. Verify remotes with: git remote -v
  2. Install locally with: pip install -e ".[dev]"
  3. Initialize your personal storage with: mempalace init <project-dir>
  4. Keep your memory data outside the repo, usually under ~/.mempalace/
EOF
