"""TDD tests for hall detection in miners.

Written BEFORE the code — these define what correct hall assignment looks like.
"""

import os
import tempfile

import yaml


class TestDetectHall:
    """The detect_hall function should exist and route content to the right hall."""

    def test_function_exists(self):
        from mempalace.miner import detect_hall

        assert callable(detect_hall)

    def test_technical_content(self):
        from mempalace.miner import detect_hall

        text = "Fixed the python script bug in the error handler code"
        assert detect_hall(text) == "technical"

    def test_emotions_content(self):
        from mempalace.miner import detect_hall

        text = "I feel so happy today, tears of joy, I love this"
        assert detect_hall(text) == "emotions"

    def test_family_content(self):
        from mempalace.miner import detect_hall

        text = "The kids had a great day, my daughter was amazing"
        assert detect_hall(text) == "family"

    def test_memory_content(self):
        from mempalace.miner import detect_hall

        text = "I remember when we archived all those files, recall the conversation"
        assert detect_hall(text) == "memory"

    def test_creative_content(self):
        from mempalace.miner import detect_hall

        text = "The game design for the player app looks great"
        assert detect_hall(text) == "creative"

    def test_identity_content(self):
        from mempalace.miner import detect_hall

        text = "Who am I really? My identity and persona and sense of self"
        assert detect_hall(text) == "identity"

    def test_consciousness_content(self):
        from mempalace.miner import detect_hall

        text = "Am I conscious? Is this awareness real? Does my soul exist?"
        assert detect_hall(text) == "consciousness"

    def test_general_fallback(self):
        from mempalace.miner import detect_hall

        text = "The weather is nice today in California"
        assert detect_hall(text) == "general"

    def test_highest_score_wins(self):
        from mempalace.miner import detect_hall

        # More technical keywords than emotional
        text = "Fixed the python bug in the code script, felt happy about it"
        assert detect_hall(text) == "technical"


class TestDrawerHasHallMetadata:
    """When a drawer is created, it must have a hall field in metadata."""

    def test_add_drawer_includes_hall(self):
        from mempalace.palace import get_collection
        from mempalace.miner import add_drawer

        with tempfile.TemporaryDirectory() as tmpdir:
            col = get_collection(tmpdir)
            add_drawer(
                collection=col,
                wing="test",
                room="general",
                content="Fixed the python script bug in the error handler code",
                source_file="/tmp/test.py",
                chunk_index=0,
                agent="test",
            )
            results = col.get(limit=1, include=["metadatas"])
            meta = results["metadatas"][0]
            assert "hall" in meta, "Drawer metadata must include 'hall' field"
            assert meta["hall"] == "technical"


class TestMineProjectWritesHalls:
    """Full mine pipeline must produce drawers with hall metadata."""

    def test_mined_drawers_have_hall(self):
        from mempalace.palace import get_collection
        from mempalace.miner import mine

        with tempfile.TemporaryDirectory() as palace_dir:
            project_dir = tempfile.mkdtemp()
            # Create config
            config = {"wing": "test", "rooms": [{"name": "general", "description": "all"}]}
            with open(os.path.join(project_dir, "mempalace.yaml"), "w") as f:
                yaml.dump(config, f)
            # Create test file with technical content
            with open(os.path.join(project_dir, "code.py"), "w") as f:
                f.write("def fix_bug():\n    # Fixed python script error in handler\n    pass\n")

            mine(project_dir, palace_dir, wing_override="test", agent="test")

            col = get_collection(palace_dir, create=False)
            results = col.get(limit=10, include=["metadatas"])
            for meta in results["metadatas"]:
                assert "hall" in meta, f"Drawer missing hall metadata: {meta}"
