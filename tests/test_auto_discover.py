"""Tests for auto-discover wings from root_dir."""

import os
import tempfile
import shutil
import uuid

from mempalace.config import MempalaceConfig
from mempalace.mcp_server import _folder_to_wing, _sync_wings_from_root, _config
import mempalace.mcp_server as mcp_mod


class TestFolderToWing:
    def test_basic(self):
        assert _folder_to_wing("MyProject") == "wing_myproject"

    def test_hyphens_preserved(self):
        assert _folder_to_wing("My-Project") == "wing_my-project"

    def test_underscores_preserved(self):
        assert _folder_to_wing("my_project") == "wing_my_project"

    def test_no_collision_hyphen_vs_underscore(self):
        """Folders 'My-Project' and 'my_project' must produce different wing names."""
        assert _folder_to_wing("My-Project") != _folder_to_wing("my_project")

    def test_special_chars(self):
        assert _folder_to_wing("Project (v2)!") == "wing_project_v2"

    def test_leading_trailing_cleanup(self):
        assert _folder_to_wing("--project--") == "wing_project"

    def test_unicode_cjk_folder(self):
        """CJK folder names are preserved, not stripped."""
        assert _folder_to_wing("プロジェクトA") == "wing_プロジェクトa"

    def test_unicode_korean_folder(self):
        assert _folder_to_wing("프로젝트") == "wing_프로젝트"

    def test_empty_after_strip(self):
        """Folders that become empty after stripping get a fallback name."""
        assert _folder_to_wing("!!!") == "wing_unnamed"


class TestSyncWingsFromRoot:
    def setup_method(self):
        """Reset cache before each test."""
        mcp_mod._discovered_wings_cache = None

    def test_no_root_dir(self):
        """Returns empty when root_dir is not set."""
        original = _config.root_dir
        _config._file_config["root_dir"] = None
        try:
            result = _sync_wings_from_root(force=True)
            assert result == []
        finally:
            if original:
                _config._file_config["root_dir"] = original

    def test_discovers_new_folders(self):
        tmpdir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmpdir, "ProjectA"))
            os.makedirs(os.path.join(tmpdir, "ProjectB"))
            os.makedirs(os.path.join(tmpdir, ".git"))
            os.makedirs(os.path.join(tmpdir, "node_modules"))

            _config._file_config["root_dir"] = tmpdir
            result = _sync_wings_from_root(force=True)

            names = [w["folder"] for w in result]
            assert "ProjectA" in names
            assert "ProjectB" in names
            assert ".git" not in names
            assert "node_modules" not in names
        finally:
            _config._file_config.pop("root_dir", None)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cache_prevents_rescan(self):
        tmpdir = tempfile.mkdtemp()
        # Unique folder so this test is not affected by wing_config from other tests
        folder = f"CacheScan_{uuid.uuid4().hex[:8]}"
        try:
            os.makedirs(os.path.join(tmpdir, folder))
            _config._file_config["root_dir"] = tmpdir

            result1 = _sync_wings_from_root(force=True)
            assert len(result1) > 0

            # Second call should return cached (same object; no filesystem rescan)
            mcp_mod._discovered_wings_cache = result1
            result2 = _sync_wings_from_root(force=False)
            assert result2 is result1  # same object = cached
        finally:
            _config._file_config.pop("root_dir", None)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_chromadb_dependency(self):
        """Wing discovery works without ChromaDB collection access."""
        tmpdir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmpdir, "NewProject"))
            _config._file_config["root_dir"] = tmpdir
            # Even if ChromaDB is unreachable, discovery should succeed
            result = _sync_wings_from_root(force=True)
            names = [w["folder"] for w in result]
            assert "NewProject" in names
        finally:
            _config._file_config.pop("root_dir", None)
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestConfigRootDir:
    def test_root_dir_property(self):
        tmpdir = tempfile.mkdtemp()
        try:
            config = MempalaceConfig(config_dir=tmpdir)
            assert config.root_dir is None

            config._file_config["root_dir"] = "/some/path"
            assert config.root_dir == "/some/path"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_init_saves_root_dir(self):
        tmpdir = tempfile.mkdtemp()
        try:
            config = MempalaceConfig(config_dir=tmpdir)
            config.init(root_dir="/my/projects")

            # Reload and verify
            config2 = MempalaceConfig(config_dir=tmpdir)
            assert config2.root_dir == "/my/projects"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_wing_config_roundtrip(self):
        tmpdir = tempfile.mkdtemp()
        try:
            config = MempalaceConfig(config_dir=tmpdir)
            config.init()

            wc = {"wings": {"wing_test": {"type": "project"}}}
            config.save_wing_config(wc)
            loaded = config.load_wing_config()
            assert loaded["wings"]["wing_test"]["type"] == "project"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
