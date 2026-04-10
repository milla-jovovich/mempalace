"""
test_exporter.py — Tests for palace export/import functionality.

Covers: full export, full import, round-trip fidelity, skip-existing
deduplication, format validation, empty palace handling, and error paths.
"""

import json
import os

from mempalace.exporter import (
    auto_export,
    auto_import,
    backup_palace,
    export_palace,
    export_palace_jsonl,
    import_palace,
    import_palace_jsonl,
    EXPORT_FORMAT,
    EXPORT_VERSION,
)


class TestExport:
    def test_export_drawers(self, palace_path, seeded_collection, tmp_dir):
        output = os.path.join(tmp_dir, "export.json")
        result = export_palace(palace_path=palace_path, output_file=output)

        assert result.success
        assert result.drawers_exported == 4
        assert os.path.exists(output)

        with open(output, "r") as f:
            data = json.load(f)
        assert data["format"] == EXPORT_FORMAT
        assert data["version"] == EXPORT_VERSION
        assert len(data["drawers"]) == 4

    def test_export_with_kg(self, palace_path, seeded_collection, seeded_kg, tmp_dir):
        output = os.path.join(tmp_dir, "export.json")
        result = export_palace(palace_path=palace_path, output_file=output, kg=seeded_kg)

        assert result.success
        assert result.drawers_exported == 4
        assert result.kg_entities_exported > 0
        assert result.kg_triples_exported > 0

        with open(output, "r") as f:
            data = json.load(f)
        assert len(data["kg_entities"]) > 0
        assert len(data["kg_triples"]) > 0

    def test_export_empty_palace(self, palace_path, collection, tmp_dir):
        """Export of empty palace should succeed with zero counts."""
        output = os.path.join(tmp_dir, "empty.json")
        result = export_palace(palace_path=palace_path, output_file=output)

        assert result.success
        assert result.drawers_exported == 0

    def test_export_no_palace(self, tmp_dir):
        """Export from nonexistent palace should still create valid JSON."""
        output = os.path.join(tmp_dir, "none.json")
        missing = os.path.join(tmp_dir, "missing_palace")
        result = export_palace(palace_path=missing, output_file=output)

        assert result.drawers_exported == 0
        # Should still write a valid (empty) export file
        assert os.path.exists(output)

    def test_export_drawer_fields(self, palace_path, seeded_collection, tmp_dir):
        """Each exported drawer should have id, document, and metadata."""
        output = os.path.join(tmp_dir, "export.json")
        export_palace(palace_path=palace_path, output_file=output)

        with open(output, "r") as f:
            data = json.load(f)

        for drawer in data["drawers"]:
            assert "id" in drawer
            assert "document" in drawer
            assert "metadata" in drawer
            assert isinstance(drawer["metadata"], dict)


class TestImport:
    def test_import_drawers(self, tmp_dir):
        """Import drawers into a fresh palace."""
        export_data = {
            "format": EXPORT_FORMAT,
            "version": EXPORT_VERSION,
            "exported_at": "2026-04-09T00:00:00",
            "drawers": [
                {
                    "id": "test_001",
                    "document": "Alice works at Acme Corp on auth.",
                    "metadata": {"wing": "project", "room": "backend", "source_file": "test.py"},
                },
                {
                    "id": "test_002",
                    "document": "Bob built the deployment pipeline.",
                    "metadata": {"wing": "project", "room": "devops", "source_file": "deploy.py"},
                },
            ],
            "kg_entities": [],
            "kg_triples": [],
        }
        input_file = os.path.join(tmp_dir, "import.json")
        with open(input_file, "w") as f:
            json.dump(export_data, f)

        palace = os.path.join(tmp_dir, "new_palace")
        result = import_palace(input_file=input_file, palace_path=palace)

        assert result.success
        assert result.drawers_imported == 2

    def test_import_skips_existing(self, palace_path, seeded_collection, tmp_dir):
        """Import should skip drawers that already exist."""
        # Export first
        export_file = os.path.join(tmp_dir, "export.json")
        export_palace(palace_path=palace_path, output_file=export_file)

        # Import back into the same palace
        result = import_palace(input_file=export_file, palace_path=palace_path)

        assert result.drawers_skipped == 4
        assert result.drawers_imported == 0

    def test_import_kg(self, tmp_dir, kg):
        """Import KG entities and triples."""
        export_data = {
            "format": EXPORT_FORMAT,
            "version": EXPORT_VERSION,
            "exported_at": "2026-04-09T00:00:00",
            "drawers": [],
            "kg_entities": [
                {"id": "alice", "name": "Alice", "type": "person", "properties": "{}"},
            ],
            "kg_triples": [
                {
                    "subject": "Alice",
                    "predicate": "works_at",
                    "object": "Acme",
                    "valid_from": "2020-01-01",
                    "valid_to": None,
                    "confidence": 1.0,
                    "source_closet": None,
                    "source_file": None,
                },
            ],
        }
        input_file = os.path.join(tmp_dir, "import.json")
        with open(input_file, "w") as f:
            json.dump(export_data, f)

        palace = os.path.join(tmp_dir, "new_palace")
        result = import_palace(input_file=input_file, palace_path=palace, kg=kg)

        assert result.kg_entities_imported == 1
        assert result.kg_triples_imported == 1

        # Verify KG data
        facts = kg.query_entity("Alice", direction="outgoing")
        assert any(f["predicate"] == "works_at" for f in facts)

    def test_import_invalid_format(self, tmp_dir):
        """Import should reject files with wrong format."""
        input_file = os.path.join(tmp_dir, "bad.json")
        with open(input_file, "w") as f:
            json.dump({"format": "not_mempalace", "drawers": []}, f)

        palace = os.path.join(tmp_dir, "palace")
        result = import_palace(input_file=input_file, palace_path=palace)

        assert not result.success
        assert any("Unknown format" in e for e in result.errors)

    def test_import_missing_file(self, tmp_dir):
        """Import should handle missing file gracefully."""
        palace = os.path.join(tmp_dir, "palace")
        result = import_palace(input_file="/nonexistent/file.json", palace_path=palace)

        assert not result.success
        assert len(result.errors) > 0


