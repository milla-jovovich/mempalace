"""
test_entity_system.py — Tests for entity declaration, collision detection,
merge, predicate constraints, cardinality enforcement, and class inheritance.

Covers the full entity lifecycle introduced in PRs #1-#15 on smaugho/mempalace.
"""

import json


def _patch_mcp(monkeypatch, config, kg, palace_path):
    """Patch mcp_server globals and reset declared entities for a clean test."""
    import chromadb
    from mempalace import mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)

    # Ensure entity collection exists in test palace
    client = chromadb.PersistentClient(path=palace_path)
    client.get_or_create_collection("mempalace_drawers")
    client.get_or_create_collection("mempalace_entities")
    del client

    # Reset session state
    mcp_server._declared_entities = set()
    mcp_server._session_id = "test-session"


def _declare(name, description, kind="entity", importance=3, constraints=None):
    from mempalace.mcp_server import tool_kg_declare_entity

    kwargs = {"name": name, "description": description, "kind": kind, "importance": importance}
    if constraints is not None:
        kwargs["constraints"] = constraints
    return tool_kg_declare_entity(**kwargs)


def _add_edge(subject, predicate, obj):
    from mempalace.mcp_server import tool_kg_add

    return tool_kg_add(subject=subject, predicate=predicate, object=obj)


# ── Entity Declaration ────────────────────────────────────────────────


