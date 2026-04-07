import chromadb
from mempalace.convo_miner import mine_convos, chunk_exchanges, detect_convo_room


def test_convo_mining(tmp_dir, palace_path):
    chat = tmp_dir / "chat.txt"
    chat.write_text(
        "> What is memory?\nMemory is persistence.\n\n"
        "> Why does it matter?\nIt enables continuity.\n\n"
        "> How do we build it?\nWith structured storage.\n"
    )

    mine_convos(str(tmp_dir), palace_path, wing="test_convos")

    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")
    assert col.count() == 3  # 3 exchange pairs


def test_chunk_exchanges_with_markers():
    content = (
        "> Question one?\nAnswer one is here.\n\n"
        "> Question two?\nAnswer two is here.\n\n"
        "> Question three?\nAnswer three is here.\n"
    )
    chunks = chunk_exchanges(content)
    assert len(chunks) == 3
    assert "> Question one?" in chunks[0]["content"]
    assert "Answer one is here." in chunks[0]["content"]


def test_chunk_exchanges_falls_back_to_paragraphs():
    content = "First paragraph about something.\n\nSecond paragraph about another thing entirely.\n"
    chunks = chunk_exchanges(content)
    assert len(chunks) == 2


def test_detect_convo_room_technical():
    assert detect_convo_room("We found a bug in the python api server") == "technical"


def test_detect_convo_room_decisions():
    assert detect_convo_room("We decided to switch and migrated the approach") == "decisions"


def test_detect_convo_room_general():
    assert detect_convo_room("Hello how are you today") == "general"


def test_mine_convos_skips_already_filed(tmp_dir, palace_path):
    chat = tmp_dir / "chat.txt"
    chat.write_text("> First question?\nFirst answer.\n\n> Second question?\nSecond answer.\n")
    mine_convos(str(tmp_dir), palace_path, wing="test")
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")
    count_after_first = col.count()

    # Mine again — should skip
    mine_convos(str(tmp_dir), palace_path, wing="test")
    assert col.count() == count_after_first