class TestRoundTrip:
    def test_full_roundtrip(self, palace_path, seeded_collection, seeded_kg, tmp_dir):
        """Export → import into new palace → verify data matches."""
        export_file = os.path.join(tmp_dir, "roundtrip.json")

        # Export
        export_result = export_palace(
            palace_path=palace_path,
            output_file=export_file,
            kg=seeded_kg,
        )
        assert export_result.success

        # Import into fresh palace
        new_palace = os.path.join(tmp_dir, "new_palace")
        from mempalace.knowledge_graph import KnowledgeGraph

        new_kg = KnowledgeGraph(db_path=os.path.join(tmp_dir, "new_kg.sqlite3"))

        import_result = import_palace(
            input_file=export_file,
            palace_path=new_palace,
            kg=new_kg,
        )
        assert import_result.drawers_imported == export_result.drawers_exported
        assert import_result.kg_entities_imported == export_result.kg_entities_exported

        # Verify drawer content in new palace
        import chromadb

        client = chromadb.PersistentClient(path=new_palace)
        col = client.get_collection("mempalace_drawers")
        all_data = col.get(include=["documents", "metadatas"])
        assert len(all_data["ids"]) == 4

        # Verify KG content
        facts = new_kg.query_entity("Alice", direction="both")
        assert len(facts) > 0


class TestResultSerialization:
    def test_export_result_to_dict(self, palace_path, seeded_collection, tmp_dir):
        output = os.path.join(tmp_dir, "export.json")
        result = export_palace(palace_path=palace_path, output_file=output)
        d = result.to_dict()

        assert "success" in d
        assert "drawers_exported" in d
        assert "kg_entities_exported" in d
        assert isinstance(d["errors"], list)

    def test_import_result_to_dict(self, tmp_dir):
        input_file = os.path.join(tmp_dir, "bad.json")
        with open(input_file, "w") as f:
            json.dump({"format": "wrong"}, f)

        result = import_palace(input_file=input_file, palace_path=tmp_dir)
        d = result.to_dict()

        assert "success" in d
        assert "drawers_imported" in d
        assert "drawers_skipped" in d


# ── JSONL format tests ──────────────────────────────────────────────


class TestJsonlExport:
    def test_export_jsonl(self, palace_path, seeded_collection, tmp_dir):
        out = os.path.join(tmp_dir, "export_jsonl")
        result = export_palace_jsonl(palace_path=palace_path, output_dir=out)

        assert result.success
        assert result.drawers_exported == 4

        # Check JSONL files exist organized by wing/room
        assert os.path.exists(os.path.join(out, "project", "backend.jsonl"))
        assert os.path.exists(os.path.join(out, "project", "frontend.jsonl"))
        assert os.path.exists(os.path.join(out, "notes", "planning.jsonl"))

        # Each line should be valid JSON with id/document/metadata
        with open(os.path.join(out, "project", "backend.jsonl"), "r") as f:
            for line in f:
                drawer = json.loads(line)
                assert "id" in drawer
                assert "document" in drawer
                assert "metadata" in drawer

    def test_export_jsonl_includes_kg(self, palace_path, seeded_collection, seeded_kg, tmp_dir):
        out = os.path.join(tmp_dir, "export_jsonl")
        result = export_palace_jsonl(palace_path=palace_path, output_dir=out, kg=seeded_kg)

        assert result.kg_entities_exported > 0
        assert os.path.exists(os.path.join(out, "_kg.json"))


