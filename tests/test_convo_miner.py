import os
import tempfile
import shutil
import chromadb
from mempalace.convo_miner import mine_convos, _extract_assistant_turns


def test_convo_mining():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
        )

    palace_path = os.path.join(tmpdir, "palace")
    mine_convos(tmpdir, palace_path, wing="test_convos")

    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")
    assert col.count() >= 2

    # Verify search works
    results = col.query(query_texts=["memory persistence"], n_results=1)
    assert len(results["documents"][0]) > 0

    shutil.rmtree(tmpdir, ignore_errors=True)


def test_extract_assistant_turns_returns_full_response():
    """_extract_assistant_turns should capture the full AI response, not just 8 lines."""
    content = (
        "> What is exponential backoff?\n"
        "Exponential backoff is a retry strategy.\n"
        "Start at 1 second, double each attempt.\n"
        "Add random jitter to avoid thundering herd.\n"
        "Cap retries at a maximum interval, typically 60 seconds.\n"
        "Always set a maximum retry count to prevent infinite loops.\n"
        "Log each retry for observability.\n"
        "Consider circuit breakers for cascading failures.\n"
        "Return the error to the caller after the final retry.\n"
        "This is line 9 of the response that would be cut off otherwise.\n\n"
        "> Any final tips?\n"
        "Monitor retry rates as a leading indicator of downstream health.\n\n"
    )
    chunks = _extract_assistant_turns(content)
    assert len(chunks) == 2
    # Full first response — not cut at 8 lines
    assert "line 9" in chunks[0]["content"]
    # Second response also captured
    assert "downstream health" in chunks[1]["content"]


def test_convo_mining_include_assistant_indexes_standalone_turns():
    """With include_assistant=True, assistant responses should be separately indexed."""
    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
            f.write(
                "> What is the recommended retry strategy?\n"
                "Use exponential backoff with jitter. Start at 1s, cap at 60s.\n\n"
                "> Any other tips?\n"
                "Always set a maximum retry count. Consider circuit breakers for cascading failure prevention.\n\n"
            )

        palace_path = os.path.join(tmpdir, "palace")
        mine_convos(tmpdir, palace_path, wing="test_convos", include_assistant=True)

        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")

        all_results = col.get(include=["metadatas", "documents"])
        assistant_docs = [
            doc
            for doc, meta in zip(all_results["documents"], all_results["metadatas"])
            if meta.get("turn_role") == "assistant"
        ]

        assert len(assistant_docs) >= 2, "Should have one drawer per assistant turn"
        combined = " ".join(assistant_docs)
        assert "exponential backoff" in combined
        assert "circuit breaker" in combined or "circuit breakers" in combined

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_convo_mining_no_assistant_metadata_by_default():
    """Without include_assistant, no drawers should carry turn_role=assistant metadata."""
    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
            f.write(
                "> What is memory?\nMemory is persistence.\n\n"
                "> Why does it matter?\nIt enables continuity.\n\n"
            )

        palace_path = os.path.join(tmpdir, "palace")
        mine_convos(tmpdir, palace_path, wing="test_convos")

        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")

        all_results = col.get(include=["metadatas"])
        assistant_meta = [
            m for m in all_results["metadatas"] if m.get("turn_role") == "assistant"
        ]
        assert len(assistant_meta) == 0, "No assistant-tagged drawers without the flag"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
