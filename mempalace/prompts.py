"""Shared prompt helpers for interactive and non-interactive CLI flows."""

import sys


def prompt_text(prompt: str, default: str = "") -> str:
    try:
        raw = input(prompt).strip()
    except EOFError:
        fallback = default or "accept"
        print(f"\n  No interactive input available — defaulting to: {fallback}")
        return default
    return raw or default


def prompt_yes_no(prompt: str, default: str = "y") -> bool:
    answer = prompt_text(prompt, default=default).lower()
    if not answer:
        return default == "y"
    return answer.startswith("y")


def stdin_is_interactive() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False
