"""
slm_provider.py -- Small Language Model (Gemma 3 1B) provider via onnxruntime-genai.

Feature-gated: only active when MEMPALACE_NLP_SLM=1.
Model is lazily loaded on first use. Thread-safe model loading with lock.
"""

import json
import logging
import os
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Prompt templates for different tasks
# Prompt bodies (chat-template wrapping is applied at runtime based on model type)
SENTIMENT_BODY = (
    "Analyze the sentiment of the following text. "
    "Respond with exactly one word: positive, negative, or neutral.\n\n"
    "Text: {text}"
)

TRIPLES_BODY = (
    "Extract subject-predicate-object triples from the following text. "
    'Return ONLY a JSON array of objects with "subject", "predicate", "object" keys. '
    "No explanation.\n\n"
    "Text: {text}"
)

COREF_BODY = (
    "Resolve pronoun references in the following text. "
    'Return ONLY a JSON array of objects with "pronoun" and "referent" keys. '
    "No explanation.\n\n"
    "Text: {text}"
)


def _chat_wrap(user_msg: str, model_type: str = "phi3") -> str:
    """Wrap a user message in the appropriate chat template."""
    if "gemma" in model_type:
        return f"<start_of_turn>user\n{user_msg}<end_of_turn>\n<start_of_turn>model\n"
    # Phi-3 / Phi-3.5 chat template
    return f"<|user|>\n{user_msg}<|end|>\n<|assistant|>\n"


class SLMProvider:
    """NLP provider using Gemma 3 1B ONNX for nuanced NLP tasks."""

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._og = None
        self._load_lock = threading.Lock()
        self._loaded = False
        self._available = None
        self._model_type = "phi3"

    @staticmethod
    def _find_genai_dir(model_path):
        """Find the directory containing genai_config.json, searching subdirectories."""
        from pathlib import Path

        root = Path(model_path)
        if (root / "genai_config.json").exists():
            return root
        # Search for genai_config.json in subdirectories (e.g. cpu_and_mobile/...)
        for config in root.rglob("genai_config.json"):
            return config.parent
        return root

    @staticmethod
    def _detect_model_type(model_dir):
        """Detect the model type from genai_config.json."""
        from pathlib import Path

        config_path = Path(model_dir) / "genai_config.json"
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text())
                model_type = data.get("model", {}).get("type", "")
                if "gemma" in model_type:
                    return "gemma"
                if "phi" in model_type:
                    return "phi3"
                if "qwen" in model_type:
                    return "qwen"
            except Exception:
                pass
        return "phi3"

    @property
    def name(self) -> str:
        return "slm"

    @property
    def capabilities(self) -> set:
        return {"sentiment", "triples", "coref"}

    def _ensure_loaded(self):
        """Lazily load model and tokenizer on first use. Thread-safe."""
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            try:
                import onnxruntime_genai as og

                self._og = og

                from .model_manager import ModelManager

                mm = ModelManager.get()
                model_path = mm.ensure_model("gemma-3-1b-onnx")

                if model_path is None:
                    logger.debug("SLM model not available via ModelManager")
                    self._available = False
                else:
                    load_path = self._find_genai_dir(model_path)
                    self._model = og.Model(str(load_path))
                    self._tokenizer = og.Tokenizer(self._model)
                    self._model_type = self._detect_model_type(load_path)
                    self._available = True
            except ImportError:
                logger.debug("onnxruntime_genai not installed — SLMProvider unavailable")
                self._available = False
            except Exception as e:
                logger.warning(f"Failed to initialize SLM: {e}")
                self._available = False
            self._loaded = True

    def is_available(self) -> bool:
        """Check if onnxruntime_genai is importable and model is available."""
        env_slm = os.environ.get("MEMPALACE_NLP_SLM")
        feature_enabled = env_slm in ("1", "true", "yes", "on")

        if not feature_enabled:
            return False

        self._ensure_loaded()
        return self._available is True

    def generate(self, prompt: str, max_tokens: int = 256) -> str:
        """Generate text using the SLM.

        Args:
            prompt: The input prompt.
            max_tokens: Maximum tokens to generate.

        Returns:
            Generated text string, or empty string on failure.
        """
        if not self._available or self._model is None or self._tokenizer is None:
            return ""
        try:
            tokens = self._tokenizer.encode(prompt)
            params = self._og.GeneratorParams(self._model)
            params.set_search_options(
                max_length=len(tokens) + max_tokens,
                repetition_penalty=1.2,
            )

            generator = self._og.Generator(self._model, params)
            generator.append_tokens(tokens)

            output_tokens = []
            while not generator.is_done():
                generator.generate_next_token()
                new_token = generator.get_next_tokens()[0]
                output_tokens.append(new_token)
                if len(output_tokens) >= max_tokens:
                    break

            import numpy as np

            return self._tokenizer.decode(np.array(output_tokens))
        except Exception as e:
            logger.warning(f"SLM generation failed: {e}")
            return ""

    def _format_prompt(self, body: str, **kwargs) -> str:
        """Format a prompt body with chat template wrapping."""
        return _chat_wrap(body.format(**kwargs), self._model_type)

    def analyze_sentiment(self, text: str) -> str:
        """Analyze sentiment using prompted generation."""
        self._ensure_loaded()
        if not self._available:
            return "neutral"
        prompt = self._format_prompt(SENTIMENT_BODY, text=text)
        result = self.generate(prompt, max_tokens=10)
        result = result.strip().lower()
        if "positive" in result:
            return "positive"
        elif "negative" in result:
            return "negative"
        return "neutral"

    def extract_triples(self, text: str) -> List[Dict]:
        """Extract triples using prompted generation."""
        self._ensure_loaded()
        if not self._available:
            return []
        prompt = self._format_prompt(TRIPLES_BODY, text=text)
        result = self.generate(prompt, max_tokens=512)
        return self._parse_json_list(result, ["subject", "predicate", "object"])

    def resolve_coreferences(self, text: str) -> List[Dict]:
        """Resolve coreferences using prompted generation."""
        self._ensure_loaded()
        if not self._available:
            return []
        prompt = self._format_prompt(COREF_BODY, text=text)
        result = self.generate(prompt, max_tokens=256)
        return self._parse_json_list(result, ["pronoun", "referent"])

    def extract_entities(self, text: str) -> List[Dict]:
        """Not supported by SLM provider."""
        return []

    def split_sentences(self, text: str) -> List[str]:
        """Not supported by SLM provider."""
        return []

    def classify_text(self, text: str, labels: List[str]) -> Optional[Dict]:
        """Not supported by SLM provider."""
        return None

    @staticmethod
    def _parse_json_list(text: str, required_keys: list) -> List[Dict]:
        """Parse a JSON array from generated text, validating required keys."""
        try:
            # Find JSON array in the output
            start = text.find("[")
            end = text.rfind("]")
            if start == -1 or end == -1:
                return []
            data = json.loads(text[start : end + 1])
            if not isinstance(data, list):
                return []
            return [
                item
                for item in data
                if isinstance(item, dict) and all(k in item for k in required_keys)
            ]
        except (json.JSONDecodeError, ValueError):
            return []
