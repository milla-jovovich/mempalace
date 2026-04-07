import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from mempalace.config import MempalaceConfig


def test_palace_path_expands_user_home():
    config = MempalaceConfig()

    default_path = config.palace_path
    assert "~" not in default_path
    assert os.path.expanduser("~/.mempalace/palace") == default_path

    with patch.object(config, "_file_config", {"palace_path": "~/custom/palace"}):
        custom_path = config.palace_path
        assert "~" not in custom_path
        expected = os.path.expanduser("~/custom/palace")
        assert expected == custom_path

    with patch.dict(os.environ, {"MEMPALACE_PALACE_PATH": "~/env/palace"}):
        config_with_env = MempalaceConfig()
        env_path = config_with_env.palace_path
        assert "~" not in env_path
        expected = os.path.expanduser("~/env/palace")
        assert expected == env_path


def test_palace_path_with_env_var():
    with patch.dict(os.environ, {"MEMPALACE_PALACE_PATH": "~/test/palace/from/env"}):
        config = MempalaceConfig()
        path = config.palace_path
        expected = os.path.expanduser("~/test/palace/from/env")
        assert path == expected
