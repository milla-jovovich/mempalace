import tempfile
from pathlib import Path

import chromadb

from mempalace.convo_miner import mine_convos


def get_collection(palace_path: Path):
    client = chromadb.PersistentClient(path=str(palace_path))
    return client.get_collection("mempalace_drawers")


def test_convo_mining_refreshes_without_duplicates(capsys):
    tmpdir = Path(tempfile.mkdtemp())
    chat = tmpdir / "chat.txt"
    chat.write_text(
        "> What is memory?\nMemory is persistence.\n\n"
        "> Why does it matter?\nIt enables continuity.\n\n"
        "> How do we build it?\nWith structured storage.\n"
    )
    palace_path = tmpdir / "palace"

    mine_convos(str(tmpdir), str(palace_path), wing="test_convos")
    col = get_collection(palace_path)
    first_count = col.count()

    mine_convos(str(tmpdir), str(palace_path), wing="test_convos")
    output = capsys.readouterr().out

    assert first_count >= 2
    assert col.count() == first_count
    assert "Files unchanged: 1" in output


def test_same_convo_file_can_be_mined_in_exchange_and_general_modes():
    tmpdir = Path(tempfile.mkdtemp())
    chat = tmpdir / "chat.txt"
    chat.write_text(
        "> We should use Clerk because Auth0 is expensive.\n"
        "Agreed. Let's switch to Clerk.\n\n"
        "> The deploy bug is fixed now.\n"
        "Yes, the root cause was the token refresh path.\n\n"
        "> I prefer functional tests for auth flows.\n"
        "That preference makes sense.\n"
    )
    palace_path = tmpdir / "palace"

    mine_convos(str(tmpdir), str(palace_path), wing="test_convos", extract_mode="exchange")
    col = get_collection(palace_path)
    exchange_count = col.count()

    mine_convos(str(tmpdir), str(palace_path), wing="test_convos", extract_mode="general")
    results = col.get(where={"source_file": str(chat.resolve())}, include=["metadatas"])

    assert col.count() > exchange_count
    assert {meta["extract_mode"] for meta in results["metadatas"]} == {"exchange", "general"}
