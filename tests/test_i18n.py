"""Smoke tests for i18n dictionaries + Dialect integration."""

import json
import re
from pathlib import Path

from mempalace.i18n import load_lang, t, available_languages
from mempalace.dialect import Dialect


def test_all_languages_load():
    """Every JSON file loads without error and has required keys."""
    required_sections = ["terms", "cli", "aaak"]
    required_terms = ["palace", "wing", "closet", "drawer"]

    langs = available_languages()
    assert len(langs) >= 7, f"Expected 7+ languages, got {len(langs)}"

    assert "vi" in langs, "Vietnamese (vi) must be included in available languages"

    for lang in langs:
        strings = load_lang(lang)
        for section in required_sections:
            assert section in strings, f"{lang}: missing section '{section}'"
        for term in required_terms:
            assert term in strings["terms"], f"{lang}: missing term '{term}'"
            assert len(strings["terms"][term]) > 0, f"{lang}: empty term '{term}'"
        assert "instruction" in strings["aaak"], f"{lang}: missing aaak.instruction"

    print(f"  PASS: {len(langs)} languages load correctly")


def test_interpolation():
    """String interpolation works for all languages."""
    for lang in available_languages():
        load_lang(lang)
        result = t("cli.mine_complete", closets=5, drawers=100)
        assert "5" in result, f"{lang}: closets count missing from mine_complete"
        assert "100" in result, f"{lang}: drawers count missing from mine_complete"

    print("  PASS: interpolation works for all languages")


def test_dialect_loads_lang():
    """Dialect class picks up the language instruction."""
    for lang in available_languages():
        d = Dialect(lang=lang)
        assert d.lang == lang, f"Expected lang={lang}, got {d.lang}"
        assert len(d.aaak_instruction) > 10, f"{lang}: AAAK instruction too short"

    print("  PASS: Dialect loads language instruction for all languages")


def test_dialect_compress_samples():
    """Compress sample text in different languages, verify output isn't empty."""
    samples = {
        "en": "We decided to migrate from SQLite to PostgreSQL for better concurrent writes. Ben approved the PR yesterday.",
        "fr": "Nous avons décidé de migrer de SQLite vers PostgreSQL pour une meilleure écriture concurrente. Ben a approuvé le PR hier.",
        "ko": "더 나은 동시 쓰기를 위해 SQLite에서 PostgreSQL로 마이그레이션하기로 했습니다. 벤이 어제 PR을 승인했습니다.",
        "ja": "同時書き込みの改善のため、SQLiteからPostgreSQLに移行することを決定しました。ベンが昨日PRを承認しました。",
        "es": "Decidimos migrar de SQLite a PostgreSQL para mejor escritura concurrente. Ben aprobó el PR ayer.",
        "de": "Wir haben beschlossen, von SQLite auf PostgreSQL zu migrieren für bessere gleichzeitige Schreibvorgänge. Ben hat den PR gestern genehmigt.",
        "zh-CN": "我们决定从SQLite迁移到PostgreSQL以获得更好的并发写入。Ben昨天批准了PR。",
        "id": "Kami memutuskan untuk migrasi dari SQLite ke PostgreSQL untuk penulisan bersamaan yang lebih baik. Ben telah menyetujui PR kemarin.",
        "vi": "Chúng tôi quyết định chuyển từ SQLite sang PostgreSQL để cải thiện khả năng ghi đồng thời. Ben đã duyệt PR hôm qua."
    }

    for lang, text in samples.items():
        d = Dialect(lang=lang)
        compressed = d.compress(text)
        assert len(compressed) > 0, f"{lang}: compression returned empty"
        assert len(compressed) < len(text) * 2, f"{lang}: compression expanded text"
        print(f"    {lang}: {len(text)} chars → {len(compressed)} chars")
        print(f"         {compressed[:80]}")

    print("  PASS: compression works for all sample languages")


