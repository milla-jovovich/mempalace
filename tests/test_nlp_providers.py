"""Tests for mempalace.nlp_providers — providers, registry, negation, model manager."""

from mempalace.nlp_providers.legacy_provider import LegacyProvider
from mempalace.nlp_providers.negation import NEGATION_CUES, is_negated, score_with_negation
from mempalace.nlp_providers.registry import NLPProviderRegistry, get_registry


# ── LegacyProvider ──────────────────────────────────────────────────


class TestLegacyProvider:
    def setup_method(self):
        self.provider = LegacyProvider()

    def test_is_available(self):
        """LegacyProvider should always be available."""
        assert self.provider.is_available() is True

    def test_name(self):
        assert self.provider.name == "legacy"

    def test_capabilities(self):
        caps = self.provider.capabilities
        assert "ner" in caps
        assert "sentences" in caps
        assert "classify" in caps
        assert "sentiment" in caps

    def test_extract_entities_returns_list(self):
        """extract_entities should return a list of dicts."""
        # Use text with capitalized words appearing 3+ times (extract_candidates threshold)
        text = "Alice said hello. Alice went home. Alice likes tea. Bob knows Alice."
        result = self.provider.extract_entities(text)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)
            assert "text" in item
            assert "label" in item

    def test_split_sentences(self):
        """split_sentences should split on punctuation."""
        text = "Hello world. How are you? Fine thanks!"
        result = self.provider.split_sentences(text)
        assert isinstance(result, list)
        assert len(result) >= 3

    def test_extract_triples_empty(self):
        """Legacy has no triple extraction."""
        assert self.provider.extract_triples("any text") == []

    def test_resolve_coreferences_empty(self):
        """Legacy has no coref."""
        assert self.provider.resolve_coreferences("any text") == []

    def test_analyze_sentiment(self):
        """analyze_sentiment should return a string."""
        result = self.provider.analyze_sentiment("I love this!")
        assert result in ("positive", "negative", "neutral")

    def test_classify_text(self):
        """classify_text should return dict or None."""
        # Use text with clear decision markers
        text = "We decided to go with Python because it's simpler and better for our team."
        result = self.provider.classify_text(text, ["decision", "preference"])
        # May return None if text is too short for extract_memories
        assert result is None or isinstance(result, dict)


# ── NLPProviderRegistry ────────────────────────────────────────────


