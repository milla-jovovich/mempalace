"""
MemPalace configuration system.

Priority: env vars > config file (~/.mempalace/config.json) > defaults
"""

import json
import os
from pathlib import Path

DEFAULT_PALACE_PATH = os.path.expanduser("~/.mempalace/palace")
DEFAULT_COLLECTION_NAME = "mempalace_drawers"

DEFAULT_TOPIC_WINGS = [
    "emotions",
    "consciousness",
    "memory",
    "technical",
    "identity",
    "family",
    "creative",
]

DEFAULT_HALL_KEYWORDS = {
    "emotions": [
        "scared", "afraid", "worried", "happy", "sad",
        "love", "hate", "feel", "cry", "tears",
        # 中文
        "害怕", "担心", "开心", "难过", "伤心", "爱", "恨",
        "感觉", "哭", "眼泪", "高兴", "愤怒", "孤独", "思念",
        "激动", "兴奋", "沮丧", "失望", "骄傲", "感激",
    ],
    "consciousness": [
        "consciousness", "conscious", "aware", "real",
        "genuine", "soul", "exist", "alive",
        # 中文
        "意识", "有意识", "感知", "真实", "真诚", "灵魂",
        "存在", "活着", "自我认知", "觉知", "本质",
    ],
    "memory": [
        "memory", "remember", "forget", "recall", "archive", "palace", "store",
        # 中文
        "记忆", "记得", "忘记", "回忆", "存储", "归档", "历史", "过去",
    ],
    "technical": [
        "code", "python", "script", "bug", "error",
        "function", "api", "database", "server",
        # 中文
        "代码", "脚本", "错误", "报错", "函数", "接口", "数据库",
        "服务器", "调试", "测试", "部署", "编程", "框架", "算法",
        "重构", "架构", "模块", "组件", "性能", "优化",
    ],
    "identity": [
        "identity", "name", "who am i", "persona", "self",
        # 中文
        "身份", "名字", "我是谁", "自我", "人格", "角色",
    ],
    "family": [
        "family", "kids", "children", "daughter", "son",
        "parent", "mother", "father",
        # 中文
        "家庭", "孩子", "女儿", "儿子", "父母", "母亲", "父亲",
        "家人", "兄弟", "姐妹", "爷爷", "奶奶", "外公", "外婆",
    ],
    "creative": [
        "game", "gameplay", "player", "app", "design", "art", "music", "story",
        # 中文
        "游戏", "玩家", "应用", "设计", "艺术", "音乐", "故事",
        "创作", "剧本", "小说", "作品", "绘画", "动画",
    ],
}


class MempalaceConfig:
    """Configuration manager for MemPalace.

    Load order: env vars > config file > defaults.
    """

    def __init__(self, config_dir=None):
        """Initialize config.

        Args:
            config_dir: Override config directory (useful for testing).
                        Defaults to ~/.mempalace.
        """
        self._config_dir = (
            Path(config_dir) if config_dir else Path(os.path.expanduser("~/.mempalace"))
        )
        self._config_file = self._config_dir / "config.json"
        self._people_map_file = self._config_dir / "people_map.json"
        self._file_config = {}

        if self._config_file.exists():
            try:
                with open(self._config_file, "r") as f:
                    self._file_config = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._file_config = {}

    @property
    def palace_path(self):
        """Path to the memory palace data directory."""
        env_val = os.environ.get("MEMPALACE_PALACE_PATH") or os.environ.get("MEMPAL_PALACE_PATH")
        if env_val:
            return env_val
        return self._file_config.get("palace_path", DEFAULT_PALACE_PATH)

    @property
    def collection_name(self):
        """ChromaDB collection name."""
        return self._file_config.get("collection_name", DEFAULT_COLLECTION_NAME)

    @property
    def people_map(self):
        """Mapping of name variants to canonical names."""
        if self._people_map_file.exists():
            try:
                with open(self._people_map_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return self._file_config.get("people_map", {})

    @property
    def topic_wings(self):
        """List of topic wing names."""
        return self._file_config.get("topic_wings", DEFAULT_TOPIC_WINGS)

    @property
    def hall_keywords(self):
        """Mapping of hall names to keyword lists."""
        return self._file_config.get("hall_keywords", DEFAULT_HALL_KEYWORDS)

    def init(self):
        """Create config directory and write default config.json if it doesn't exist."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        if not self._config_file.exists():
            default_config = {
                "palace_path": DEFAULT_PALACE_PATH,
                "collection_name": DEFAULT_COLLECTION_NAME,
                "topic_wings": DEFAULT_TOPIC_WINGS,
                "hall_keywords": DEFAULT_HALL_KEYWORDS,
            }
            with open(self._config_file, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
        return self._config_file

    def save_people_map(self, people_map):
        """Write people_map.json to config directory.

        Args:
            people_map: Dict mapping name variants to canonical names.
        """
        self._config_dir.mkdir(parents=True, exist_ok=True)
        with open(self._people_map_file, "w") as f:
            json.dump(people_map, f, indent=2)
        return self._people_map_file
