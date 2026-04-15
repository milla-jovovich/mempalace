"""GPU detection and hardware tier selection for the walker subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HardwareTier(str, Enum):
    """Walker hardware tier based on available GPU VRAM."""

    FULL = "full"  # ≥20 GB — runs Qwen 2.5-7B AWQ + GLiNER
    REDUCED = "reduced"  # 8–20 GB — runs smaller walker model
    CPU_ONLY = "cpu_only"  # No CUDA or <8 GB — walker disabled


@dataclass
class WalkerHardware:
    """Detected hardware configuration for the walker subsystem."""

    tier: HardwareTier
    device_name: str | None  # e.g. "NVIDIA RTX A5000"; None for CPU_ONLY
    vram_gb: float | None  # Total VRAM in GiB; None for CPU_ONLY


_FULL_VRAM_GIB = 20.0
_REDUCED_VRAM_GIB = 8.0


def detect_hardware() -> WalkerHardware:
    """Detect available GPU hardware and return the appropriate walker tier.

    Returns CPU_ONLY if:
    - torch is not installed
    - CUDA is not available
    - VRAM < 8 GB
    """
    try:
        import torch  # type: ignore[import-not-found]

        if torch is None:
            raise ImportError("torch sentinel")
    except (ImportError, TypeError):
        return WalkerHardware(tier=HardwareTier.CPU_ONLY, device_name=None, vram_gb=None)

    if not torch.cuda.is_available() or torch.cuda.device_count() == 0:
        return WalkerHardware(tier=HardwareTier.CPU_ONLY, device_name=None, vram_gb=None)

    device_name: str = torch.cuda.get_device_name(0)
    props = torch.cuda.get_device_properties(0)
    vram_bytes: int = props.total_memory
    vram_gib = vram_bytes / (1024**3)

    if vram_gib >= _FULL_VRAM_GIB:
        tier = HardwareTier.FULL
    elif vram_gib >= _REDUCED_VRAM_GIB:
        tier = HardwareTier.REDUCED
    else:
        return WalkerHardware(tier=HardwareTier.CPU_ONLY, device_name=device_name, vram_gb=vram_gib)

    return WalkerHardware(tier=tier, device_name=device_name, vram_gb=vram_gib)
