"""Tests for mempalace.layers — 4-Layer Memory Stack."""

import json

import pytest

from mempalace.layers import Layer0, Layer1, Layer2, Layer3, MemoryStack


class TestLayer0:
    def test_reads_identity_file(self, identity_file):
        layer = Layer0(identity_path=identity_file)
        text = layer.render()
        assert "Atlas" in text
        assert "Alice" in text

    def test_missing_file_returns_default(self, tmp_path):
        layer = Layer0(identity_path=str(tmp_path / "missing.txt"))
        text = layer.render()
        assert "No identity configured" in text

    def test_token_estimate(self, identity_file):
        layer = Layer0(identity_path=identity_file)
        tokens = layer.token_estimate()
        assert tokens > 0

    def test_caches_result(self, identity_file):
        layer = Layer0(identity_path=identity_file)
        t1 = layer.render()
        t2 = layer.render()
        assert t1 == t2


class TestLayer1:
    @pytest.mark.integration
    def test_generates_essential_story(self, palace_with_data):
        layer = Layer1(palace_path=palace_with_data)
        text = layer.generate()
        assert "L1" in text
        assert "ESSENTIAL STORY" in text

    @pytest.mark.integration
    def test_wing_filter(self, palace_with_data):
        layer = Layer1(palace_path=palace_with_data, wing="personal")
        text = layer.generate()
        assert "L1" in text

    def test_no_palace(self, tmp_path):
        layer = Layer1(palace_path=str(tmp_path / "nope"))
        text = layer.generate()
        assert "No palace found" in text

    @pytest.mark.integration
    def test_respects_max_chars(self, palace_with_data):
        layer = Layer1(palace_path=palace_with_data)
        text = layer.generate()
        assert len(text) <= Layer1.MAX_CHARS + 500  # some slack for headers


class TestLayer2:
    @pytest.mark.integration
    def test_retrieve(self, palace_with_data):
        layer = Layer2(palace_path=palace_with_data)
        text = layer.retrieve()
        assert "L2" in text
        assert "ON-DEMAND" in text

    @pytest.mark.integration
    def test_wing_filter(self, palace_with_data):
        layer = Layer2(palace_path=palace_with_data)
        text = layer.retrieve(wing="myapp")
        assert "L2" in text

    def test_no_palace(self, tmp_path):
        layer = Layer2(palace_path=str(tmp_path / "nope"))
        text = layer.retrieve()
        assert "No palace found" in text


class TestLayer3:
    @pytest.mark.integration
    def test_search(self, palace_with_data):
        layer = Layer3(palace_path=palace_with_data)
        text = layer.search("GraphQL")
        assert "L3" in text
        assert "SEARCH RESULTS" in text

    @pytest.mark.integration
    def test_search_raw(self, palace_with_data):
        layer = Layer3(palace_path=palace_with_data)
        hits = layer.search_raw("chess")
        assert len(hits) > 0
        assert "text" in hits[0]
        assert "similarity" in hits[0]
        assert "metadata" in hits[0]

    def test_no_palace(self, tmp_path):
        layer = Layer3(palace_path=str(tmp_path / "nope"))
        text = layer.search("test")
        assert "No palace found" in text

    def test_search_raw_no_palace(self, tmp_path):
        layer = Layer3(palace_path=str(tmp_path / "nope"))
        assert layer.search_raw("test") == []


class TestMemoryStack:
    @pytest.mark.integration
    def test_wake_up(self, palace_with_data, identity_file):
        stack = MemoryStack(palace_path=palace_with_data, identity_path=identity_file)
        text = stack.wake_up()
        assert "Atlas" in text
        assert "L1" in text

    @pytest.mark.integration
    def test_wake_up_with_wing(self, palace_with_data, identity_file):
        stack = MemoryStack(palace_path=palace_with_data, identity_path=identity_file)
        text = stack.wake_up(wing="personal")
        assert "Atlas" in text

    @pytest.mark.integration
    def test_recall(self, palace_with_data):
        stack = MemoryStack(palace_path=palace_with_data)
        text = stack.recall(wing="myapp")
        assert "L2" in text

    @pytest.mark.integration
    def test_search(self, palace_with_data):
        stack = MemoryStack(palace_path=palace_with_data)
        text = stack.search("GraphQL")
        assert "L3" in text

    @pytest.mark.integration
    def test_status(self, palace_with_data, identity_file):
        stack = MemoryStack(palace_path=palace_with_data, identity_path=identity_file)
        s = stack.status()
        assert s["total_drawers"] == 5
        assert s["L0_identity"]["exists"] is True
        assert s["palace_path"] == palace_with_data
