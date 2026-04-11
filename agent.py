#!/usr/bin/env python3
"""
agent.py — MemPalace OpenAI-Compatible Agent Proxy

A proxy server that:
  1. Accepts OpenAI-compatible API requests
  2. Enhances system prompts with MemPalace memory context
  3. Forwards to a backend LLM (OpenAI-compatible)
  4. Optionally stores conversation to MemPalace

Usage:
  AGENT_BASE_URL="http://0.0.0.0:8889/v1" LLM_BASE_URL="http://192.168.0.100:8000/v1" \\
    python agent.py --data=/path/to/user/data

Environment:
  LLM_BASE_URL    Backend LLM endpoint (default: http://localhost:8000/v1)
  LLM_API_KEY     Backend LLM API key (default: local)
  LLM_MODEL       Backend LLM model name (default: local)
  AGENT_BASE_URL  Agent bind URL (default: http://0.0.0.0:8001/v1)
  AGENT_HOST      Agent bind host (default: 0.0.0.0)
  AGENT_PORT      Agent bind port (default: 8001)

Connect your client to the AGENT_BASE_URL.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from openai import AsyncOpenAI

from mempalace.config import MempalaceConfig, sanitize_name
from mempalace.layers import MemoryStack
from mempalace.palace import get_collection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mempalace_agent")

# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BackendConfig:
    url: str = "http://localhost:8000/v1"
    api_key: str = "local"
    model: str = "local"

    @classmethod
    def from_env(cls) -> "BackendConfig":
        return cls(
            url=os.environ.get("LLM_BASE_URL", cls.url),
            api_key=os.environ.get("LLM_API_KEY", cls.api_key),
            model=os.environ.get("LLM_MODEL", cls.model),
        )


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8001

    @classmethod
    def from_env(cls) -> "ServerConfig":
        base_url = os.environ.get("AGENT_BASE_URL", "")
        if base_url:
            parsed = urlparse(base_url)
            return cls(
                host=parsed.hostname or cls.host,
                port=parsed.port or cls.port,
            )
        return cls(
            host=os.environ.get("AGENT_HOST", cls.host),
            port=int(os.environ.get("AGENT_PORT", cls.port)),
        )


# ---------------------------------------------------------------------------
# Conversation storage
# ---------------------------------------------------------------------------


class ConversationStore:
    """Persists conversation exchanges to a MemPalace ChromaDB collection."""

    COLLECTION = "mempalace_drawers"

    def __init__(self, palace_path: str) -> None:
        self._palace_path = palace_path

    def _drawer_id(self, wing: str, room: str, content_preview: str) -> str:
        digest = hashlib.sha256((wing + room + content_preview[:100]).encode()).hexdigest()[:24]
        return f"drawer_{wing}_{room}_{digest}"

    def save(
        self,
        user_message: str,
        assistant_message: str,
        model: str,
        wing: str = "conversations",
        room: str = "general",
    ) -> None:
        content = f"User: {user_message}\n\nAssistant ({model}): {assistant_message}"
        wing_clean = sanitize_name(wing, "wing")
        room_clean = sanitize_name(room, "room")
        drawer_id = self._drawer_id(wing_clean, room_clean, content)

        collection = get_collection(self._palace_path, self.COLLECTION)

        try:
            existing = collection.get(ids=[drawer_id])
            if existing and existing["ids"]:
                return  # idempotent
        except Exception:
            pass

        collection.add(
            ids=[drawer_id],
            documents=[content],
            metadatas=[
                {
                    "wing": wing_clean,
                    "room": room_clean,
                    "source_file": "agent_conversation",
                    "chunk_index": 0,
                    "added_by": "mempalace_agent",
                    "filed_at": datetime.now().isoformat(),
                    "type": "conversation",
                }
            ],
        )
        logger.debug("Stored conversation %s → %s/%s", drawer_id, wing_clean, room_clean)

    def save_async_fire_and_forget(self, *args, **kwargs) -> None:
        """Schedule a non-blocking save without blocking the event loop."""
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, lambda: self._safe_save(*args, **kwargs))

    def _safe_save(self, *args, **kwargs) -> None:
        try:
            self.save(*args, **kwargs)
        except Exception as exc:
            logger.warning("Failed to store conversation: %s", exc)


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------


class MessageEnhancer:
    """Injects MemPalace context into an OpenAI message list."""

    _MEMORY_HEADER = "# MemPalace Memory Context"
    _MEMORY_PREAMBLE = (
        "The following is your memory palace context. Use it to answer questions accurately."
    )
    _MEMORY_FOOTER = "# End MemPalace Context"
    _INSTRUCTIONS_HEADER = "# Your Original Instructions"
    _SEARCH_HEADER = "## Relevant Memories"

    def __init__(self, wake_up_context: str) -> None:
        self._wake_up_context = wake_up_context

    def _build_system_content(self, existing: Optional[str]) -> str:
        parts = [
            self._MEMORY_HEADER,
            self._MEMORY_PREAMBLE,
            "",
            self._wake_up_context,
            "",
            self._MEMORY_FOOTER,
            "",
        ]
        if existing:
            parts += [self._INSTRUCTIONS_HEADER, existing]
        return "\n".join(parts)

    def with_wake_up(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return a new message list with an enhanced system prompt prepended."""
        existing_system: Optional[str] = None
        rest: List[Dict[str, Any]] = []

        for msg in messages:
            if msg.get("role") == "system":
                existing_system = msg.get("content", "")
            else:
                rest.append(msg)

        return [
            {"role": "system", "content": self._build_system_content(existing_system)},
            *rest,
        ]

    def with_search_results(
        self, messages: List[Dict[str, Any]], results: str
    ) -> List[Dict[str, Any]]:
        """Inject L3 search results into the existing system prompt (or prepend one)."""
        search_block = f"{self._SEARCH_HEADER}\n{results}"
        messages = list(messages)  # shallow copy — don't mutate caller's list

        for i, msg in enumerate(messages):
            if msg.get("role") == "system":
                messages[i] = {
                    **msg,
                    "content": f"{msg['content']}\n\n{search_block}",
                }
                return messages

        return [{"role": "system", "content": search_block}, *messages]


