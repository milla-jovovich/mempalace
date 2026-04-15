"""Async HTTP client for Qwen3.5 35B relationship extraction.

Uses CircuitBreaker.call_async() from Phase 0+Task 1b.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from mempalace.infra.circuit_breaker import CircuitBreaker, CircuitOpenError
from mempalace.walker.extractor.gliner_ner import Entity

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Extract relationships as JSON triples from the text.\n"
    'Return ONLY a JSON array: [{"subject": "...", "predicate": "...", "object": "..."}]\n'
    "Use only entities from the provided list. Predicates must be snake_case verbs.\n"
    "Return [] if no clear relationships exist. No explanation, no markdown."
)

STRICTER_PROMPT = (
    'Return ONLY a JSON array of {"subject","predicate","object"} objects.\n'
    "No markdown, no explanation, no other text. Just the JSON array."
)


@dataclass(slots=True)
class Triple:
    subject: str
    predicate: str
    object: str


class QwenRelExtractor:
    def __init__(
        self,
        base_url: str = "http://localhost:43100",
        model: str = "qwen35",
        concurrency: int = 4,
        timeout_secs: float = 30.0,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._concurrency = concurrency
        self._timeout_secs = timeout_secs
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_secs)
        self._cb = CircuitBreaker("qwen_rel", failure_threshold=3, recovery_timeout_secs=30.0)
        self._preflight_check()

    def _preflight_check(self) -> None:
        try:
            with httpx.Client(base_url=self._base_url, timeout=5.0) as sync:
                r = sync.get("/v1/models")
                r.raise_for_status()
        except Exception as e:
            raise RuntimeError(
                f"Qwen endpoint {self._base_url} unreachable: {e}. "
                f"Start the Qwen server before running walker extract."
            ) from e

    async def aclose(self) -> None:
        await self._client.aclose()

    async def extract(self, text: str, entities: list[Entity]) -> list[Triple]:
        if not entities or not text or not text.strip():
            return []

        entity_lines = "\n".join(f"- {e.text} ({e.type})" for e in entities)
        user_content = f"Text:\n{text}\n\nEntities:\n{entity_lines}"

        content = await self._http_call(SYSTEM_PROMPT, user_content)
        if content is None:
            return []

        triples = _parse_triples(content)
        if triples is not None:
            return triples

        # Parse failures do NOT count as HTTP failures — breaker stays closed.
        content = await self._http_call(STRICTER_PROMPT, user_content)
        if content is None:
            return []

        return _parse_triples(content) or []

    async def _http_call(self, system: str, user: str) -> str | None:
        try:
            return await self._cb.call_async(lambda: self._do_post(system, user))
        except CircuitOpenError:
            log.warning("Qwen circuit OPEN — skipping call")
            return None
        except Exception as e:
            log.warning("Qwen HTTP call failed: %s", e)
            return None

    async def _do_post(self, system: str, user: str) -> str:
        resp = await self._client.post(
            "/v1/chat/completions",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.0,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _parse_triples(content: str) -> list[Triple] | None:
    """Parse JSON triples from Qwen response. Returns None if unparseable."""
    if content is None:
        return None

    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```\s*$", "", stripped)
        stripped = stripped.strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = _extract_first_json_array(stripped)
        if data is None:
            return None

    if not isinstance(data, list):
        return None

    triples: list[Triple] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        s, p, o = item.get("subject"), item.get("predicate"), item.get("object")
        if isinstance(s, str) and isinstance(p, str) and isinstance(o, str):
            triples.append(Triple(s, p, o))
    return triples


def _extract_first_json_array(text: str):
    """Find the first balanced JSON array honoring string quoting."""
    start = text.find("[")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None
