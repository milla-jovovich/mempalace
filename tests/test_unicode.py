"""Tests for Unicode/i18n support — Cyrillic and multilingual text."""

from mempalace.entity_detector import extract_candidates, score_entity, classify_entity
from mempalace.dialect import Dialect


# ==================== entity_detector ====================


class TestCyrillicEntityDetection:
    """Test that Cyrillic proper nouns are detected as entity candidates."""

    def test_single_cyrillic_names(self):
        text = "Никита пришёл домой. Никита сказал привет. Никита любит код."
        candidates = extract_candidates(text)
        assert "Никита" in candidates
        assert candidates["Никита"] >= 3

    def test_multiple_cyrillic_entities(self):
        text = (
            "Алиса и Борис работают вместе. "
            "Алиса написала код. Борис проверил код. "
            "Алиса сказала спасибо. Борис ответил. "
            "Алиса и Борис обсудили результат."
        )
        candidates = extract_candidates(text)
        assert "Алиса" in candidates
        assert "Борис" in candidates

    def test_mixed_latin_cyrillic(self):
        text = (
            "Alice met Никита at the conference. "
            "Alice presented her work. Никита asked questions. "
            "Alice and Никита discussed the architecture. "
            "Alice loves Python. Никита prefers TypeScript."
        )
        candidates = extract_candidates(text)
        assert "Alice" in candidates
        assert "Никита" in candidates

    def test_multi_word_cyrillic_names(self):
        text = (
            "Мем Палас работает отлично. "
            "Мем Палас использует ChromaDB. "
            "Мем Палас поддерживает юникод."
        )
        candidates = extract_candidates(text)
        assert "Мем Палас" in candidates

    def test_cyrillic_stopwords_filtered(self):
        """Common Russian words should not appear as entity candidates."""
        text = (
            "Время идёт быстро. Время не ждёт. Время покажет. "
            "Система работает. Система стабильна. Система готова."
        )
        candidates = extract_candidates(text)
        assert "Время" not in candidates
        assert "Система" not in candidates

    def test_cyrillic_person_scoring(self):
        text = (
            "Никита сказал привет. Никита спросил как дела. "
            "Никита ответил что хорошо. Он рад видеть всех. "
            "Привет Никита, спасибо Никита."
        )
        lines = text.splitlines()
        scores = score_entity("Никита", text, lines)
        assert scores["person_score"] > 0
        assert len(scores["person_signals"]) > 0


# ==================== dialect ====================


