from unittest.mock import MagicMock
import pytest
from mempalace.walker.extractor.gliner_ner import GlinerNER, Entity, ENTITY_TYPES
from mempalace.walker.gpu_detect import HardwareTier, WalkerHardware


def _fake_ner(fake_predict):
    ner = GlinerNER.__new__(GlinerNER)
    ner._model = MagicMock()
    ner._model.batch_predict_entities.side_effect = fake_predict
    ner._device = "cpu"
    return ner


def test_entity_dataclass():
    e = Entity("Alice", "person", 0.92)
    assert e.text == "Alice" and e.type == "person"


def test_entity_types_contains_core():
    for t in ("person", "organization", "location", "date"):
        assert t in ENTITY_TYPES


@pytest.mark.parametrize("tier,expected", [
    (HardwareTier.FULL, "cuda"),
    (HardwareTier.REDUCED, "cuda"),
    (HardwareTier.CPU_ONLY, "cpu"),
])
def test_select_device_for_tier(monkeypatch, tier, expected):
    fake = WalkerHardware(tier=tier, device_name="x", vram_gb=0.0)
    monkeypatch.setattr(
        "mempalace.walker.extractor.gliner_ner.detect_hardware", lambda: fake
    )
    assert GlinerNER._select_device() == expected


def test_select_device_fallback_on_error(monkeypatch):
    def boom(): raise RuntimeError("no cuda")
    monkeypatch.setattr(
        "mempalace.walker.extractor.gliner_ner.detect_hardware", boom
    )
    assert GlinerNER._select_device() == "cpu"


def test_extract_batch_maps_entities():
    fake_predict = lambda texts, labels, threshold: [
        [{"text": "Alice", "label": "person", "score": 0.9}],
        [{"text": "DeepMind", "label": "organization", "score": 0.85}],
    ]
    ner = _fake_ner(fake_predict)
    out = ner.extract_batch(["a", "b"])
    assert len(out) == 2
    assert out[0][0].text == "Alice"
    assert out[1][0].type == "organization"


def test_extract_batch_empty_input():
    ner = _fake_ner(lambda *a, **k: [])
    assert ner.extract_batch([]) == []
    ner._model.batch_predict_entities.assert_not_called()


def test_extract_batch_passes_threshold():
    ner = _fake_ner(lambda texts, labels, threshold: [[]])
    ner.extract_batch(["t"], threshold=0.6)
    ner._model.batch_predict_entities.assert_called_with(
        ["t"], ENTITY_TYPES, threshold=0.6
    )
