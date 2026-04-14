#!/usr/bin/env python3
"""Quick smoke test for i18n dictionaries + Dialect integration."""

import sys
from pathlib import Path

# Add parent to path so we can import mempalace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mempalace.i18n import load_lang, t, available_languages
from mempalace.dialect import Dialect


def test_all_languages_load():
    """Every JSON file loads without error and has required keys."""
    required_sections = ["terms", "cli", "aaak"]
    required_terms = ["palace", "wing", "closet", "drawer"]

    langs = available_languages()
    assert len(langs) >= 7, f"Expected 7+ languages, got {len(langs)}"

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
    }

    for lang, text in samples.items():
        d = Dialect(lang=lang)
        compressed = d.compress(text)
        assert len(compressed) > 0, f"{lang}: compression returned empty"
        assert len(compressed) < len(text) * 2, f"{lang}: compression expanded text"
        print(f"    {lang}: {len(text)} chars → {len(compressed)} chars")
        print(f"         {compressed[:80]}")

    print("  PASS: compression works for all sample languages")


if __name__ == "__main__":
    print("i18n smoke tests:")
    test_all_languages_load()
    test_interpolation()
    test_dialect_loads_lang()
    test_dialect_compress_samples()
    print("\nAll tests passed.")
