#!/usr/bin/env python3
"""
Export Slack conversations from the local macOS Slack desktop session.

Output format is Slack-export-like:

    output_dir/
      metadata.json
      channels.json
      users.json
      <channel-name>/
        2026-04-08.json

The JSON day files contain lists of Slack message objects so MemPalace can
ingest them with:

    mempalace mine <output_dir> --mode convos

Security note:
    This script reads your active Slack desktop session credentials from local
    macOS resources so it can call https://slack.com/api/* on your behalf:
      - Slack Safe Storage from macOS Keychain
      - the encrypted `d` cookie from Slack's Cookies SQLite database
      - the local `xoxc-` token from Slack's LevelDB files
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional


SLACK_APP_DIR = Path.home() / "Library/Application Support/Slack"
COOKIE_DB = SLACK_APP_DIR / "Cookies"
LOCAL_STORAGE_DIR = SLACK_APP_DIR / "Local Storage/leveldb"
DEFAULT_TYPES = ("public_channel", "private_channel", "mpim", "im")
SAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")
DESCRIPTION = __doc__.split("\n\nSecurity note:", 1)[0]
SECURITY_EPILOG = """
Security note:
  - Reads `Slack Safe Storage` from macOS Keychain via `security find-generic-password`
  - Opens `~/Library/Application Support/Slack/Cookies` read-only to read the encrypted `d` cookie
  - Scans `~/Library/Application Support/Slack/Local Storage/leveldb/*.ldb` for the local `xoxc-` token
  - Uses those credentials only for requests to https://slack.com/api/*
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=SECURITY_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write the export into.",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="UTC start date, inclusive, in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="UTC end date, exclusive, in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--types",
        nargs="+",
        default=list(DEFAULT_TYPES),
        choices=list(DEFAULT_TYPES),
        help="Conversation types to export.",
    )
    parser.add_argument(
        "--limit-conversations",
        type=int,
        default=0,
        help="Optional cap on conversations for testing.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress as the export runs.",
    )
    return parser.parse_args()


def utc_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def slack_safe_storage_key() -> str:
    for cmd in (
        ["security", "find-generic-password", "-w", "-s", "Slack Safe Storage"],
        ["security", "find-generic-password", "-w", "-a", "Slack Safe Storage"],
    ):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            return proc.stdout.strip()
    raise RuntimeError("Could not find 'Slack Safe Storage' in macOS Keychain")


def encrypted_cookie_hex(name: str) -> str:
    cookie_db_uri = f"{COOKIE_DB.resolve().as_uri()}?mode=ro"
    try:
        with sqlite3.connect(cookie_db_uri, uri=True) as conn:
            row = conn.execute(
                """
                select hex(encrypted_value)
                from cookies
                where host_key = '.slack.com' and name = ?
                limit 1
                """,
                (name,),
            ).fetchone()
    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            f"Could not read Slack cookie database at {COOKIE_DB}. "
            "Quit Slack and retry if the database is locked."
        ) from exc
    if not row or not row[0]:
        raise RuntimeError(f"Could not read Slack cookie '{name}'")
    return row[0]


def decrypt_chromium_cookie(cookie_hex: str, safe_storage_key: str) -> str:
    encrypted = bytes.fromhex(cookie_hex)
    if not encrypted.startswith(b"v10"):
        raise RuntimeError("Unexpected Chromium cookie format")
    key = hashlib.pbkdf2_hmac(
        "sha1",
        safe_storage_key.encode(),
        b"saltysalt",
        1003,
        16,
    )
    proc = subprocess.run(
        ["openssl", "enc", "-aes-128-cbc", "-d", "-K", key.hex(), "-iv", "20" * 16],
        input=encrypted[3:],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Cookie decryption failed: {proc.stderr.decode().strip()}")
    return proc.stdout.decode("utf-8", "replace")


def desktop_token() -> str:
    ldb_files = sorted(str(path) for path in LOCAL_STORAGE_DIR.glob("*.ldb"))
    if not ldb_files:
        raise RuntimeError(f"No .ldb files found in {LOCAL_STORAGE_DIR}")
    proc = subprocess.run(
        ["strings", *ldb_files],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("Could not scan Slack local storage for desktop token")
    match = re.search(r"(xoxc-[A-Za-z0-9-]+)", proc.stdout)
    if not match:
        raise RuntimeError("Could not find Slack desktop xoxc token")
    return match.group(1)


def desktop_cookie() -> str:
    safe_key = slack_safe_storage_key()
    decrypted = decrypt_chromium_cookie(encrypted_cookie_hex("d"), safe_key)
    match = re.search(r"(xoxd-[A-Za-z0-9%._/+=-]+)", decrypted)
    if not match:
        raise RuntimeError("Could not find Slack desktop xoxd cookie")
    return match.group(1)


class SlackSession:
    def __init__(self, token: str, desktop_cookie_value: str):
        self.token = token
        self.desktop_cookie_value = desktop_cookie_value

    def api(self, method: str, params: Optional[dict] = None) -> dict:
        params = params or {}
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"https://slack.com/api/{method}?{query}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Cookie": f"d={self.desktop_cookie_value}",
                "User-Agent": "Mozilla/5.0",
            },
        )
        while True:
            try:
                with urllib.request.urlopen(request) as response:
                    payload = json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    retry_after = int(exc.headers.get("Retry-After", "1"))
                    time.sleep(retry_after)
                    continue
                raise
            if not payload.get("ok"):
                error = payload.get("error", "unknown_error")
                if error == "ratelimited":
                    time.sleep(1)
                    continue
                raise RuntimeError(f"Slack API {method} failed: {error}")
            return payload

    def auth_test(self) -> dict:
        return self.api("auth.test")