class TestRegistry:
    def test_register_and_load(self):
        """Registry should register and lazily load providers."""
        registry = NLPProviderRegistry()
        registry.register("legacy", lambda: LegacyProvider())
        provider = registry._load_provider("legacy")
        assert provider is not None
        assert provider.name == "legacy"

    def test_register_factory_function(self):
        """Registry should accept factory functions."""
        registry = NLPProviderRegistry()
        registry.register("legacy", lambda: LegacyProvider())
        provider = registry._load_provider("legacy")
        assert provider is not None

    def test_get_for_capability(self):
        """get_for_capability should return legacy for known capabilities."""
        registry = NLPProviderRegistry()
        registry.register("legacy", lambda: LegacyProvider())
        provider = registry.get_for_capability("ner")
        assert provider is not None
        assert provider.name == "legacy"

    def test_get_for_capability_unknown(self):
        """Unknown capability should return None."""
        registry = NLPProviderRegistry()
        provider = registry.get_for_capability("teleportation")
        assert provider is None

    def test_fallback_chain(self):
        """When higher-priority providers fail, should fall back."""
        registry = NLPProviderRegistry()
        # Register a failing provider and a working one
        registry.register("spacy", lambda: (_ for _ in ()).throw(ImportError("no spacy")))
        registry.register("legacy", lambda: LegacyProvider())
        # Should fall back to legacy for NER
        provider = registry.get_for_capability("ner")
        assert provider is not None
        assert provider.name == "legacy"

    def test_convenience_split_sentences(self):
        """Registry convenience method should work."""
        registry = NLPProviderRegistry()
        registry.register("legacy", lambda: LegacyProvider())
        result = registry.split_sentences("Hello. World.")
        assert isinstance(result, list)
        assert len(result) >= 2

    def test_convenience_extract_entities(self):
        """Registry convenience method for entities should work."""
        registry = NLPProviderRegistry()
        registry.register("legacy", lambda: LegacyProvider())
        result = registry.extract_entities("some text")
        assert isinstance(result, list)

    def test_convenience_extract_triples(self):
        """Registry convenience method for triples returns empty (no triple provider)."""
        registry = NLPProviderRegistry()
        registry.register("legacy", lambda: LegacyProvider())
        result = registry.extract_triples("some text")
        assert result == []

    def test_convenience_classify_text(self):
        """Registry convenience classify_text returns None when no classifier."""
        registry = NLPProviderRegistry()
        result = registry.classify_text("some text", ["a", "b"])
        assert result is None

    def test_split_sentences_no_providers(self):
        """split_sentences should use regex fallback when no providers registered."""
        registry = NLPProviderRegistry()
        result = registry.split_sentences("Hello world. How are you?")
        assert isinstance(result, list)
        assert len(result) >= 2

    def test_load_provider_failure(self):
        """_load_provider should return None and not retry on failure."""
        registry = NLPProviderRegistry()
        registry.register("bad", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        result = registry._load_provider("bad")
        assert result is None
        # Second call should also return None (don't retry)
        result2 = registry._load_provider("bad")
        assert result2 is None

    def test_load_provider_unknown(self):
        """_load_provider should return None for unknown name."""
        registry = NLPProviderRegistry()
        assert registry._load_provider("doesnt_exist") is None

    def test_load_provider_already_loaded(self):
        """_load_provider should return cached instance on second call."""
        registry = NLPProviderRegistry()
        registry.register("legacy", lambda: LegacyProvider())
        p1 = registry._load_provider("legacy")
        p2 = registry._load_provider("legacy")
        assert p1 is p2


# ── NLPProvider Protocol ──────────────────────────────────────────────


class TestProtocol:
    def test_legacy_is_nlp_provider(self):
        """LegacyProvider should be a runtime instance of NLPProvider Protocol."""
        from mempalace.nlp_providers.base import NLPProvider

        provider = LegacyProvider()
        assert isinstance(provider, NLPProvider)


# ── get_registry singleton ──────────────────────────────────────────


def test_get_registry_returns_instance():
    """get_registry should return an NLPProviderRegistry."""
    # Reset the global to force fresh creation
    import mempalace.nlp_providers.registry as reg_mod

    old = reg_mod._registry
    reg_mod._registry = None
    try:
        registry = get_registry()
        assert isinstance(registry, NLPProviderRegistry)
    finally:
        reg_mod._registry = old


# ── Negation detection ──────────────────────────────────────────────


class TestNegation:
    def test_basic_not(self):
        """'not happy' should be negated."""
        text = "I am not happy about this"
        pos = text.index("happy")
        assert is_negated(text, pos) is True

    def test_contraction_dont(self):
        """\"don't like\" should be negated."""
        text = "I don't like this approach"
        pos = text.index("like")
        assert is_negated(text, pos) is True

    def test_contraction_cant(self):
        """\"can't work\" should be negated."""
        text = "This can't work properly"
        pos = text.index("work")
        assert is_negated(text, pos) is True

    def test_no_negation(self):
        """Positive statement should not be negated."""
        text = "I really love this feature"
        pos = text.index("love")
        assert is_negated(text, pos) is False

    def test_never(self):
        """'never' should trigger negation."""
        text = "We should never use this pattern"
        pos = text.index("use")
        assert is_negated(text, pos) is True

    def test_window_limit(self):
        """Negation outside window should not trigger."""
        text = "not a single one of these things is happy"
        pos = text.index("happy")
        # "not" is far away, outside default window of 5
        result = is_negated(text, pos, window=3)
        assert result is False

    def test_negation_cues_list(self):
        """NEGATION_CUES should contain expected entries."""
        assert "not" in NEGATION_CUES
        assert "never" in NEGATION_CUES
        assert "don't" in NEGATION_CUES
        assert "can't" in NEGATION_CUES

    def test_score_with_negation_reduces(self):
        """score_with_negation should reduce score for negated matches."""
        text = "I am not happy but on the other hand I feel quite excited about it"
        markers = [r"\bhappy\b", r"\bexcited\b"]
        score, keywords = score_with_negation(text, markers)
        # "not happy" is negated (-0.5), "excited" is far from negation (+1.0)
        assert score == 0.5
        assert "excited" in keywords

    def test_score_with_negation_no_negation(self):
        """Without negation all matches should count positively."""
        text = "I am happy and excited"
        markers = [r"\bhappy\b", r"\bexcited\b"]
        score, keywords = score_with_negation(text, markers)
        assert score == 2.0


# ── ModelManager ────────────────────────────────────────────────────


class TestModelManager:
    def setup_method(self):
        from mempalace.nlp_providers.model_manager import ModelManager

        ModelManager._reset()

    def teardown_method(self):
        from mempalace.nlp_providers.model_manager import ModelManager

        ModelManager._reset()

    def test_singleton(self):
        """ModelManager.get() should return the same instance."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm1 = ModelManager.get()
        mm2 = ModelManager.get()
        assert mm1 is mm2

    def test_get_status_not_installed(self):
        """Models requiring unavailable packages should be NOT_INSTALLED."""
        from mempalace.nlp_providers.model_manager import ModelManager, ModelStatus

        mm = ModelManager.get()
        # spacy is likely not installed in test env
        status = mm.get_status("spacy-xx-ent-wiki-sm")
        assert status in (ModelStatus.NOT_INSTALLED, ModelStatus.NOT_DOWNLOADED)

    def test_get_status_unknown_model(self):
        """Unknown model ID should return NOT_INSTALLED."""
        from mempalace.nlp_providers.model_manager import ModelManager, ModelStatus

        mm = ModelManager.get()
        status = mm.get_status("nonexistent-model")
        assert status == ModelStatus.NOT_INSTALLED

    def test_check_disk_space(self):
        """_check_disk_space should return a boolean."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager.get()
        result = mm._check_disk_space(100)
        assert isinstance(result, bool)

    def test_get_all_status(self):
        """get_all_status should return status for all catalog models."""
        from mempalace.nlp_providers.model_manager import MODEL_CATALOG, ModelManager

        mm = ModelManager.get()
        all_status = mm.get_all_status()
        assert len(all_status) == len(MODEL_CATALOG)
        for model_id in MODEL_CATALOG:
            assert model_id in all_status
            assert "status" in all_status[model_id]
            assert "spec" in all_status[model_id]

    def test_remove_model_not_found(self):
        """Removing a non-existent model should return False."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager.get()
        assert mm.remove_model("nonexistent-model") is False

    def test_remove_model_exists(self, tmp_path):
        """Removing an existing model dir should return True."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        (tmp_path / "test-model").mkdir()
        (tmp_path / "test-model" / "model.onnx").write_text("fake")
        assert mm.remove_model("test-model") is True
        assert not (tmp_path / "test-model").exists()

    def test_model_path(self, tmp_path):
        """_model_path should join model_dir and model_id."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        assert mm._model_path("foo") == tmp_path / "foo"

    def test_get_free_space_mb(self, tmp_path):
        """_get_free_space_mb should return a positive number."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        free = mm._get_free_space_mb()
        assert free > 0

    def test_get_local_size_empty(self, tmp_path):
        """_get_local_size for non-existent model returns 0."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        assert mm._get_local_size("nonexistent") == 0

    def test_get_local_size_with_files(self, tmp_path):
        """_get_local_size returns total size in MB."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        model_dir = tmp_path / "test-model"
        model_dir.mkdir()
        (model_dir / "data.bin").write_bytes(b"x" * 2048)
        size = mm._get_local_size("test-model")
        assert isinstance(size, int)
        assert size >= 0  # small file rounds to 0 MB

    def test_get_status_downloading(self, tmp_path):
        """Model with .downloading lock file should be DOWNLOADING."""
        from mempalace.nlp_providers.model_manager import ModelManager, ModelStatus

        mm = ModelManager(model_dir=str(tmp_path))
        model_dir = tmp_path / "spacy-xx-ent-wiki-sm"
        model_dir.mkdir()
        (model_dir / ".downloading").write_text("pid=12345")
        # Monkeypatch the import check to pass
        import mempalace.nlp_providers.model_manager as mm_mod

        orig_catalog = mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"]
        mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"] = mm_mod.ModelSpec(
            id="spacy-xx-ent-wiki-sm",
            display_name="test",
            phase=1,
            size_mb=15,
            required_packages=[],  # no packages required for this test
            description="test",
        )
        try:
            status = mm.get_status("spacy-xx-ent-wiki-sm")
            assert status == ModelStatus.DOWNLOADING
        finally:
            mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"] = orig_catalog

    def test_get_status_ready(self, tmp_path):
        """Model with dir but no lock should be READY (when packages available)."""
        from mempalace.nlp_providers.model_manager import ModelManager, ModelStatus

        mm = ModelManager(model_dir=str(tmp_path))
        model_dir = tmp_path / "spacy-xx-ent-wiki-sm"
        model_dir.mkdir()
        import mempalace.nlp_providers.model_manager as mm_mod

        orig_catalog = mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"]
        mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"] = mm_mod.ModelSpec(
            id="spacy-xx-ent-wiki-sm",
            display_name="test",
            phase=1,
            size_mb=15,
            required_packages=[],
            description="test",
        )
        try:
            status = mm.get_status("spacy-xx-ent-wiki-sm")
            assert status == ModelStatus.READY
        finally:
            mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"] = orig_catalog

    def test_ensure_model_unknown(self, tmp_path):
        """ensure_model with unknown model_id returns None."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        assert mm.ensure_model("totally-unknown") is None

    def test_ensure_model_ready(self, tmp_path):
        """ensure_model returns path when model is already ready."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        model_dir = tmp_path / "spacy-xx-ent-wiki-sm"
        model_dir.mkdir()
        import mempalace.nlp_providers.model_manager as mm_mod

        orig = mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"]
        mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"] = mm_mod.ModelSpec(
            id="spacy-xx-ent-wiki-sm",
            display_name="test",
            phase=1,
            size_mb=15,
            required_packages=[],
            description="test",
        )
        try:
            path = mm.ensure_model("spacy-xx-ent-wiki-sm")
            assert path == model_dir
        finally:
            mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"] = orig

    def test_ensure_model_not_installed(self, tmp_path):
        """ensure_model returns None when packages missing."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        # spacy package likely not installed
        assert mm.ensure_model("spacy-xx-ent-wiki-sm") is None

    def test_ensure_model_not_downloaded_no_auto(self, tmp_path, monkeypatch):
        """ensure_model returns None when not downloaded and auto-download disabled."""
        from mempalace.nlp_providers.model_manager import ModelManager

        monkeypatch.delenv("MEMPALACE_AUTO_DOWNLOAD", raising=False)
        mm = ModelManager(model_dir=str(tmp_path))
        import mempalace.nlp_providers.model_manager as mm_mod

        orig = mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"]
        mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"] = mm_mod.ModelSpec(
            id="spacy-xx-ent-wiki-sm",
            display_name="test",
            phase=1,
            size_mb=15,
            required_packages=[],
            description="test",
        )
        try:
            assert mm.ensure_model("spacy-xx-ent-wiki-sm") is None
        finally:
            mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"] = orig

    def test_install_for_backend_spacy(self, tmp_path):
        """install_for_backend('spacy') should attempt phase ≤1 models."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        results = mm.install_for_backend("spacy", prompt_user=False)
        # Should include phase 1 models (spacy, coreferee)
        assert "spacy-xx-ent-wiki-sm" in results
        assert "coreferee-en" in results
        # Should not include phase 2+
        assert "gliner2-onnx" not in results

    def test_install_for_backend_pysbd(self, tmp_path):
        """install_for_backend('pysbd') for phase 0 has no models to install."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        results = mm.install_for_backend("pysbd", prompt_user=False)
        assert len(results) == 0  # phase 0 has no model downloads

    def test_download_creates_lock_file(self, tmp_path):
        """_download should create and clean up lock file."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        import mempalace.nlp_providers.model_manager as mm_mod

        orig = mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"]
        mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"] = mm_mod.ModelSpec(
            id="spacy-xx-ent-wiki-sm",
            display_name="test",
            phase=1,
            size_mb=1,
            required_packages=[],
            description="test",
        )
        try:
            mm._download("spacy-xx-ent-wiki-sm")
            # Download returns None (placeholder impl) but lock file should be cleaned
            lock_file = tmp_path / "spacy-xx-ent-wiki-sm" / ".downloading"
            assert not lock_file.exists()
        finally:
            mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"] = orig

    def test_download_low_disk_space(self, tmp_path, monkeypatch):
        """_download should fail gracefully on low disk space."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        monkeypatch.setattr(mm, "_check_disk_space", lambda mb: False)
        import mempalace.nlp_providers.model_manager as mm_mod

        orig = mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"]
        mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"] = mm_mod.ModelSpec(
            id="spacy-xx-ent-wiki-sm",
            display_name="test",
            phase=1,
            size_mb=1,
            required_packages=[],
            description="test",
        )
        try:
            result = mm._download("spacy-xx-ent-wiki-sm")
            assert result is None
        finally:
            mm_mod.MODEL_CATALOG["spacy-xx-ent-wiki-sm"] = orig

    def test_print_install_hint(self, tmp_path, capsys):
        """_print_install_hint should print package names."""
        from mempalace.nlp_providers.model_manager import ModelManager, ModelSpec

        mm = ModelManager(model_dir=str(tmp_path))
        spec = ModelSpec(
            id="test",
            display_name="Test Model",
            phase=1,
            size_mb=10,
            required_packages=["spacy"],
        )
        mm._print_install_hint(spec)
        captured = capsys.readouterr()
        assert "spacy" in captured.out
        assert "pip install" in captured.out

    def test_remove_model_files(self, tmp_path):
        """_remove_model_files should delete model directory."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        model_dir = tmp_path / "test-model"
        model_dir.mkdir()
        (model_dir / "file.bin").write_text("data")
        mm._remove_model_files("test-model")
        assert not model_dir.exists()

    def test_is_auto_download_allowed(self, monkeypatch, tmp_path):
        """_is_auto_download_allowed should respect env var."""
        from mempalace.nlp_providers.model_manager import ModelManager

        mm = ModelManager(model_dir=str(tmp_path))
        monkeypatch.setenv("MEMPALACE_AUTO_DOWNLOAD", "1")
        assert mm._is_auto_download_allowed() is True
        monkeypatch.setenv("MEMPALACE_AUTO_DOWNLOAD", "0")
        assert mm._is_auto_download_allowed() is False
        monkeypatch.delenv("MEMPALACE_AUTO_DOWNLOAD")
        assert mm._is_auto_download_allowed() is False
