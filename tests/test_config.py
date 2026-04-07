import os
import json
import shutil
import tempfile
from mempalace.config import MempalaceConfig


def _force_rmtree(path):
    """Remove a temp directory, handling Windows file-lock issues."""

    def _onerror(func, fpath, exc_info):
        import stat

        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except OSError:
            pass  # temp dir will be cleaned up by OS eventually

    shutil.rmtree(path, onerror=_onerror)


def test_default_config():
    tmpdir = tempfile.mkdtemp()
    try:
        cfg = MempalaceConfig(config_dir=tmpdir)
        assert "palace" in cfg.palace_path
        assert cfg.collection_name == "mempalace_drawers"
    finally:
        _force_rmtree(tmpdir)


def test_config_from_file():
    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "config.json"), "w") as f:
            json.dump({"palace_path": "/custom/palace"}, f)
        cfg = MempalaceConfig(config_dir=tmpdir)
        assert cfg.palace_path == "/custom/palace"
    finally:
        _force_rmtree(tmpdir)


def test_env_override():
    old_val = os.environ.get("MEMPALACE_PALACE_PATH")
    try:
        os.environ["MEMPALACE_PALACE_PATH"] = "/env/palace"
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        assert cfg.palace_path == "/env/palace"
    finally:
        if old_val is None:
            os.environ.pop("MEMPALACE_PALACE_PATH", None)
        else:
            os.environ["MEMPALACE_PALACE_PATH"] = old_val


def test_init():
    tmpdir = tempfile.mkdtemp()
    try:
        cfg = MempalaceConfig(config_dir=tmpdir)
        cfg.init()
        assert os.path.exists(os.path.join(tmpdir, "config.json"))
    finally:
        _force_rmtree(tmpdir)