def test_korean_status_drawers_uses_count():
    """ko.json status_drawers must use {count}, not {drawers}."""
    load_lang("ko")
    result = t("cli.status_drawers", count=42)
    assert "42" in result, f"Expected '42' in '{result}' -- count variable not interpolated"

def test_vietnamese_status_drawers_uses_count():
    """vi.json status_drawers must use {count}."""
    load_lang("vi")
    result = t("cli.status_drawers", count=42)
    assert "42" in result, f"Expected '42' in '{result}'"

def test_from_config_defaults_to_english(tmp_path):
    """Dialect.from_config without a lang key must not inherit module-level state."""
    load_lang("ko")  # pollute module-level _current_lang

    config_path = tmp_path / "config.json"
    config_path.write_text('{"entities": {}}')

    d = Dialect.from_config(str(config_path))
    assert d.lang == "en", f"Expected 'en', got '{d.lang}' -- state leak from prior load_lang"

def test_vietnamese_does_not_fallback_to_english():
    from mempalace.i18n import get_entity_patterns

    vi = get_entity_patterns(("vi",))
    en = get_entity_patterns(("en",))

    assert vi["candidate_patterns"] != en["candidate_patterns"]


def test_vietnamese_regex_matches_text():
    from mempalace.i18n import get_entity_patterns
    import re

    patterns = get_entity_patterns(("vi",))

    text = "Nguyễn Văn A đã triển khai hệ thống GraphQL"

    matches = []
    for p in patterns["candidate_patterns"]:
        matches += re.findall(p, text)

    assert len(matches) > 0

def test_vietnamese_direct_address():
    from mempalace.i18n import get_entity_patterns
    import re

    patterns = get_entity_patterns(("vi",))
    text = "chào Nam, bạn làm xong chưa?"

    raw_patterns = patterns.get("direct_address_pattern", [])

    if isinstance(raw_patterns, str):
        raw_patterns = [raw_patterns]

    name_pattern = r"[A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*"

    matches = []

    for p in raw_patterns:
        if isinstance(p, re.Pattern):
            # pattern đã compile → dùng trực tiếp
            if p.search(text):
                matches.append(True)
        else:
            # pattern dạng string → replace {name}
            p = p.replace("{name}", name_pattern)
            matches += re.findall(p, text, re.IGNORECASE)

    assert len(matches) > 0

def test_vietnamese_unicode_normalization():
    import unicodedata
    from mempalace.i18n import get_entity_patterns
    import re

    text_nfc = "Nguyễn Văn A"
    text_nfd = unicodedata.normalize("NFD", text_nfc)

    patterns = get_entity_patterns(("vi",))

    def match(text):
        out = []
        for p in patterns["candidate_patterns"]:
            out += re.findall(p, text)
        return out

    assert match(text_nfc) != []
    assert match(text_nfd) != []

def test_vietnamese_mixed_english():
    from mempalace.i18n import get_entity_patterns
    import re

    text = "Anh Tuấn deploy GraphQL service hôm qua"

    patterns = get_entity_patterns(("vi",))
    matches = []

    for p in patterns["candidate_patterns"]:
        matches += re.findall(p, text)

    assert len(matches) > 0

def test_vietnamese_dialogue_patterns():
    from mempalace.i18n import get_entity_patterns
    import re

    patterns = get_entity_patterns(("vi",))
    text = "chào Nam, bạn làm xong chưa?"

    raw_patterns = patterns.get("direct_address_pattern", [])

    if isinstance(raw_patterns, str):
        raw_patterns = [raw_patterns]

    matched = False

    for p in raw_patterns:
        if isinstance(p, re.Pattern):
            if p.search(text):
                matched = True
        else:
            name_pattern = r"[A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*"
            p = p.replace("{name}", name_pattern)
            if re.search(p, text, re.IGNORECASE):
                matched = True

    assert matched


