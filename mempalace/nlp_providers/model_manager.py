"""
model_manager.py -- Download, verify, cache, and manage NLP models.

All model operations go through ModelManager. Providers call
ModelManager.ensure_model() and receive a local path, never
downloading anything themselves.
"""

import logging
import os
import shutil
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ModelStatus(Enum):
    NOT_INSTALLED = "not_installed"  # deps not installed
    NOT_DOWNLOADED = "not_downloaded"  # deps installed, model missing
    DOWNLOADING = "downloading"  # download in progress
    CORRUPTED = "corrupted"  # model files fail verification
    READY = "ready"  # model verified and ready


@dataclass
class ModelSpec:
    """Declares a downloadable model."""

    id: str  # unique key, e.g. "spacy-xx-ent-wiki-sm"
    display_name: str  # human-friendly, e.g. "spaCy xx_ent_wiki_sm"
    phase: int  # 1-4
    size_mb: int  # approximate download size
    required_packages: list  # pip packages that must be importable
    description: str = ""
    optional: bool = False  # True for Phase 4 (Gemma)
    hf_repo_id: str = ""  # HuggingFace repo for snapshot_download


# -- Model catalog --
MODEL_CATALOG: Dict[str, ModelSpec] = {
    "spacy-xx-ent-wiki-sm": ModelSpec(
        id="spacy-xx-ent-wiki-sm",
        display_name="spaCy xx_ent_wiki_sm",
        phase=1,
        size_mb=15,
        required_packages=["spacy"],
        description="Multilingual NER (PER, ORG, LOC, MISC)",
    ),
    "coreferee-en": ModelSpec(
        id="coreferee-en",
        display_name="coreferee English",
        phase=1,
        size_mb=2,
        required_packages=["coreferee", "spacy"],
        description="Coreference resolution for English",
    ),
    "gliner2-onnx": ModelSpec(
        id="gliner2-onnx",
        display_name="GLiNER2 ONNX",
        phase=2,
        size_mb=412,
        required_packages=["gliner"],
        description="Relation extraction, zero-shot NER, classification",
    ),
    "wtpsplit-sat3l-sm": ModelSpec(
        id="wtpsplit-sat3l-sm",
        display_name="wtpsplit sat-3l-sm",
        phase=3,
        size_mb=18,
        required_packages=["wtpsplit"],
        description="Sentence segmentation, 85 languages",
    ),
    "gemma-3-1b-onnx": ModelSpec(
        id="gemma-3-1b-onnx",
        display_name="Gemma 3 1B ONNX",
        phase=4,
        size_mb=1100,
        required_packages=["onnxruntime_genai"],
        description="Small language model for complex extraction",
        optional=True,
        hf_repo_id="MiCkSoftware/gemma-3-1b-it-abliterated-onnx-genai-int4-20260213-221858",
    ),
}


