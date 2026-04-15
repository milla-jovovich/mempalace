"""Tests for GPU detection and hardware tier selection."""

from unittest.mock import MagicMock, patch

import pytest

from mempalace.walker.gpu_detect import HardwareTier, WalkerHardware, detect_hardware


def test_full_tier_on_large_vram():
    """≥20 GB VRAM → FULL tier."""
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = True
    mock_torch.cuda.device_count.return_value = 1
    mock_torch.cuda.get_device_name.return_value = "NVIDIA RTX A5000"
    mock_torch.cuda.get_device_properties.return_value = MagicMock(total_memory=24 * 1024**3)

    with patch.dict("sys.modules", {"torch": mock_torch}):
        hw = detect_hardware()

    assert hw.tier == HardwareTier.FULL
    assert hw.device_name == "NVIDIA RTX A5000"
    assert hw.vram_gb == pytest.approx(24.0, abs=0.5)


def test_reduced_tier_on_medium_vram():
    """8–20 GB VRAM → REDUCED tier."""
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = True
    mock_torch.cuda.device_count.return_value = 1
    mock_torch.cuda.get_device_name.return_value = "NVIDIA RTX 3080"
    mock_torch.cuda.get_device_properties.return_value = MagicMock(total_memory=10 * 1024**3)

    with patch.dict("sys.modules", {"torch": mock_torch}):
        hw = detect_hardware()

    assert hw.tier == HardwareTier.REDUCED
    assert hw.device_name == "NVIDIA RTX 3080"


def test_cpu_only_when_no_cuda():
    """No CUDA → CPU_ONLY tier."""
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = False

    with patch.dict("sys.modules", {"torch": mock_torch}):
        hw = detect_hardware()

    assert hw.tier == HardwareTier.CPU_ONLY
    assert hw.device_name is None
    assert hw.vram_gb is None


def test_cpu_only_when_torch_not_installed():
    """If torch is not installed → CPU_ONLY (graceful fallback)."""
    import sys
    original = sys.modules.get("torch")
    sys.modules["torch"] = None  # simulate ImportError via sys.modules
    try:
        hw = detect_hardware()
    finally:
        if original is None:
            sys.modules.pop("torch", None)
        else:
            sys.modules["torch"] = original

    assert hw.tier == HardwareTier.CPU_ONLY


def test_walker_hardware_dataclass():
    """WalkerHardware is a proper dataclass with the right fields."""
    hw = WalkerHardware(tier=HardwareTier.FULL, device_name="A5000", vram_gb=24.0)
    assert hw.tier == HardwareTier.FULL
    assert hw.device_name == "A5000"
    assert hw.vram_gb == 24.0