def test_vietnamese_schema_keys_match_english():
    i18n_dir = Path(__file__).resolve().parents[1] / "mempalace" / "i18n"
    en = json.loads((i18n_dir / "en.json").read_text(encoding="utf-8"))
    vi = json.loads((i18n_dir / "vi.json").read_text(encoding="utf-8"))

    assert set(vi.keys()) == set(en.keys())
    assert set(vi["terms"].keys()) == set(en["terms"].keys())
    assert set(vi["cli"].keys()) == set(en["cli"].keys())
    assert set(vi["aaak"].keys()) == set(en["aaak"].keys())
    assert set(vi["regex"].keys()) == set(en["regex"].keys())
    assert set(vi["entity"].keys()) == set(en["entity"].keys())


def test_vietnamese_cli_placeholders_match_english():
    i18n_dir = Path(__file__).resolve().parents[1] / "mempalace" / "i18n"
    en = json.loads((i18n_dir / "en.json").read_text(encoding="utf-8"))
    vi = json.loads((i18n_dir / "vi.json").read_text(encoding="utf-8"))
    placeholder_re = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

    for key, en_text in en["cli"].items():
        vi_text = vi["cli"][key]
        assert vi_text.strip(), f"vi.cli.{key} should not be empty"
        en_vars = set(placeholder_re.findall(en_text))
        vi_vars = set(placeholder_re.findall(vi_text))
        assert vi_vars == en_vars, f"vi.cli.{key} placeholders differ from en.cli.{key}"


def test_vietnamese_regex_patterns_compile_and_match_samples():
    from mempalace.i18n import get_regex

    load_lang("vi")
    patterns = get_regex()

    topic_re = re.compile(patterns["topic_pattern"])
    quote_re = re.compile(patterns["quote_pattern"])
    action_re = re.compile(patterns["action_pattern"], re.IGNORECASE)

    text = (
        'Nguyễn Văn Anh đã triển khai hệ thống GraphQL. '
        '"Đây là một đoạn trích dẫn đủ dài để kiểm tra quote pattern hoạt động." '
        "Nhóm vừa cập nhật pipeline xử lý dữ liệu."
    )

    assert topic_re.search(text), "vi.topic_pattern should detect topic-like tokens"
    assert quote_re.search(text), "vi.quote_pattern should capture quoted spans"
    assert action_re.search(text), "vi.action_pattern should detect action phrases"
    assert "và" in patterns["stop_words"]
    assert "là" in patterns["stop_words"]


def test_vietnamese_multi_word_pattern_matches_name():
    from mempalace.i18n import get_entity_patterns

    patterns = get_entity_patterns(("vi",))
    text = "Nguyễn Văn Anh đã triển khai hệ thống mới."

    matches = []
    for pattern in patterns["multi_word_patterns"]:
        matches.extend(re.findall(pattern, text))

    assert any("Nguyễn Văn Anh" in match for match in matches)


def test_vietnamese_entity_lists_have_active_signals():
    from mempalace.i18n import get_entity_patterns

    patterns = get_entity_patterns(("vi",))
    name_pattern = r"[A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*"

    person_hits = 0
    for pattern in patterns["person_verb_patterns"]:
        probe = pattern.replace("{name}", name_pattern)
        if re.search(probe, "Nam nói rõ kế hoạch.", re.IGNORECASE):
            person_hits += 1

    pronoun_hits = 0
    for pattern in patterns["pronoun_patterns"]:
        if re.search(pattern, "Cô ấy đã phản hồi rồi.", re.IGNORECASE):
            pronoun_hits += 1

    project_hits = 0
    for pattern in patterns["project_verb_patterns"]:
        probe = pattern.replace("{name}", name_pattern)
        if re.search(probe, "Nhóm đã xây dựng Atlas.", re.IGNORECASE):
            project_hits += 1

    assert person_hits > 0, "expected at least one vi person_verb pattern to fire"
    assert pronoun_hits > 0, "expected at least one vi pronoun pattern to fire"
    assert project_hits > 0, "expected at least one vi project_verb pattern to fire"
    assert "và" in patterns["stopwords"]
    assert "không" in patterns["stopwords"]