class TestJsonlImport:
    def test_import_jsonl(self, palace_path, seeded_collection, seeded_kg, tmp_dir):
        # Export first
        export_dir = os.path.join(tmp_dir, "export_jsonl")
        export_palace_jsonl(palace_path=palace_path, output_dir=export_dir, kg=seeded_kg)

        # Import into a fresh palace
        new_palace = os.path.join(tmp_dir, "new_palace")
        from mempalace.knowledge_graph import KnowledgeGraph

        new_kg = KnowledgeGraph(db_path=os.path.join(tmp_dir, "new_kg.sqlite3"))
        result = import_palace_jsonl(input_dir=export_dir, palace_path=new_palace, kg=new_kg)

        assert result.drawers_imported == 4
        assert result.kg_entities_imported > 0

    def test_import_jsonl_skips_existing(self, palace_path, seeded_collection, tmp_dir):
        export_dir = os.path.join(tmp_dir, "export_jsonl")
        export_palace_jsonl(palace_path=palace_path, output_dir=export_dir)

        # Import back into the same palace
        result = import_palace_jsonl(input_dir=export_dir, palace_path=palace_path)
        assert result.drawers_skipped == 4
        assert result.drawers_imported == 0


# ── Auto-detection tests ─────────────────────────────────────────────


class TestAutoFormatDetection:
    def test_auto_export_json_file(self, palace_path, seeded_collection, tmp_dir):
        out = os.path.join(tmp_dir, "out.json")
        result = auto_export(palace_path=palace_path, output=out)
        assert result.success
        assert os.path.isfile(out)

    def test_auto_export_directory(self, palace_path, seeded_collection, tmp_dir):
        out = os.path.join(tmp_dir, "out_dir")
        result = auto_export(palace_path=palace_path, output=out)
        assert result.success
        assert os.path.isdir(out)

    def test_auto_export_format_override(self, palace_path, seeded_collection, tmp_dir):
        # Override: force JSON even for a non-.json path
        out = os.path.join(tmp_dir, "force_json")
        result = auto_export(palace_path=palace_path, output=out, format="json")
        assert result.success
        assert os.path.isfile(out)

    def test_auto_import_file(self, palace_path, seeded_collection, tmp_dir):
        out = os.path.join(tmp_dir, "out.json")
        export_palace(palace_path=palace_path, output_file=out)
        new_palace = os.path.join(tmp_dir, "new")
        result = auto_import(input_path=out, palace_path=new_palace)
        assert result.drawers_imported == 4

    def test_auto_import_directory(self, palace_path, seeded_collection, tmp_dir):
        out = os.path.join(tmp_dir, "out_dir")
        export_palace_jsonl(palace_path=palace_path, output_dir=out)
        new_palace = os.path.join(tmp_dir, "new")
        result = auto_import(input_path=out, palace_path=new_palace)
        assert result.drawers_imported == 4


# ── Binary backup tests ──────────────────────────────────────────────


class TestBackup:
    def test_backup_directory(self, palace_path, seeded_collection, tmp_dir):
        result = backup_palace(palace_path=palace_path, max_backups=0)
        assert result.success
        assert os.path.isdir(result.backup_path)
        assert result.size_bytes > 0

    def test_backup_zip(self, palace_path, seeded_collection, tmp_dir):
        result = backup_palace(palace_path=palace_path, zip_mode=True, max_backups=0)
        assert result.success
        assert result.backup_path.endswith(".zip")
        assert os.path.isfile(result.backup_path)

    def test_backup_no_palace(self, tmp_dir):
        result = backup_palace(palace_path=os.path.join(tmp_dir, "missing"))
        assert not result.success
        assert len(result.errors) > 0

    def test_backup_result_to_dict(self, palace_path, seeded_collection):
        result = backup_palace(palace_path=palace_path, max_backups=0)
        d = result.to_dict()
        assert "success" in d
        assert "backup_path" in d
        assert "size_mb" in d


class TestBackupValidation:
    def test_valid_backup_passes(self, palace_path, seeded_collection):
        result = backup_palace(palace_path=palace_path, max_backups=0)
        assert result.success
        assert len(result.validation_errors) == 0

    def test_valid_zip_backup_passes(self, palace_path, seeded_collection):
        result = backup_palace(palace_path=palace_path, zip_mode=True, max_backups=0)
        assert result.success
        assert len(result.validation_errors) == 0

    def test_backup_result_has_validation_field(self, palace_path, seeded_collection):
        result = backup_palace(palace_path=palace_path, max_backups=0)
        d = result.to_dict()
        assert "validation_errors" in d