def sanitize_slug(value: str) -> str:
    slug = SAFE_SLUG_RE.sub("_", value).strip("._")
    return slug or "unknown"


def conversation_slug(conversation: dict) -> str:
    name = conversation.get("name")
    if name:
        return sanitize_slug(name)
    if conversation.get("is_im"):
        user_id = conversation.get("user", "unknown")
        return sanitize_slug(f"dm-{user_id.lower()}")
    if conversation.get("is_mpim"):
        return sanitize_slug(f"mpim-{conversation['id'].lower()}")
    return sanitize_slug(conversation["id"].lower())


def export_conversations(
    session: SlackSession,
    output_dir: Path,
    start: datetime,
    end: datetime,
    types: Iterable[str],
    limit_conversations: int = 0,
    verbose: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    start_ts = start.timestamp()
    end_ts = end.timestamp()

    channels_meta: List[dict] = []
    users_seen: set[str] = set()
    conversation_count = 0
    total_messages = 0

    cursor = None
    while True:
        params = {
            "types": ",".join(types),
            "limit": 200,
            "exclude_archived": "false",
        }
        if cursor:
            params["cursor"] = cursor
        page = session.api("users.conversations", params)
        conversations = page.get("channels", [])

        for conversation in conversations:
            if limit_conversations and conversation_count >= limit_conversations:
                break

            slug = conversation_slug(conversation)
            conv_dir = output_dir / slug
            conv_dir.mkdir(parents=True, exist_ok=True)
            channels_meta.append(
                {
                    "id": conversation["id"],
                    "name": slug,
                    "is_channel": conversation.get("is_channel", False),
                    "is_group": conversation.get("is_group", False),
                    "is_im": conversation.get("is_im", False),
                    "is_mpim": conversation.get("is_mpim", False),
                    "is_private": conversation.get("is_private", False),
                    "created": conversation.get("created"),
                }
            )

            if verbose:
                print(f"[export] {conversation['id']} -> {slug}", flush=True)

            day_buckets: Dict[str, List[dict]] = defaultdict(list)
            history_cursor = None
            conversation_messages = 0

            page_count = 0
            while True:
                history_params = {
                    "channel": conversation["id"],
                    "limit": 200,
                    "oldest": f"{start_ts:.6f}",
                    "latest": f"{end_ts:.6f}",
                    "inclusive": "true",
                }
                if history_cursor:
                    history_params["cursor"] = history_cursor
                history = session.api("conversations.history", history_params)
                messages = history.get("messages", [])
                page_count += 1

                for message in messages:
                    message_ts = float(message["ts"])
                    if message_ts < start_ts or message_ts >= end_ts:
                        continue
                    day = datetime.fromtimestamp(message_ts, tz=timezone.utc).strftime("%Y-%m-%d")
                    day_buckets[day].append(message)
                    conversation_messages += 1
                    user_id = message.get("user")
                    if user_id:
                        users_seen.add(user_id)

                history_cursor = history.get("response_metadata", {}).get("next_cursor") or None
                if verbose and (page_count == 1 or page_count % 10 == 0):
                    print(
                        f"[export] {slug}: page {page_count}, collected {conversation_messages} messages",
                        flush=True,
                    )
                if not history_cursor:
                    break

            for day, messages in sorted(day_buckets.items()):
                with (conv_dir / f"{day}.json").open("w", encoding="utf-8") as handle:
                    json.dump(messages, handle, ensure_ascii=False, indent=2)

            total_messages += conversation_messages
            conversation_count += 1

            if verbose:
                print(
                    f"[export] {slug}: {conversation_messages} messages across {len(day_buckets)} day files",
                    flush=True,
                )

        if limit_conversations and conversation_count >= limit_conversations:
            break

        cursor = page.get("response_metadata", {}).get("next_cursor") or None
        if not cursor:
            break

    with (output_dir / "channels.json").open("w", encoding="utf-8") as handle:
        json.dump(channels_meta, handle, ensure_ascii=False, indent=2)

    with (output_dir / "users.json").open("w", encoding="utf-8") as handle:
        json.dump(
            [{"id": user_id} for user_id in sorted(users_seen)],
            handle,
            ensure_ascii=False,
            indent=2,
        )

    metadata = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "conversation_types": list(types),
        "conversation_count": conversation_count,
        "message_count": total_messages,
    }
    with (output_dir / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)

    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                **metadata,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    args = parse_args()
    start = utc_date(args.start)
    end = utc_date(args.end)
    if end <= start:
        raise SystemExit("--end must be after --start")

    session = SlackSession(token=desktop_token(), desktop_cookie_value=desktop_cookie())
    auth = session.auth_test()

    if args.verbose:
        print(
            f"[auth] team={auth['team']} user={auth['user']} team_id={auth['team_id']}",
            flush=True,
        )

    export_conversations(
        session=session,
        output_dir=Path(args.output_dir).expanduser().resolve(),
        start=start,
        end=end,
        types=args.types,
        limit_conversations=args.limit_conversations,
        verbose=args.verbose,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
