"""Regression tests for issue #225 — MCP stdio protection.

The MCP protocol multiplexes JSON-RPC over stdio. Stdout MUST carry only
valid JSON-RPC messages. Several transitive deps (chromadb → onnxruntime,
posthog telemetry) print banners and warnings to stdout — sometimes at
the C level — which broke Claude Desktop's JSON parser on Windows.

The fix in mcp_server.py redirects stdout → stderr at both the Python
and file-descriptor level during module import, then restores the real
stdout in main() before entering the protocol loop.
"""

import subprocess
import sys
import textwrap
import json
import os
import sqlite3


def test_module_import_redirects_stdout_to_stderr():
    """At import time, sys.stdout must point at sys.stderr so any stray
    print() from a transitive dependency is sent to stderr."""
    code = textwrap.dedent(
        """
        import sys
        original_stdout = sys.stdout
        from mempalace import mcp_server
        assert sys.stdout is sys.stderr, (
            f"Expected sys.stdout to be redirected to sys.stderr, "
            f"got: {sys.stdout!r}"
        )
        assert mcp_server._REAL_STDOUT is original_stdout, (
            "mcp_server._REAL_STDOUT must hold the original stdout"
        )
        print("OK", file=sys.stderr)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"


def test_restore_stdout_returns_real_stdout():
    """_restore_stdout() must reassign sys.stdout to the original handle
    so main() can write JSON-RPC responses to the real stdout."""
    code = textwrap.dedent(
        """
        import sys
        original_stdout = sys.stdout
        from mempalace import mcp_server
        assert sys.stdout is sys.stderr
        mcp_server._restore_stdout()
        assert sys.stdout is original_stdout, (
            f"After _restore_stdout(), sys.stdout must be the original; "
            f"got: {sys.stdout!r}"
        )
        mcp_server._restore_stdout()  # idempotent
        print("OK", file=sys.stderr)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"


def test_mcp_server_no_stdout_noise_on_clean_exit():
    """`python -m mempalace.mcp_server` with empty stdin must produce
    nothing on stdout. Empty input → readline() returns '' → main()
    breaks out cleanly. Any stdout content here would corrupt the
    JSON-RPC stream in real use."""
    proc = subprocess.run(
        [sys.executable, "-m", "mempalace.mcp_server"],
        input=b"",
        capture_output=True,
        timeout=60,
    )
    assert (
        proc.stdout == b""
    ), f"stdout must be empty before the first JSON-RPC response, but got: {proc.stdout!r}"


def test_mcp_server_reads_utf8_json_rpc_under_legacy_windows_locale(tmp_path):
    """Claude sends MCP JSON-RPC as UTF-8 even when Windows console locale is CP936.

    If the server lets Python decode stdin with the process locale, Chinese tool
    arguments are mojibake before json.loads() sees them.
    """
    palace = tmp_path / "palace"
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "mempalace_kg_add",
            "arguments": {
                "subject": "杨工",
                "predicate": "关系",
                "object": "钥匙",
                "valid_from": "2026-05-01",
            },
        },
    }
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp936"

    proc = subprocess.run(
        [sys.executable, "-m", "mempalace.mcp_server", "--palace", str(palace)],
        input=(json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=60,
    )

    assert proc.returncode == 0, f"stdout: {proc.stdout!r}\nstderr: {proc.stderr!r}"
    response = json.loads(proc.stdout)
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["success"] is True
    assert content["fact"] == "杨工 → 关系 → 钥匙"

    conn = sqlite3.connect(str(palace / "knowledge_graph.sqlite3"))
    try:
        entities = conn.execute("SELECT id, name FROM entities ORDER BY id").fetchall()
        triples = conn.execute("SELECT subject, predicate, object FROM triples").fetchall()
    finally:
        conn.close()

    assert entities == [("杨工", "杨工"), ("钥匙", "钥匙")]
    assert triples == [("杨工", "关系", "钥匙")]