class TestCyrillicDialect:
    """Test that the AAAK Dialect handles Cyrillic text correctly."""

    def test_compress_cyrillic_text(self):
        dialect = Dialect()
        text = "Мы решили использовать GraphQL вместо REST для нашего API."
        result = dialect.compress(text)
        assert result  # should produce non-empty output
        assert "|" in result  # should have AAAK structure

    def test_topic_extraction_cyrillic(self):
        dialect = Dialect()
        topics = dialect._extract_topics(
            "Архитектура микросервисов позволяет масштабировать приложение"
        )
        assert len(topics) > 0
        # Should contain meaningful Russian words, not be empty
        assert any(len(t) > 2 for t in topics)

    def test_topic_extraction_mixed(self):
        dialect = Dialect()
        topics = dialect._extract_topics(
            "NanoClaw использует TypeScript и Docker для деплоя"
        )
        assert len(topics) > 0

    def test_emotion_detection_russian(self):
        dialect = Dialect()
        emotions = dialect._detect_emotions("Я очень надеюсь что всё получится")
        assert "hope" in emotions

    def test_emotion_detection_russian_fear(self):
        dialect = Dialect()
        emotions = dialect._detect_emotions("Боюсь что не успеем к дедлайну")
        assert "fear" in emotions

    def test_flag_detection_russian(self):
        dialect = Dialect()
        flags = dialect._detect_flags("Мы решили перейти на новый фреймворк")
        assert "DECISION" in flags

    def test_flag_detection_russian_technical(self):
        dialect = Dialect()
        flags = dialect._detect_flags("Архитектура сервера требует рефакторинга")
        assert "TECHNICAL" in flags

    def test_entity_detection_in_cyrillic_text(self):
        dialect = Dialect(entities={"Никита": "НКТ"})
        entities = dialect._detect_entities_in_text("Никита написал новый модуль")
        assert "НКТ" in entities

    def test_entity_auto_code_cyrillic(self):
        dialect = Dialect()
        code = dialect.encode_entity("Никита")
        assert code == "НИК"

    def test_entity_detection_fallback_cyrillic(self):
        """Capitalized Cyrillic words should be detected as entities in fallback mode."""
        dialect = Dialect()
        entities = dialect._detect_entities_in_text(
            "вчера Никита обсудил проект с Борисом"
        )
        # Should find at least one Cyrillic entity
        assert len(entities) > 0

    def test_key_sentence_russian(self):
        dialect = Dialect()
        text = (
            "Проект развивается хорошо. "
            "Мы решили использовать новый подход. "
            "Это длинное предложение которое описывает множество деталей и аспектов работы над проектом."
        )
        sentence = dialect._extract_key_sentence(text)
        assert len(sentence) > 0
        # Should prefer the decision sentence over generic ones
        assert "решили" in sentence.lower()

    def test_compress_preserves_cyrillic_entities(self):
        dialect = Dialect(entities={"Владлен": "ВЛД", "Никита": "НКТ"})
        text = "Владлен помог Никите разобраться с архитектурой деплоя."
        result = dialect.compress(text)
        assert "ВЛД" in result or "НКТ" in result

    def test_stopwords_dont_become_topics(self):
        dialect = Dialect()
        topics = dialect._extract_topics(
            "это просто очень хорошо что всё работает потому что надо было сделать"
        )
        # Common stopwords should not be topics
        stopwords = {"это", "просто", "очень", "потому"}
        for t in topics:
            assert t not in stopwords

    def test_profanity_emotion_signals(self):
        """Profanity carries strong emotional signals in Russian."""
        dialect = Dialect()
        assert "joy" in dialect._detect_emotions("Заебись, всё работает!")
        assert "fear" in dialect._detect_emotions("Пиздец, всё сломалось")
        assert "rage" in dialect._detect_emotions("Бесит эта хрень")
        assert "frust" in dialect._detect_emotions("Заебал этот баг")

    def test_profanity_not_entities(self):
        """Profanity at sentence starts should not become entity candidates."""
        text = (
            "Блять, опять ошибка. Блять, не работает. Блять, почему. "
            "Сука, опять. Сука, сломалось. Сука, почему так."
        )
        candidates = extract_candidates(text)
        assert "Блять" not in candidates
        assert "Сука" not in candidates

    def test_new_person_verb_patterns(self):
        """New Russian person verbs should fire as person signals."""
        text = (
            "Маша поняла задачу. Маша согласилась помочь. "
            "Маша объяснила решение. Маша показала результат. "
            "Маша вспомнила о встрече."
        )
        lines = text.splitlines()
        scores = score_entity("Маша", text, lines)
        assert scores["person_score"] > 0

    def test_new_flag_signals(self):
        """New Russian flag signals should be detected."""
        dialect = Dialect()
        assert "DECISION" in dialect._detect_flags("Мы отказались от старого подхода")
        assert "ORIGIN" in dialect._detect_flags("Он придумал новый алгоритм")
        assert "TECHNICAL" in dialect._detect_flags("Нужен рефакторинг модуля")
        assert "PIVOT" in dialect._detect_flags("Это было настоящее открытие")

    def test_prepositional_pronoun_proximity(self):
        """Prepositional pronoun forms should fire as person proximity signals."""
        text = (
            "Андрей работал весь день. О нём говорили коллеги. "
            "Андрей предложил решение. С ним согласились все. "
            "Андрей показал результат. У него получилось."
        )
        lines = text.splitlines()
        scores = score_entity("Андрей", text, lines)
        assert scores["person_score"] > 0
        assert any("pronoun" in s for s in scores["person_signals"])
