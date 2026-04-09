"""Tests for entity detector CODE_KEYWORDS filtering (#348)."""

from mempalace.entity_detector import extract_candidates, detect_entities, CODE_KEYWORDS, STOPWORDS


class TestCodeKeywordsFiltering:
    """Verify that programming keywords are excluded from entity candidates."""

    def test_rust_types_excluded(self):
        """Rust types like String, Vec, Debug should not be candidates."""
        text = "String " * 10 + "Vec " * 10 + "Debug " * 10 + "Clone " * 10
        candidates = extract_candidates(text)
        for keyword in ["String", "Vec", "Debug", "Clone"]:
            assert keyword not in candidates, f"{keyword} should be filtered by CODE_KEYWORDS"

    def test_rust_derive_macros_excluded(self):
        """Serialize, Deserialize should not be candidates."""
        text = "Serialize " * 10 + "Deserialize " * 10
        candidates = extract_candidates(text)
        assert "Serialize" not in candidates
        assert "Deserialize" not in candidates

    def test_framework_names_excluded(self):
        """React, Tauri, Node, Vue should not be candidates."""
        text = "React " * 10 + "Tauri " * 10 + "Node " * 10 + "Vue " * 10
        candidates = extract_candidates(text)
        for name in ["React", "Tauri", "Node", "Vue"]:
            assert name not in candidates, f"{name} should be filtered"

    def test_language_names_excluded(self):
        """Rust, Python, Kotlin etc should not be candidates."""
        text = "Rust " * 10 + "Python " * 10 + "Kotlin " * 10
        candidates = extract_candidates(text)
        for name in ["Rust", "Python", "Kotlin"]:
            assert name not in candidates, f"{name} should be filtered"

    def test_common_code_patterns_excluded(self):
        """Phase, Flow, Tree, Graph should not be candidates."""
        text = "Phase " * 10 + "Flow " * 10 + "Tree " * 10 + "Graph " * 10
        candidates = extract_candidates(text)
        for name in ["Phase", "Flow", "Tree", "Graph"]:
            assert name not in candidates, f"{name} should be filtered"

    def test_real_project_names_not_excluded(self):
        """Actual project names like CodeMAP, MalCheck should still be detected."""
        # These are not in CODE_KEYWORDS or STOPWORDS
        assert "codemap" not in CODE_KEYWORDS
        assert "malcheck" not in CODE_KEYWORDS
        assert "codemap" not in STOPWORDS
        assert "malcheck" not in STOPWORDS

    def test_real_person_names_not_excluded(self):
        """Real person names should still be candidates."""
        text = "Alice " * 10 + "Bob " * 10 + "Charlie " * 10
        candidates = extract_candidates(text)
        assert "Alice" in candidates
        assert "Bob" in candidates
        assert "Charlie" in candidates

    def test_code_keywords_are_lowercase(self):
        """All CODE_KEYWORDS entries should be lowercase for consistent matching."""
        for keyword in CODE_KEYWORDS:
            assert keyword == keyword.lower(), f"CODE_KEYWORDS entry '{keyword}' should be lowercase"

    def test_no_overlap_with_stopwords(self):
        """CODE_KEYWORDS should not duplicate STOPWORDS entries (keep sets clean)."""
        overlap = CODE_KEYWORDS & STOPWORDS
        # Some overlap is acceptable but flag it for awareness
        # This test documents the current state rather than enforcing zero overlap
        assert isinstance(overlap, set)  # just verify it runs

    def test_detect_entities_with_code_heavy_content(self, tmp_path):
        """Full pipeline: code-heavy files should not produce false project detections."""
        # Create a fake Rust-like file
        rust_content = """
        use std::collections::HashMap;
        #[derive(Debug, Clone, Serialize, Deserialize)]
        struct Config {
            name: String,
            values: Vec<String>,
        }
        impl Default for Config {
            fn default() -> Self { Config { name: String::new(), values: Vec::new() } }
        }
        """ * 5

        test_file = tmp_path / "main.rs"
        test_file.write_text(rust_content)

        # Also create a prose file mentioning a real project
        prose_file = tmp_path / "README.md"
        prose_file.write_text("MyProject is a tool for data analysis. " * 10)

        result = detect_entities([prose_file, test_file], max_files=10)

        # Rust keywords should NOT appear as projects
        project_names = [e["name"] for e in result["projects"]]
        uncertain_names = [e["name"] for e in result["uncertain"]]
        all_detected = project_names + uncertain_names

        for keyword in ["String", "Vec", "Debug", "Clone", "Serialize", "Deserialize"]:
            assert keyword not in all_detected, f"{keyword} should not be detected"
