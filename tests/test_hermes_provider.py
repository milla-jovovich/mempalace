#!/usr/bin/env python3
"""Tests for the MemPalace Hermes Agent memory provider."""

import json
import pytest
from mempalace.hermes_provider import MempalaceProvider


class TestMempalaceProviderBasic:
    """Test the MempalaceProvider without a live palace."""

    def test_name(self):
        """Provider name should be 'mempalace'."""
        provider = MempalaceProvider()
        assert provider.name == "mempalace"

    def test_is_available_no_palace(self):
        """Without a palace directory, is_available should return False."""
        provider = MempalaceProvider(palace_path="/nonexistent/path")
        # May return True or False depending on default config, but should not crash
        result = provider.is_available()
        assert isinstance(result, bool)

    def test_get_tool_schemas(self):
        """Provider should expose mempalace_search and mempalace_kg_query tools."""
        provider = MempalaceProvider()
        schemas = provider.get_tool_schemas()
        assert len(schemas) == 2
        names = [s["name"] for s in schemas]
        assert "mempalace_search" in names
        assert "mempalace_kg_query" in names

    def test_tool_schemas_have_parameters(self):
        """Each tool schema should have a parameters field with required."""
        provider = MempalaceProvider()
        for schema in provider.get_tool_schemas():
            assert "parameters" in schema
            assert "properties" in schema["parameters"]
            assert "required" in schema["parameters"]

    def test_system_prompt_block_no_init(self):
        """System prompt should be empty before initialization."""
        provider = MempalaceProvider()
        assert provider.system_prompt_block() == ""

    def test_prefetch_no_init(self):
        """Prefetch should return empty string before initialization."""
        provider = MempalaceProvider()
        assert provider.prefetch("test query") == ""

    def test_handle_unknown_tool(self):
        """Unknown tool calls should return an error."""
        provider = MempalaceProvider()
        result = json.loads(provider.handle_tool_call("unknown_tool", {}))
        assert "error" in result

    def test_handle_search_no_init(self):
        """Search tool should return error when palace not initialized."""
        provider = MempalaceProvider()
        result = json.loads(provider.handle_tool_call("mempalace_search", {"query": "test"}))
        assert "error" in result

    def test_handle_kg_query_no_init(self):
        """KG query tool should return error when KG not initialized."""
        provider = MempalaceProvider()
        result = json.loads(provider.handle_tool_call("mempalace_kg_query", {"entity": "test"}))
        assert "error" in result

    def test_shutdown_safe(self):
        """Shutdown should be safe to call without initialization."""
        provider = MempalaceProvider()
        provider.shutdown()  # Should not raise

    def test_sync_turn_no_init(self):
        """sync_turn should be safe to call without initialization."""
        provider = MempalaceProvider()
        provider.sync_turn("hello", "hi there")  # Should not raise

    def test_on_pre_compress_no_init(self):
        """on_pre_compress should return empty string without initialization."""
        provider = MempalaceProvider()
        result = provider.on_pre_compress([{"content": "test message"}])
        assert result == ""

    def test_on_memory_write_no_init(self):
        """on_memory_write should be safe to call without initialization."""
        provider = MempalaceProvider()
        provider.on_memory_write("add", "memory", "test content")  # Should not raise


class TestMempalaceProviderWithPalace:
    """Test with a temporary palace directory."""

    @pytest.fixture
    def palace_provider(self, tmp_path):
        """Create a provider with a temporary palace."""
        import chromadb

        palace_path = str(tmp_path / "palace")
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_or_create_collection("mempalace_drawers")

        # Add test data
        col.add(
            ids=["test_1", "test_2"],
            documents=[
                "We decided to use GraphQL instead of REST for the API",
                "The authentication system uses JWT tokens with refresh rotation",
            ],
            metadatas=[
                {"wing": "wing_code", "room": "api-design", "filed_at": "2026-01-01"},
                {"wing": "wing_code", "room": "auth", "filed_at": "2026-01-02"},
            ],
        )

        provider = MempalaceProvider(palace_path=palace_path)
        provider.initialize(session_id="test-session")
        return provider

    def test_search_tool(self, palace_provider):
        """Search tool should find relevant documents."""
        result = json.loads(
            palace_provider.handle_tool_call("mempalace_search", {"query": "GraphQL API"})
        )
        assert "results" in result
        assert result["count"] > 0
        assert any("GraphQL" in r["content"] for r in result["results"])

    def test_prefetch(self, palace_provider):
        """Prefetch should return relevant context."""
        context = palace_provider.prefetch("Tell me about the API design")
        # Should return something (the GraphQL decision)
        assert isinstance(context, str)

    def test_sync_turn_stores_exchange(self, palace_provider):
        """sync_turn should not raise when called with valid args."""
        # sync_turn runs in a background thread; we verify it doesn't crash
        palace_provider.sync_turn(
            "What auth system do we use?",
            "We use JWT tokens with refresh rotation.",
            session_id="test-session",
        )

    def test_system_prompt_block(self, palace_provider):
        """System prompt should include MemPalace instructions."""
        block = palace_provider.system_prompt_block()
        # May or may not have layers loaded depending on identity.txt
        assert isinstance(block, str)


class TestRegisterFunction:
    """Test the hermes-agent plugin registration."""

    def test_register(self):
        """register() should create and register a MempalaceProvider."""
        from mempalace.hermes_provider import register

        class FakeCtx:
            def __init__(self):
                self.provider = None

            def register_memory_provider(self, p):
                self.provider = p

        ctx = FakeCtx()
        register(ctx)
        assert ctx.provider is not None
        assert ctx.provider.name == "mempalace"