class TestEntityDeclaration:
    def test_declare_new_entity(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        result = _declare("test-server", "A test server for unit tests", kind="entity", importance=4)
        assert result["success"] is True
        assert result["status"] == "created"
        assert result["entity_id"] == "test_server"
        assert result["kind"] == "entity"

    def test_declare_existing_entity_returns_exists(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        _declare("my-tool", "A development tool", kind="entity")
        result = _declare("my-tool", "A development tool", kind="entity")
        assert result["success"] is True
        assert result["status"] == "exists"

    def test_declare_entity_normalizes_name(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        result = _declare("My CamelCase Entity", "Test entity", kind="entity")
        assert result["entity_id"] == "my_camel_case_entity"

    def test_declare_entity_strips_articles(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        result = _declare("the-big-server", "A big server", kind="entity")
        assert result["entity_id"] == "big_server"

    def test_kind_is_required(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        result = _declare("no-kind", "Missing kind", kind=None)
        assert result["success"] is False
        assert "kind" in result["error"].lower() or "REQUIRED" in result["error"]

    def test_invalid_kind_rejected(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        result = _declare("bad-kind", "Bad kind", kind="widget")
        assert result["success"] is False

    def test_declare_registers_in_session(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)
        from mempalace.mcp_server import _declared_entities

        _declare("session-entity", "Test entity for session", kind="entity")
        assert "session_entity" in _declared_entities


# ── Predicate Declaration ─────────────────────────────────────────────


class TestPredicateDeclaration:
    def _setup_classes(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        # Need root class 'thing' for constraints
        _declare("thing", "Root class of the ontology", kind="class", importance=5)
        _declare("system", "A running infrastructure component", kind="class", importance=4)
        _declare("tool", "A software tool", kind="class", importance=4)

    def test_predicate_requires_constraints(self, monkeypatch, config, palace_path, kg):
        self._setup_classes(monkeypatch, config, palace_path, kg)

        result = _declare("my-predicate", "A test predicate", kind="predicate")
        assert result["success"] is False
        assert "constraints" in result["error"].lower() or "REQUIRE" in result["error"]

    def test_predicate_requires_all_5_fields(self, monkeypatch, config, palace_path, kg):
        self._setup_classes(monkeypatch, config, palace_path, kg)

        # Missing object_classes
        result = _declare(
            "incomplete-pred", "Missing fields", kind="predicate",
            constraints={
                "subject_kinds": ["entity"],
                "object_kinds": ["entity"],
                "subject_classes": ["thing"],
                "cardinality": "many-to-many",
            },
        )
        assert result["success"] is False
        assert "object_classes" in result["error"]

    def test_predicate_valid_full_constraints(self, monkeypatch, config, palace_path, kg):
        self._setup_classes(monkeypatch, config, palace_path, kg)

        result = _declare(
            "tested-by", "Subject is tested by object", kind="predicate", importance=4,
            constraints={
                "subject_kinds": ["entity"],
                "object_kinds": ["entity"],
                "subject_classes": ["thing"],
                "object_classes": ["thing"],
                "cardinality": "many-to-many",
            },
        )
        assert result["success"] is True
        assert result["status"] == "created"

    def test_predicate_invalid_cardinality(self, monkeypatch, config, palace_path, kg):
        self._setup_classes(monkeypatch, config, palace_path, kg)

        result = _declare(
            "bad-card", "Bad cardinality", kind="predicate",
            constraints={
                "subject_kinds": ["entity"],
                "object_kinds": ["entity"],
                "subject_classes": ["thing"],
                "object_classes": ["thing"],
                "cardinality": "one-to-none",
            },
        )
        assert result["success"] is False
        assert "cardinality" in result["error"].lower()

    def test_predicate_invalid_kind_in_subject_kinds(self, monkeypatch, config, palace_path, kg):
        self._setup_classes(monkeypatch, config, palace_path, kg)

        result = _declare(
            "bad-kinds", "Bad subject kinds", kind="predicate",
            constraints={
                "subject_kinds": ["widget"],
                "object_kinds": ["entity"],
                "subject_classes": ["thing"],
                "object_classes": ["thing"],
                "cardinality": "many-to-many",
            },
        )
        assert result["success"] is False
        assert "widget" in result["error"]

    def test_predicate_nonexistent_class_rejected(self, monkeypatch, config, palace_path, kg):
        self._setup_classes(monkeypatch, config, palace_path, kg)

        result = _declare(
            "bad-class-ref", "References nonexistent class", kind="predicate",
            constraints={
                "subject_kinds": ["entity"],
                "object_kinds": ["entity"],
                "subject_classes": ["nonexistent_class"],
                "object_classes": ["thing"],
                "cardinality": "many-to-many",
            },
        )
        assert result["success"] is False
        assert "nonexistent_class" in result["error"]

    def test_predicate_class_must_be_kind_class(self, monkeypatch, config, palace_path, kg):
        self._setup_classes(monkeypatch, config, palace_path, kg)

        # Declare a non-class entity, then try to use it as a class in constraints
        _declare("my-entity", "A regular entity", kind="entity")
        result = _declare(
            "bad-class-kind", "Class ref is not kind=class", kind="predicate",
            constraints={
                "subject_kinds": ["entity"],
                "object_kinds": ["entity"],
                "subject_classes": ["my-entity"],
                "object_classes": ["thing"],
                "cardinality": "many-to-many",
            },
        )
        assert result["success"] is False
        assert "kind=" in result["error"]


# ── kg_add enforcement ────────────────────────────────────────────────


class TestKgAddEnforcement:
    def _setup(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        # Classes
        _declare("thing", "Root class", kind="class", importance=5)
        _declare("system", "Infrastructure component", kind="class", importance=4)
        _declare("rule", "Standing order", kind="class", importance=4)

        # Predicate
        _declare(
            "depends-on", "Subject depends on object", kind="predicate", importance=4,
            constraints={
                "subject_kinds": ["entity"],
                "object_kinds": ["entity"],
                "subject_classes": ["thing"],
                "object_classes": ["thing"],
                "cardinality": "many-to-many",
            },
        )

        # Entities
        _declare("server-a", "Server A for testing", kind="entity")
        _declare("server-b", "Server B for testing", kind="entity")

    def test_undeclared_subject_rejected(self, monkeypatch, config, palace_path, kg):
        self._setup(monkeypatch, config, palace_path, kg)

        result = _add_edge("unknown-entity", "depends-on", "server-b")
        assert result["success"] is False
        assert "not declared" in result["issues"][0]

    def test_undeclared_predicate_rejected(self, monkeypatch, config, palace_path, kg):
        self._setup(monkeypatch, config, palace_path, kg)

        result = _add_edge("server-a", "unknown-pred", "server-b")
        assert result["success"] is False
        assert "not declared" in result["issues"][0]

    def test_undeclared_object_rejected(self, monkeypatch, config, palace_path, kg):
        self._setup(monkeypatch, config, palace_path, kg)

        result = _add_edge("server-a", "depends-on", "unknown-entity")
        assert result["success"] is False
        assert "not declared" in result["issues"][0]

    def test_predicate_used_as_subject_rejected(self, monkeypatch, config, palace_path, kg):
        self._setup(monkeypatch, config, palace_path, kg)

        result = _add_edge("depends-on", "depends-on", "server-b")
        assert result["success"] is False
        assert "predicate" in result["issues"][0].lower()

    def test_non_predicate_used_as_predicate_rejected(self, monkeypatch, config, palace_path, kg):
        self._setup(monkeypatch, config, palace_path, kg)

        result = _add_edge("server-a", "server-b", "server-a")
        assert result["success"] is False
        assert "predicate" in result["issues"][0].lower()

    def test_valid_edge_succeeds(self, monkeypatch, config, palace_path, kg):
        self._setup(monkeypatch, config, palace_path, kg)

        result = _add_edge("server-a", "depends-on", "server-b")
        assert result["success"] is True


# ── Class constraint enforcement ──────────────────────────────────────


class TestClassConstraints:
    def _setup(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        # Classes
        _declare("thing", "Root class", kind="class", importance=5)
        _declare("system", "Infrastructure component", kind="class", importance=4)
        _declare("process", "A workflow or procedure", kind="class", importance=4)
        _declare("rule", "A standing order", kind="class", importance=4)

        # Predicate restricted to system/process subjects
        _declare(
            "runs-in", "Subject runs inside object", kind="predicate", importance=4,
            constraints={
                "subject_kinds": ["entity"],
                "object_kinds": ["entity"],
                "subject_classes": ["system", "process"],
                "object_classes": ["system"],
                "cardinality": "many-to-one",
            },
        )

        # Entities with is-a classification
        _declare("my-server", "A test server", kind="entity")
        kg.add_triple("my_server", "is-a", "system")

        _declare("my-rule", "A test rule", kind="entity")
        kg.add_triple("my_rule", "is-a", "rule")

        _declare("docker-env", "Docker runtime", kind="entity")
        kg.add_triple("docker_env", "is-a", "system")

    def test_class_constraint_pass(self, monkeypatch, config, palace_path, kg):
        """system entity as subject of runs-in should pass (system in allowed)."""
        self._setup(monkeypatch, config, palace_path, kg)

        result = _add_edge("my-server", "runs-in", "docker-env")
        assert result["success"] is True

    def test_class_constraint_fail_wrong_subject(self, monkeypatch, config, palace_path, kg):
        """rule entity as subject of runs-in should fail (rule not in [system, process])."""
        self._setup(monkeypatch, config, palace_path, kg)

        result = _add_edge("my-rule", "runs-in", "docker-env")
        assert result["success"] is False
        assert "constraint_issues" in result
        assert "class mismatch" in result["constraint_issues"][0].lower() or "Subject class" in result["constraint_issues"][0]


# ── Class inheritance ─────────────────────────────────────────────────


class TestClassInheritance:
    def _setup(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        # Class hierarchy: thing -> system -> database
        _declare("thing", "Root class", kind="class", importance=5)
        _declare("system", "Infrastructure component", kind="class", importance=4)
        _declare("database", "A database system", kind="class", importance=3)
        # system is-a thing is auto-added; database is-a thing is auto-added
        # But we need database is-a system explicitly
        kg.add_triple("database", "is-a", "system")

        # Predicate allowing only ["thing"] — should accept anything via inheritance
        _declare(
            "has-property", "Subject has property object", kind="predicate", importance=4,
            constraints={
                "subject_kinds": ["entity"],
                "object_kinds": ["entity", "literal"],
                "subject_classes": ["thing"],
                "object_classes": ["thing"],
                "cardinality": "many-to-many",
            },
        )

        # Predicate allowing only ["system"] — should accept database via inheritance
        _declare(
            "hosted-by", "Subject is hosted by object", kind="predicate", importance=3,
            constraints={
                "subject_kinds": ["entity"],
                "object_kinds": ["entity"],
                "subject_classes": ["system"],
                "object_classes": ["system"],
                "cardinality": "many-to-many",
            },
        )

        # Entity classified as database
        _declare("postgres-db", "PostgreSQL database instance", kind="entity")
        kg.add_triple("postgres_db", "is-a", "database")

        # Entity classified as system
        _declare("docker-host", "Docker container host", kind="entity")
        kg.add_triple("docker_host", "is-a", "system")

        # A literal for property value
        _declare("port-5432", "PostgreSQL default port", kind="literal")

    def test_thing_accepts_any_class(self, monkeypatch, config, palace_path, kg):
        """Predicate with subject_classes=['thing'] should accept any classified entity."""
        self._setup(monkeypatch, config, palace_path, kg)

        result = _add_edge("postgres-db", "has-property", "port-5432")
        assert result["success"] is True

    def test_inherited_class_passes(self, monkeypatch, config, palace_path, kg):
        """database is-a system, so database entity should pass constraint requiring system."""
        self._setup(monkeypatch, config, palace_path, kg)

        result = _add_edge("postgres-db", "hosted-by", "docker-host")
        assert result["success"] is True


# ── Cardinality enforcement ───────────────────────────────────────────


class TestCardinalityEnforcement:
    def _setup(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        # Classes
        _declare("thing", "Root class", kind="class", importance=5)
        _declare("system", "Infrastructure component", kind="class", importance=4)

        # many-to-one predicate
        _declare(
            "runs-in", "Subject runs inside object", kind="predicate", importance=4,
            constraints={
                "subject_kinds": ["entity"],
                "object_kinds": ["entity"],
                "subject_classes": ["thing"],
                "object_classes": ["thing"],
                "cardinality": "many-to-one",
            },
        )

        # many-to-many predicate
        _declare(
            "depends-on", "Subject depends on object", kind="predicate", importance=4,
            constraints={
                "subject_kinds": ["entity"],
                "object_kinds": ["entity"],
                "subject_classes": ["thing"],
                "object_classes": ["thing"],
                "cardinality": "many-to-many",
            },
        )

        _declare("app", "Test application", kind="entity")
        _declare("container-a", "Docker container A", kind="entity")
        _declare("container-b", "Docker container B", kind="entity")
        _declare("lib-x", "Library X", kind="entity")
        _declare("lib-y", "Library Y", kind="entity")

    def test_many_to_one_first_edge_succeeds(self, monkeypatch, config, palace_path, kg):
        self._setup(monkeypatch, config, palace_path, kg)

        result = _add_edge("app", "runs-in", "container-a")
        assert result["success"] is True

    def test_many_to_one_second_edge_blocked(self, monkeypatch, config, palace_path, kg):
        self._setup(monkeypatch, config, palace_path, kg)

        _add_edge("app", "runs-in", "container-a")
        result = _add_edge("app", "runs-in", "container-b")
        assert result["success"] is False
        assert "constraint_issues" in result
        assert "cardinality" in result["constraint_issues"][0].lower()

    def test_many_to_many_multiple_edges_ok(self, monkeypatch, config, palace_path, kg):
        self._setup(monkeypatch, config, palace_path, kg)

        result1 = _add_edge("app", "depends-on", "lib-x")
        result2 = _add_edge("app", "depends-on", "lib-y")
        assert result1["success"] is True
        assert result2["success"] is True


# ── Entity merge ──────────────────────────────────────────────────────


class TestEntityMerge:
    def test_merge_moves_edges(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        # Create two entities with edges
        _declare("thing", "Root class", kind="class", importance=5)
        _declare("old-server", "The old name for the server", kind="entity")
        _declare("new-server", "The canonical server entity", kind="entity")
        _declare("depends-on", "Dependency", kind="predicate", importance=4,
                 constraints={
                     "subject_kinds": ["entity"],
                     "object_kinds": ["entity"],
                     "subject_classes": ["thing"],
                     "object_classes": ["thing"],
                     "cardinality": "many-to-many",
                 })
        _declare("my-db", "A database", kind="entity")

        # Add edge to old entity
        _add_edge("old-server", "depends-on", "my-db")

        # Merge old into new
        from mempalace.mcp_server import tool_kg_merge_entities
        result = tool_kg_merge_entities(source="old-server", target="new-server")
        assert result["success"] is True
        assert result["edges_moved"] >= 1

    def test_merge_updates_declared_set(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)
        from mempalace.mcp_server import _declared_entities

        _declare("source-ent", "Source entity", kind="entity")
        _declare("target-ent", "Target entity", kind="entity")

        assert "source_ent" in _declared_entities
        assert "target_ent" in _declared_entities

        from mempalace.mcp_server import tool_kg_merge_entities
        tool_kg_merge_entities(source="source-ent", target="target-ent")

        assert "source_ent" not in _declared_entities
        assert "target_ent" in _declared_entities


# ── Auto is-a thing for classes ───────────────────────────────────────


class TestAutoIsAThing:
    def test_new_class_gets_is_a_thing(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        _declare("thing", "Root class", kind="class", importance=5)
        _declare("vehicle", "A vehicle class", kind="class", importance=3)

        # Check is-a thing edge was auto-added
        edges = kg.query_entity("vehicle", direction="outgoing")
        is_a_thing = [e for e in edges if e["predicate"] == "is-a" and e["object"] == "thing"]
        assert len(is_a_thing) == 1

    def test_thing_itself_no_self_loop(self, monkeypatch, config, palace_path, kg):
        _patch_mcp(monkeypatch, config, kg, palace_path)

        _declare("thing", "Root class", kind="class", importance=5)

        # thing should NOT have is-a thing (self-loop)
        edges = kg.query_entity("thing", direction="outgoing")
        is_a_self = [e for e in edges if e["predicate"] == "is-a" and e["object"] == "thing"]
        assert len(is_a_self) == 0


# ── Normalization ─────────────────────────────────────────────────────


class TestNormalization:
    def test_underscores_used(self):
        from mempalace.knowledge_graph import normalize_entity_name

        assert normalize_entity_name("my-entity") == "my_entity"
        assert normalize_entity_name("my_entity") == "my_entity"
        assert normalize_entity_name("my entity") == "my_entity"

    def test_camel_case_split(self):
        from mempalace.knowledge_graph import normalize_entity_name

        assert normalize_entity_name("CamelCase") == "camel_case"
        assert normalize_entity_name("XMLParser") == "xml_parser"

    def test_article_stripping(self):
        from mempalace.knowledge_graph import normalize_entity_name

        assert normalize_entity_name("the-big-server") == "big_server"
        assert normalize_entity_name("a-small-tool") == "small_tool"
        assert normalize_entity_name("an-example") == "example"

    def test_collapses_all_separators(self):
        from mempalace.knowledge_graph import normalize_entity_name

        assert normalize_entity_name("foo---bar") == "foo_bar"
        assert normalize_entity_name("foo___bar") == "foo_bar"
        assert normalize_entity_name("foo...bar") == "foo_bar"

    def test_empty_normalizes_to_unknown(self):
        from mempalace.knowledge_graph import normalize_entity_name

        assert normalize_entity_name("---") == "unknown"
        assert normalize_entity_name("") == "unknown"
