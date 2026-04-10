"""
kg_extraction.py — Hybrid NER + LLM Extraction for the Knowledge Graph
=======================================================================

Extracts entities and relationship triples from raw text using:
  1. spaCy NER (if installed) or regex fallback
  2. Claude Haiku LLM extraction (if ANTHROPIC_API_KEY available)
  3. Co-occurrence triples for entity pairs in the same sentence

Usage:
    from mempalace.knowledge_graph import KnowledgeGraph
    from mempalace.kg_extraction import EntityTripleExtractor

    kg = KnowledgeGraph()
    extractor = EntityTripleExtractor(kg)
    result = extractor.extract("Alice Chen works at Acme Corp.", source_closet="closet_abc")
    # {"entities_added": 2, "triples_added": 1, "details": [...]}
"""

import json
import os
import re
from datetime import date


class EntityTripleExtractor:
    """Extract entities and relationship triples from text, writing directly to a KnowledgeGraph."""

    # spaCy entity types we care about
    _SPACY_TYPES = {"PERSON", "ORG", "GPE", "EVENT"}

    def __init__(self, kg, use_llm: str = "auto"):
        """
        Args:
            kg: KnowledgeGraph instance to write extracted data to.
            use_llm: "auto" (use if ANTHROPIC_API_KEY set), "always", "never".
        """
        self.kg = kg
        self.use_llm = use_llm

    # ── Public API ────────────────────────────────────────────────────────

    def extract(self, text: str, source_closet: str = None) -> dict:
        """
        Extract entities and triples from text, write to KG.

        Returns:
            {"entities_added": int, "triples_added": int, "details": list}
        """
        entities, triples = self._extract_ner(text)

        if self._should_use_llm():
            llm_entities, llm_triples = self._extract_llm(text)
            # Merge: LLM entities override NER on same name (higher quality types)
            existing_names = {e["name"].lower() for e in entities}
            for e in llm_entities:
                if e["name"].lower() not in existing_names:
                    entities.append(e)
                    existing_names.add(e["name"].lower())
            triples.extend(llm_triples)

        # Add co-occurrence triples from all discovered entities
        triples.extend(self._build_cooccurrence_triples(entities, text))

        # Write entities
        entities_added = 0
        for entity in entities:
            self.kg.add_entity(entity["name"], entity.get("type", "unknown"))
            entities_added += 1

        # Write triples
        triples_added = 0
        details = []
        for triple in triples:
            triple_id = self.kg.add_triple(
                subject=triple["subject"],
                predicate=triple["predicate"],
                obj=triple["object"],
                valid_from=triple.get("valid_from"),
                confidence=triple.get("confidence", 1.0),
                source_closet=source_closet,
            )
            if triple_id:
                triples_added += 1
                details.append(
                    {
                        "triple_id": triple_id,
                        "subject": triple["subject"],
                        "predicate": triple["predicate"],
                        "object": triple["object"],
                        "confidence": triple.get("confidence", 1.0),
                    }
                )

        return {
            "entities_added": entities_added,
            "triples_added": triples_added,
            "details": details,
        }

    # ── Extraction backends ───────────────────────────────────────────────

    def _extract_ner(self, text: str) -> tuple:
        """
        Extract entities and triples via spaCy NER or regex fallback.

        Returns:
            (entities, triples) where entities=[{name, type}], triples=[{subject, predicate, object, confidence}]
        """
        if self._spacy_available():
            return self._extract_spacy(text)
        return self._extract_regex(text)

    def _extract_spacy(self, text: str) -> tuple:
        """Run spaCy NER and build co-occurrence triples."""
        try:
            import spacy  # noqa: PLC0415

            # Load small model; fall back to blank English if no model installed
            try:
                nlp = spacy.load("en_core_web_sm")
            except OSError:
                try:
                    nlp = spacy.load("en_core_web_md")
                except OSError:
                    return self._extract_regex(text)

            doc = nlp(text)
            entities = []
            seen = set()
            for ent in doc.ents:
                if ent.label_ in self._SPACY_TYPES and ent.text.lower() not in seen:
                    entities.append({"name": ent.text, "type": ent.label_.lower()})
                    seen.add(ent.text.lower())

            return entities, []
        except Exception:
            return self._extract_regex(text)

    def _extract_regex(self, text: str) -> tuple:
        """
        Regex fallback: detect capitalized multi-word names (e.g. "Alice Chen", "Acme Corp").
        Entity type is "unknown" for all regex-detected entities.
        """
        # Match 2+ consecutive capitalized words (Title Case), not at sentence start only
        pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
        entities = []
        seen = set()
        for match in pattern.finditer(text):
            name = match.group(1)
            if name.lower() not in seen:
                entities.append({"name": name, "type": "unknown"})
                seen.add(name.lower())
        return entities, []

    def _extract_llm(self, text: str) -> tuple:
        """
        Extract entities and triples via Claude Haiku.

        Returns:
            (entities, triples) or ([], []) on any failure.
        """
        try:
            import anthropic  # noqa: PLC0415

            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

            prompt = (
                "Extract named entities and factual relationships from the text below.\n"
                "Return a JSON object with two keys:\n"
                '  "entities": array of {name, type} — type is one of: person, org, place, event, concept\n'
                '  "triples": array of {subject, predicate, object, valid_from} '
                "— valid_from is ISO date string or null\n\n"
                "Return ONLY valid JSON, no explanation.\n\n"
                f"Text: {text[:4000]}"
            )

            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            raw = message.content[0].text.strip()
            # Strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            parsed = json.loads(raw)
            entities = [
                {"name": e.get("name", ""), "type": e.get("type", "unknown")}
                for e in parsed.get("entities", [])
                if e.get("name")
            ]
            triples = [
                {
                    "subject": t.get("subject", ""),
                    "predicate": t.get("predicate", ""),
                    "object": t.get("object", ""),
                    "valid_from": t.get("valid_from"),
                    "confidence": 1.0,
                }
                for t in parsed.get("triples", [])
                if t.get("subject") and t.get("predicate") and t.get("object")
            ]
            return entities, triples
        except Exception:
            return [], []

    # ── Co-occurrence triples ─────────────────────────────────────────────

    def _build_cooccurrence_triples(self, entities: list, text: str) -> list:
        """
        For each pair of entities appearing in the same sentence, emit a
        "mentioned_with" triple with confidence=0.6.
        """
        if len(entities) < 2:
            return []

        sentences = re.split(r"[.!?]+", text)
        triples = []

        for sentence in sentences:
            sentence_lower = sentence.lower()
            present = [e for e in entities if e["name"].lower() in sentence_lower]
            if len(present) < 2:
                continue
            # Emit pairs (each pair once, ordered by position in sentence)
            for i in range(len(present)):
                for j in range(i + 1, len(present)):
                    triples.append(
                        {
                            "subject": present[i]["name"],
                            "predicate": "mentioned_with",
                            "object": present[j]["name"],
                            "confidence": 0.6,
                            "valid_from": date.today().isoformat(),
                        }
                    )

        return triples

    # ── Availability checks ───────────────────────────────────────────────

    @staticmethod
    def _spacy_available() -> bool:
        """Return True if spaCy is importable."""
        try:
            import spacy  # noqa: F401, PLC0415

            return True
        except ImportError:
            return False

    @staticmethod
    def _llm_available() -> bool:
        """Return True if the anthropic package and API key are present."""
        try:
            import anthropic  # noqa: F401, PLC0415

            return bool(os.environ.get("ANTHROPIC_API_KEY"))
        except ImportError:
            return False

    # ── Internal helpers ──────────────────────────────────────────────────

    def _should_use_llm(self) -> bool:
        if self.use_llm == "never":
            return False
        if self.use_llm == "always":
            return self._llm_available()
        # "auto": only if API key is set
        return self._llm_available()
