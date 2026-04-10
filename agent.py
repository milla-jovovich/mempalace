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

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, AsyncGenerator
from contextlib import asynccontextmanager

# FastAPI imports
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

# HTTP client for backend
import httpx

# MemPalace imports
from mempalace.layers import MemoryStack
from mempalace.config import MempalaceConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("mempalace_agent")


class MemPalaceAgent:
    """
    MemPalace Agent Proxy — adds memory to any OpenAI-compatible API.

    The agent:
      - Loads L0 (identity) + L1 (essential story) on startup
      - Injects memory context into system prompts
      - Forwards requests to backend LLM
      - Can store conversations back to the palace
    """

    def __init__(
        self,
        data_path: str,
        backend_url: str,
        backend_key: str,
        backend_model: str,
        auto_store: bool = True,
        wake_up_wing: Optional[str] = None,
    ):
        self.data_path = Path(data_path).expanduser().resolve()
        self.backend_url = backend_url.rstrip("/")
        self.backend_key = backend_key
        self.backend_model = backend_model
        self.auto_store = auto_store
        self.wake_up_wing = wake_up_wing

        # Initialize palace at the data path
        self.palace_path = str(self.data_path / ".mempalace" / "palace")
        os.makedirs(self.palace_path, exist_ok=True)

        # Override env var for this process
        os.environ["MEMPALACE_PALACE_PATH"] = self.palace_path

        # Initialize memory stack
        self.stack = MemoryStack(palace_path=self.palace_path)

        # Load wake-up context once
        self.wake_up_context = self.stack.wake_up(wing=wake_up_wing)
        logger.info(f"Loaded wake-up context (~{len(self.wake_up_context) // 4} tokens)")

        # HTTP client for backend
        self.client = httpx.AsyncClient(
            base_url=self.backend_url,
            headers={"Authorization": f"Bearer {self.backend_key}"},
            timeout=300.0,
        )

        logger.info(f"MemPalace Agent initialized")
        logger.info(f"  Data path: {self.data_path}")
        logger.info(f"  Palace path: {self.palace_path}")
        logger.info(f"  Backend: {self.backend_url}")
        logger.info(f"  Model: {self.backend_model}")

    def _build_system_prompt(self, existing_system: Optional[str] = None) -> str:
        """Build enhanced system prompt with MemPalace context."""
        parts = []

        # Add MemPalace wake-up context first
        parts.append("# MemPalace Memory Context")
        parts.append(
            "The following is your memory palace context. Use it to answer questions accurately."
        )
        parts.append("")
        parts.append(self.wake_up_context)
        parts.append("")
        parts.append("# End MemPalace Context")
        parts.append("")

        # Add existing system prompt if provided
        if existing_system:
            parts.append("# Your Original Instructions")
            parts.append(existing_system)

        return "\n".join(parts)

    def _enhance_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Enhance message list with MemPalace context in system prompt."""
        enhanced = []
        existing_system = None

        for msg in messages:
            if msg.get("role") == "system":
                existing_system = msg.get("content", "")
            else:
                enhanced.append(msg)

        # Build enhanced system prompt with memory
        system_prompt = self._build_system_prompt(existing_system)

        # Insert system prompt at the beginning
        enhanced.insert(0, {"role": "system", "content": system_prompt})

        return enhanced

    async def chat_completions(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle chat completions request with memory enhancement."""
        # Extract messages
        messages = request_data.get("messages", [])
        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")

        # Check if this is a search query we should augment
        last_message = messages[-1] if messages else {}
        if last_message.get("role") == "user":
            user_query = last_message.get("content", "")
            # Perform L3 search for relevant context
            search_results = self.stack.search(user_query, n_results=3)
            if search_results and "No results" not in search_results:
                # Inject search results into system context
                messages = self._inject_search_context(messages, search_results)

        # Enhance with MemPalace wake-up context
        enhanced_messages = self._enhance_messages(messages)

        # Prepare backend request
        backend_request = {
            **request_data,
            "messages": enhanced_messages,
            "model": self.backend_model,
        }

        # Remove fields that shouldn't be forwarded
        for key in ["user", "session_id"]:
            backend_request.pop(key, None)

        # Forward to backend
        try:
            response = await self.client.post(
                "/chat/completions",
                json=backend_request,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Backend error: {e}")
            raise HTTPException(status_code=502, detail=f"Backend error: {e}")

    def _inject_search_context(
        self, messages: List[Dict[str, str]], search_results: str
    ) -> List[Dict[str, str]]:
        """Inject L3 search results into the conversation context."""
        # Find system message or create one
        has_system = False
        for msg in messages:
            if msg.get("role") == "system":
                has_system = True
                original = msg.get("content", "")
                msg["content"] = (
                    f"{original}\n\n## Relevant Memories (from search)\n{search_results}"
                )
                break

        if not has_system:
            # Insert at beginning
            messages.insert(
                0, {"role": "system", "content": f"## Relevant Memories\n{search_results}"}
            )

        return messages

    async def chat_completions_stream(
        self, request_data: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """Handle streaming chat completions."""
        messages = request_data.get("messages", [])
        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")

        # Check if this is a search query
        last_message = messages[-1] if messages else {}
        if last_message.get("role") == "user":
            user_query = last_message.get("content", "")
            search_results = self.stack.search(user_query, n_results=3)
            if search_results and "No results" not in search_results:
                messages = self._inject_search_context(messages, search_results)

        enhanced_messages = self._enhance_messages(messages)

        backend_request = {
            **request_data,
            "messages": enhanced_messages,
            "model": self.backend_model,
            "stream": True,
        }

        for key in ["user", "session_id"]:
            backend_request.pop(key, None)

        try:
            async with self.client.stream(
                "POST",
                "/chat/completions",
                json=backend_request,
                headers={"Content-Type": "application/json"},
                timeout=300.0,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        yield line + "\n"
        except httpx.HTTPError as e:
            logger.error(f"Backend streaming error: {e}")
            error_data = json.dumps({"error": {"message": str(e)}})
            yield f"data: {error_data}\n\n"

    async def models(self) -> Dict[str, Any]:
        """Return available models (proxied from backend)."""
        try:
            response = await self.client.get("/models")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            # Return a default model if backend doesn't support /models
            return {
                "object": "list",
                "data": [
                    {
                        "id": self.backend_model,
                        "object": "model",
                        "created": 0,
                        "owned_by": "mempalace-agent",
                    }
                ],
            }

    async def close(self):
        """Cleanup resources."""
        await self.client.aclose()


# FastAPI app
def create_app(agent: MemPalaceAgent) -> FastAPI:
    """Create FastAPI application with the agent."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Lifespan context manager for startup/shutdown."""
        # Startup
        yield
        # Shutdown
        await agent.close()

    app = FastAPI(
        title="MemPalace Agent Proxy",
        description="OpenAI-compatible proxy with MemPalace memory enhancement",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.get("/v1/models")
    async def list_models():
        """List available models."""
        return await agent.models()

    @app.get("/models")
    async def list_models_compat():
        """List models (compat endpoint)."""
        return await agent.models()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        """Chat completions endpoint."""
        try:
            request_data = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        is_streaming = request_data.get("stream", False)

        if is_streaming:
            return StreamingResponse(
                agent.chat_completions_stream(request_data),
                media_type="text/event-stream",
            )
        else:
            result = await agent.chat_completions(request_data)
            return JSONResponse(content=result)

    @app.post("/chat/completions")
    async def chat_completions_compat(request: Request):
        """Chat completions (compat endpoint)."""
        return await chat_completions(request)

    @app.get("/v1/health")
    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "agent": "mempalace",
            "backend": agent.backend_url,
            "model": agent.backend_model,
        }

    @app.post("/v1/memory/search")
    @app.post("/memory/search")
    async def memory_search(request: Request):
        """Direct memory search endpoint."""
        try:
            data = await request.json()
            query = data.get("query", "")
            wing = data.get("wing")
            room = data.get("room")
            n_results = data.get("n_results", 5)

            results = agent.stack.search(query, wing=wing, room=room, n_results=n_results)
            return {"results": results}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/v1/memory/status")
    @app.get("/memory/status")
    async def memory_status():
        """Get memory stack status."""
        return agent.stack.status()

    return app


def main():
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

Example:
  AGENT_BASE_URL="http://0.0.0.0:8889/v1" LLM_BASE_URL="http://192.168.0.100:8000/v1" \\
    uv run python agent.py --data=/home/user/data
        """,
    )
    parser.add_argument(
        "--data", required=True, help="Path to user data directory (where palace will be stored)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to run agent on (default: 8001, or from AGENT_BASE_URL)",
    )
    parser.add_argument(
        "--host", default=None, help="Host to bind to (default: 0.0.0.0, or from AGENT_BASE_URL)"
    )
    parser.add_argument(
        "--no-auto-store", action="store_true", help="Disable automatic conversation storage"
    )
    parser.add_argument("--wing", default=None, help="Specific wing to load for wake-up context")

    args = parser.parse_args()

    # Get agent binding config from environment (AGENT_BASE_URL takes priority)
    agent_base_url = os.environ.get("AGENT_BASE_URL", "")
    if agent_base_url:
        # Parse host:port from AGENT_BASE_URL (e.g., "http://0.0.0.0:8889/v1")
        try:
            from urllib.parse import urlparse

            parsed = urlparse(agent_base_url)
            env_host = parsed.hostname or "0.0.0.0"
            env_port = parsed.port or 8001
        except Exception:
            env_host = "0.0.0.0"
            env_port = 8001
    else:
        env_host = os.environ.get("AGENT_HOST", "0.0.0.0")
        env_port = int(os.environ.get("AGENT_PORT", "8001"))

    # CLI args override environment
    host = args.host if args.host else env_host
    port = args.port if args.port else env_port

    # Get backend config from environment
    backend_url = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1")
    backend_key = os.environ.get("LLM_API_KEY", "local")
    backend_model = os.environ.get("LLM_MODEL", "local")

    # Ensure data directory exists
    data_path = Path(args.data).expanduser().resolve()
    data_path.mkdir(parents=True, exist_ok=True)

    # Initialize palace if needed
    palace_path = data_path / ".mempalace" / "palace"
    palace_path.mkdir(parents=True, exist_ok=True)

    # Initialize MemPalace config
    config = MempalaceConfig(config_dir=str(data_path / ".mempalace"))
    config.init()

    logger.info("=" * 60)
    logger.info("MemPalace Agent Proxy Starting")
    logger.info("=" * 60)
    logger.info(f"Data directory: {data_path}")
    logger.info(f"Palace path: {palace_path}")
    logger.info(f"Backend LLM: {backend_url}")
    logger.info(f"Backend model: {backend_model}")
    logger.info(f"Agent endpoint: http://{host}:{port}/v1")
    logger.info("=" * 60)

    # Create agent
    agent = MemPalaceAgent(
        data_path=str(data_path),
        backend_url=backend_url,
        backend_key=backend_key,
        backend_model=backend_model,
        auto_store=not args.no_auto_store,
        wake_up_wing=args.wing,
    )

    # Create FastAPI app
    app = create_app(agent)

    # Run server
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
