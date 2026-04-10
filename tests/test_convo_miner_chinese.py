"""Tests for Chinese room classification in convo_miner."""

import pytest
from conftest import HAS_MULTILINGUAL

pytestmark = pytest.mark.skipif(
    not HAS_MULTILINGUAL,
    reason="requires sentence-transformers (pip install mempalace[multilingual])",
)

from mempalace.convo_miner import detect_convo_room  # noqa: E402


class TestChineseRoomDetection:
    def test_chinese_technical_room(self):
        content = "我们需要修改代码来修复这个错误。调试了很久终于找到问题。部署到服务器上。"
        assert detect_convo_room(content) == "technical"

    def test_traditional_chinese_technical_room(self):
        content = "我們需要修改代碼來修復這個錯誤。調試了很久終於找到問題。"
        assert detect_convo_room(content) == "technical"

    def test_chinese_decisions_room(self):
        content = "我们决定使用新的方案。选择了这个策略是因为权衡了各种因素。"
        assert detect_convo_room(content) == "decisions"

    def test_chinese_problems_room(self):
        content = "系统出现了严重的故障，崩溃了好几次。这个问题需要尽快修复和解决。"
        assert detect_convo_room(content) == "problems"

    def test_chinese_planning_room(self):
        content = "我们需要制定计划，确定里程碑和截止日期。需求规格要尽快完成。"
        assert detect_convo_room(content) == "planning"

    def test_chinese_architecture_room(self):
        content = "系统的架构设计需要重新考虑。模块和组件的结构不够合理。"
        assert detect_convo_room(content) == "architecture"

    def test_mixed_content_room(self):
        """Chinese + English keywords should score together."""
        content = "We need to fix the 代码 bug. The 错误 in the database is causing crashes."
        room = detect_convo_room(content)
        assert room in ("technical", "problems")

    def test_english_room_detection_unchanged(self):
        content = "The code has a bug in the database query function. Need to debug the API server."
        assert detect_convo_room(content) == "technical"

    def test_general_room_fallback(self):
        content = "今天天气不错，我们出去散步了。"
        assert detect_convo_room(content) == "general"
