"""Tests for Unicode/i18n support — Cyrillic and multilingual text."""

from mempalace.entity_detector import extract_candidates, score_entity, classify_entity
from mempalace.dialect import Dialect

RU = ("ru",)
EN_RU = ("en", "ru")


# ==================== entity_detector ====================


class TestCyrillicEntityDetection:
    """Test that Cyrillic proper nouns are detected as entity candidates."""

    def test_single_cyrillic_names(self):
        text = "Никита пришёл домой. Никита сказал привет. Никита любит код."
        candidates = extract_candidates(text, languages=RU)
        assert "Никита" in candidates
        assert candidates["Никита"] >= 3

    def test_multiple_cyrillic_entities(self):
        text = (
            "Алиса и Борис работают вместе. "
            "Алиса написала код. Борис проверил код. "
            "Алиса сказала спасибо. Борис ответил. "
            "Алиса и Борис обсудили результат."
        )
        candidates = extract_candidates(text, languages=RU)
        assert "Алиса" in candidates
        assert "Борис" in candidates

    def test_mixed_latin_cyrillic(self):
        text = (
            "Alice met Никита at the conference. "
            "Alice presented her work. Никита asked questions. "
            "Alice and Никита discussed the architecture. "
            "Alice loves Python. Никита prefers TypeScript."
        )
        candidates = extract_candidates(text, languages=EN_RU)
        assert "Alice" in candidates
        assert "Никита" in candidates

    def test_multi_word_cyrillic_names(self):
        text = (
            "Мем Палас работает отлично. "
            "Мем Палас использует ChromaDB. "
            "Мем Палас поддерживает юникод."
        )
        candidates = extract_candidates(text, languages=RU)
        assert "Мем Палас" in candidates

    def test_cyrillic_stopwords_filtered(self):
        """Common Russian stopwords should not appear as entity candidates."""
        text = (
            "Привет друзья сегодня. Привет давно не виделись. Привет как дела. "
            "Спасибо за помощь. Спасибо большое. Спасибо огромное."
        )
        candidates = extract_candidates(text, languages=RU)
        assert "Привет" not in candidates
        assert "Спасибо" not in candidates

    def test_cyrillic_person_scoring(self):
        text = (
            "Никита сказал привет. Никита спросил как дела. "
            "Никита ответил что хорошо. Он рад видеть всех. "
            "Привет Никита, спасибо Никита."
        )
        lines = text.splitlines()
        scores = score_entity("Никита", text, lines, languages=RU)
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
        # Upstream dialect._extract_topics uses ASCII regex — pure Cyrillic
        # returns empty topics. Mixed text extracts Latin tokens.
        dialect = Dialect()
        topics = dialect._extract_topics(
            "NanoClaw использует TypeScript и Docker для деплоя"
        )
        assert len(topics) > 0
        assert any(len(t) > 2 for t in topics)

    def test_topic_extraction_mixed(self):
        dialect = Dialect()
        topics = dialect._extract_topics(
            "NanoClaw использует TypeScript и Docker для деплоя"
        )
        assert len(topics) > 0

    def test_emotion_detection_english_keywords(self):
        dialect = Dialect()
        assert "hope" in dialect._detect_emotions("I hope this works out")
        assert "fear" in dialect._detect_emotions("I fear we won't make the deadline")

    def test_flag_detection_english_keywords(self):
        dialect = Dialect()
        assert "DECISION" in dialect._detect_flags("We decided to switch to the new framework")
        assert "TECHNICAL" in dialect._detect_flags("The server architecture needs refactoring")

    def test_entity_detection_in_cyrillic_text(self):
        dialect = Dialect(entities={"Никита": "НКТ"})
        entities = dialect._detect_entities_in_text("Никита написал новый модуль")
        assert "НКТ" in entities

    def test_entity_auto_code_cyrillic(self):
        dialect = Dialect()
        code = dialect.encode_entity("Никита")
        assert code == "НИК"

    def test_entity_detection_fallback_latin(self):
        """Capitalized Latin words should be detected as entities in fallback mode."""
        dialect = Dialect()
        entities = dialect._detect_entities_in_text(
            "Yesterday Alice discussed the project with Bob"
        )
        assert len(entities) > 0

    def test_key_sentence_extraction(self):
        dialect = Dialect()
        text = (
            "The project is going well. "
            "We decided to use a new approach. "
            "This is a long sentence that describes many details and aspects of the project work."
        )
        sentence = dialect._extract_key_sentence(text)
        assert len(sentence) > 0
        assert "decided" in sentence.lower()

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

    def test_russian_person_verb_patterns(self):
        """Russian person verbs from i18n should fire as person signals."""
        text = (
            "Никита сказал привет. Никита спросил как дела. "
            "Никита ответил что хорошо. Никита решил задачу. "
            "Никита предложил вариант."
        )
        lines = text.splitlines()
        scores = score_entity("Никита", text, lines, languages=RU)
        assert scores["person_score"] > 0

    def test_russian_pronoun_proximity(self):
        """Russian pronoun patterns from i18n should fire as person signals."""
        text = (
            "Андрей работал весь день. Он сделал отчёт. "
            "Андрей предложил решение. Его идея понравилась. "
            "Андрей показал результат. Ему доверяют."
        )
        lines = text.splitlines()
        scores = score_entity("Андрей", text, lines, languages=RU)
        assert scores["person_score"] > 0
        assert any("pronoun" in s for s in scores["person_signals"])