class ModelManager:
    """
    Singleton that owns all model lifecycle operations.
    Thread-safe. Used by providers and CLI commands.
    """

    _instance: Optional["ModelManager"] = None
    _lock = threading.Lock()

    def __init__(self, model_dir: Optional[str] = None):
        self.model_dir = Path(
            model_dir
            or os.environ.get("MEMPALACE_MODEL_DIR")
            or Path.home() / ".mempalace" / "models"
        )
        self._download_locks: Dict[str, threading.Lock] = {}
        self._status_cache: Dict[str, ModelStatus] = {}

    @classmethod
    def get(cls, model_dir: Optional[str] = None) -> "ModelManager":
        """Get or create the singleton ModelManager."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(model_dir)
        return cls._instance

    @classmethod
    def _reset(cls):
        """Reset singleton (for tests only)."""
        cls._instance = None

    # -- Core API --

    def ensure_model(self, model_id: str, prompt_user: bool = False) -> Optional[Path]:
        """
        Ensure a model is available. Returns the local path, or None if
        the model cannot be made available.

        When prompt_user=True (CLI/init context), asks before downloading.
        When prompt_user=False (provider context), returns None silently.
        """
        spec = MODEL_CATALOG.get(model_id)
        if spec is None:
            logger.error(f"Unknown model: {model_id}")
            return None

        status = self.get_status(model_id)

        if status == ModelStatus.READY:
            return self._model_path(model_id)

        if status == ModelStatus.NOT_INSTALLED:
            if prompt_user:
                self._print_install_hint(spec)
            return None

        if status == ModelStatus.CORRUPTED:
            logger.warning(f"Model {spec.display_name} is corrupted, re-downloading...")
            self._remove_model_files(model_id)

        if status in (ModelStatus.NOT_DOWNLOADED, ModelStatus.CORRUPTED):
            if not self._is_auto_download_allowed() and not prompt_user:
                return None
            return self._download(model_id)

        return None

    def get_status(self, model_id: str) -> ModelStatus:
        """Check current status of a model."""
        spec = MODEL_CATALOG.get(model_id)
        if spec is None:
            return ModelStatus.NOT_INSTALLED

        # Check if required packages are importable
        for pkg in spec.required_packages:
            try:
                __import__(pkg)
            except ImportError:
                return ModelStatus.NOT_INSTALLED

        # Check if model files exist
        model_path = self._model_path(model_id)
        if not model_path.exists():
            return ModelStatus.NOT_DOWNLOADED

        # Check if a download is in progress (lock file)
        lock_file = model_path / ".downloading"
        if lock_file.exists():
            return ModelStatus.DOWNLOADING

        return ModelStatus.READY

    def get_all_status(self) -> Dict[str, Dict]:
        """Get status of every model in the catalog. Used by CLI status command."""
        result = {}
        for model_id, spec in MODEL_CATALOG.items():
            status = self.get_status(model_id)
            local_size = self._get_local_size(model_id) if status == ModelStatus.READY else 0
            result[model_id] = {
                "spec": spec,
                "status": status,
                "local_size_mb": local_size,
            }
        return result

    def install_for_backend(self, backend: str, prompt_user: bool = True) -> Dict[str, bool]:
        """Download all models needed for a given backend level."""
        phase_map = {"pysbd": 0, "spacy": 1, "gliner": 2, "full": 3, "slm": 4}
        max_phase = phase_map.get(backend, 0)

        results = {}
        for model_id, spec in MODEL_CATALOG.items():
            if spec.phase <= max_phase and not spec.optional:
                path = self.ensure_model(model_id, prompt_user=prompt_user)
                results[model_id] = path is not None
            elif spec.optional and backend == "slm":
                path = self.ensure_model(model_id, prompt_user=prompt_user)
                results[model_id] = path is not None
        return results

    def remove_model(self, model_id: str) -> bool:
        """Remove a downloaded model to free disk space."""
        model_path = self._model_path(model_id)
        if model_path.exists():
            shutil.rmtree(model_path, ignore_errors=True)
            logger.info(f"Removed model: {model_id}")
            return True
        return False

    # -- Internal helpers --

    def _model_path(self, model_id: str) -> Path:
        """Return the local directory for a given model."""
        return self.model_dir / model_id

    def _is_auto_download_allowed(self) -> bool:
        """Check if auto-download is allowed via env var."""
        return os.environ.get("MEMPALACE_AUTO_DOWNLOAD") in ("1", "true", "yes", "on")

    def _check_disk_space(self, needed_mb: int) -> bool:
        """Check if enough disk space is available."""
        try:
            free_mb = self._get_free_space_mb()
            return free_mb > needed_mb * 1.5  # 50% margin
        except OSError:
            return True  # Optimistic if we can't check

    def _get_free_space_mb(self) -> float:
        """Get free disk space in MB for the model directory."""
        self.model_dir.mkdir(parents=True, exist_ok=True)
        stat = shutil.disk_usage(self.model_dir)
        return stat.free / (1024 * 1024)

    def _get_local_size(self, model_id: str) -> int:
        """Get local size of downloaded model in MB."""
        model_path = self._model_path(model_id)
        if not model_path.exists():
            return 0
        total = sum(f.stat().st_size for f in model_path.rglob("*") if f.is_file())
        return total // (1024 * 1024)

    def _remove_model_files(self, model_id: str):
        """Remove model files (for re-download)."""
        model_path = self._model_path(model_id)
        if model_path.exists():
            shutil.rmtree(model_path, ignore_errors=True)

    def _print_install_hint(self, spec: ModelSpec):
        """Print a user-friendly install hint."""
        pkgs = ", ".join(spec.required_packages)
        print(f"\n  {spec.display_name} requires packages: {pkgs}")
        print("  Install with: pip install mempalace[nlp]")

    def _download(self, model_id: str) -> Optional[Path]:
        """Thread-safe download with disk space check."""
        spec = MODEL_CATALOG[model_id]

        # Per-model lock prevents concurrent downloads of the same model
        if model_id not in self._download_locks:
            self._download_locks[model_id] = threading.Lock()

        with self._download_locks[model_id]:
            # Re-check after acquiring lock
            if self.get_status(model_id) == ModelStatus.READY:
                return self._model_path(model_id)

            # Check disk space
            if not self._check_disk_space(spec.size_mb):
                logger.error(
                    f"Not enough disk space for {spec.display_name} "
                    f"(need ~{spec.size_mb} MB). "
                    f"Free space: {self._get_free_space_mb():.0f} MB"
                )
                return None

            model_path = self._model_path(model_id)
            model_path.mkdir(parents=True, exist_ok=True)

            # Write lock file
            lock_file = model_path / ".downloading"
            lock_file.write_text(f"pid={os.getpid()}")

            try:
                if spec.hf_repo_id:
                    return self._download_from_hf(spec, model_path, lock_file)
                logger.info(f"Model download for {spec.display_name} not yet implemented")
                lock_file.unlink(missing_ok=True)
                return None
            except Exception as e:
                lock_file.unlink(missing_ok=True)
                logger.error(f"Download error for {spec.display_name}: {e}")
                return None

    def _download_from_hf(
        self, spec: ModelSpec, model_path: Path, lock_file: Path
    ) -> Optional[Path]:
        """Download a model from HuggingFace Hub using snapshot_download."""
        try:
            from huggingface_hub import snapshot_download

            logger.info(f"Downloading {spec.display_name} from {spec.hf_repo_id}...")
            snapshot_path = snapshot_download(
                repo_id=spec.hf_repo_id,
                local_dir=str(model_path),
            )
            lock_file.unlink(missing_ok=True)
            logger.info(f"Downloaded {spec.display_name} to {snapshot_path}")
            return model_path
        except ImportError:
            logger.error("huggingface_hub not installed — cannot download model")
            lock_file.unlink(missing_ok=True)
            return None
        except Exception as e:
            lock_file.unlink(missing_ok=True)
            logger.error(f"HuggingFace download failed for {spec.display_name}: {e}")
            return None