# ---------------------------------------------------------------------------
# Response serialisation helpers (pure functions)
# ---------------------------------------------------------------------------


def _serialise_response(response) -> Dict[str, Any]:
    usage = None
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    return {
        "id": response.id,
        "object": response.object,
        "created": response.created,
        "model": response.model,
        "choices": [
            {
                "index": c.index,
                "message": {"role": c.message.role, "content": c.message.content},
                "finish_reason": c.finish_reason,
            }
            for c in response.choices
        ],
        "usage": usage,
    }


def _serialise_chunk(chunk) -> Dict[str, Any]:
    return {
        "id": chunk.id,
        "object": chunk.object,
        "created": chunk.created,
        "model": chunk.model,
        "choices": [
            {
                "index": c.index,
                "delta": {
                    "role": c.delta.role or None,
                    "content": c.delta.content or None,
                },
                "finish_reason": c.finish_reason,
            }
            for c in chunk.choices
        ],
    }


def _last_user_message(messages: List[Dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

_FORWARD_PARAMS = frozenset(
    {
        "temperature",
        "max_tokens",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "stop",
    }
)


class MemPalaceAgent:
    """
    MemPalace Agent Proxy — adds memory to any OpenAI-compatible API.

    Responsibilities:
      - Load and surface MemPalace memory context (L0 + L1 wake-up, L3 search)
      - Delegate message enhancement to MessageEnhancer
      - Delegate persistence to ConversationStore
      - Forward requests to the backend LLM via AsyncOpenAI
    """

    def __init__(
        self,
        data_path: str,
        backend: BackendConfig,
        auto_store: bool = True,
        wake_up_wing: Optional[str] = None,
    ) -> None:
        self._data_path = Path(data_path).expanduser().resolve()
        self._backend = backend
        self._auto_store = auto_store

        palace_path = str(self._data_path / ".mempalace" / "palace")
        os.makedirs(palace_path, exist_ok=True)
        os.environ["MEMPALACE_PALACE_PATH"] = palace_path

        self._stack = MemoryStack(palace_path=palace_path)
        self._store = ConversationStore(palace_path)

        wake_up_context = self._stack.wake_up(wing=wake_up_wing)
        logger.info("Loaded wake-up context (~%d tokens)", len(wake_up_context) // 4)

        self._enhancer = MessageEnhancer(wake_up_context)

        self._client = AsyncOpenAI(
            base_url=backend.url.rstrip("/"),
            api_key=backend.api_key,
            timeout=300.0,
        )

        logger.info(
            "MemPalaceAgent ready | data=%s | backend=%s | model=%s",
            self._data_path,
            backend.url,
            backend.model,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat_completions(
        self, request_data: Dict[str, Any]
    ) -> Union[Dict[str, Any], AsyncGenerator[str, None]]:
        messages: List[Dict[str, Any]] = request_data.get("messages") or []
        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")

        messages = self._maybe_inject_search(messages)
        enhanced = self._enhancer.with_wake_up(messages)

        kwargs: Dict[str, Any] = {
            "model": self._backend.model,
            "messages": enhanced,
            "stream": request_data.get("stream", False),
            **{k: request_data[k] for k in _FORWARD_PARAMS if k in request_data},
        }

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            logger.error("Backend error: %s", exc)
            raise HTTPException(status_code=502, detail=f"Backend error: {exc}") from exc

        if kwargs["stream"]:
            return self._stream_and_store(response, messages)

        result = _serialise_response(response)
        if self._auto_store:
            content = response.choices[0].message.content or "" if response.choices else ""
            self._store.save_async_fire_and_forget(
                user_message=_last_user_message(messages),
                assistant_message=content,
                model=self._backend.model,
            )
        return result

    async def list_models(self) -> Dict[str, Any]:
        try:
            response = await self._client.models.list()
            return {
                "object": "list",
                "data": [
                    {
                        "id": m.id,
                        "object": "model",
                        "created": getattr(m, "created", 0),
                        "owned_by": getattr(m, "owned_by", "unknown"),
                    }
                    for m in response.data
                ],
            }
        except Exception:
            return {
                "object": "list",
                "data": [
                    {
                        "id": self._backend.model,
                        "object": "model",
                        "created": 0,
                        "owned_by": "mempalace-agent",
                    }
                ],
            }

    def search_memory(self, query: str, wing=None, room=None, n_results: int = 5) -> str:
        return self._stack.search(query, wing=wing, room=room, n_results=n_results)

    def memory_status(self) -> Dict[str, Any]:
        return self._stack.status()

    async def close(self) -> None:
        await self._client.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _maybe_inject_search(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        query = _last_user_message(messages)
        if not query:
            return messages
        results = self._stack.search(query, n_results=3)
        if results and "No results" not in results:
            return self._enhancer.with_search_results(messages, results)
        return messages

    async def _stream_and_store(
        self, stream, original_messages: List[Dict[str, Any]]
    ) -> AsyncGenerator[str, None]:
        buffer: List[str] = []

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                buffer.append(chunk.choices[0].delta.content)
            yield f"data: {json.dumps(_serialise_chunk(chunk))}\n\n"

        yield "data: [DONE]\n\n"

        if buffer and self._auto_store:
            self._store.save_async_fire_and_forget(
                user_message=_last_user_message(original_messages),
                assistant_message="".join(buffer),
                model=self._backend.model,
            )


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------


def create_app(agent: MemPalaceAgent) -> FastAPI:

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await agent.close()

    app = FastAPI(
        title="MemPalace Agent Proxy",
        description="OpenAI-compatible proxy with MemPalace memory enhancement",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.get("/v1/models")
    async def list_models():
        return await agent.list_models()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        try:
            data = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        result = await agent.chat_completions(data)
        if data.get("stream", False):
            return StreamingResponse(result, media_type="text/event-stream")
        return JSONResponse(content=result)

    @app.get("/v1/health")
    async def health():
        return {
            "status": "healthy",
            "agent": "mempalace",
            "backend": agent._backend.url,
            "model": agent._backend.model,
        }

    @app.post("/v1/memory/search")
    async def memory_search(request: Request):
        try:
            data = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")
        results = agent.search_memory(
            query=data.get("query", ""),
            wing=data.get("wing"),
            room=data.get("room"),
            n_results=data.get("n_results", 5),
        )
        return {"results": results}

    @app.get("/v1/memory/status")
    async def memory_status():
        return agent.memory_status()

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MemPalace Agent Proxy — OpenAI-compatible API with memory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables (Backend LLM):
  LLM_BASE_URL    Backend LLM endpoint (default: http://localhost:8000/v1)
  LLM_API_KEY     Backend LLM API key (default: local)
  LLM_MODEL       Backend LLM model name (default: local)

Environment Variables (Agent Binding):
  AGENT_BASE_URL  Full URL like http://0.0.0.0:8889/v1 (parsed for host:port)
  AGENT_HOST      Agent bind host (default: 0.0.0.0)
  AGENT_PORT      Agent bind port (default: 8001)

Priority: AGENT_BASE_URL > AGENT_HOST/AGENT_PORT > --host/--port args
        """,
    )
    parser.add_argument(
        "--data",
        required=True,
        help="Path to user data directory (palace will be stored here)",
    )
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument(
        "--no-auto-store", action="store_true", help="Disable automatic conversation storage"
    )
    parser.add_argument("--wing", default=None, help="Specific wing to load for wake-up context")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    backend = BackendConfig.from_env()
    server = ServerConfig.from_env()

    # CLI args override environment
    if args.host:
        server.host = args.host
    if args.port:
        server.port = args.port

    data_path = Path(args.data).expanduser().resolve()
    data_path.mkdir(parents=True, exist_ok=True)
    (data_path / ".mempalace" / "palace").mkdir(parents=True, exist_ok=True)

    config = MempalaceConfig(config_dir=str(data_path / ".mempalace"))
    config.init()

    logger.info("=" * 60)
    logger.info("MemPalace Agent Proxy Starting")
    logger.info("  data    : %s", data_path)
    logger.info("  backend : %s  (model: %s)", backend.url, backend.model)
    logger.info("  endpoint: http://%s:%d/v1", server.host, server.port)
    logger.info("=" * 60)

    agent = MemPalaceAgent(
        data_path=str(data_path),
        backend=backend,
        auto_store=not args.no_auto_store,
        wake_up_wing=args.wing,
    )
    app = create_app(agent)
    uvicorn.run(app, host=server.host, port=server.port, log_level="info")


if __name__ == "__main__":
    main()
