"""
test_fact_checker.py — Tests for rule-based contradiction detection.

Covers: attribution conflicts, tenure mismatches, role conflicts,
relationship conflicts, no-conflict cases, unknown entities,
and expired fact handling.
"""

from mempalace.fact_checker import check_assertion


# ── Attribution conflicts ────────────────────────────────────────────


class TestAttributionConflicts:
    def test_detects_wrong_person(self, kg):
        """If KG says Maya is assigned to auth migration, claiming Soren did it is RED."""
        kg.add_entity("Maya", entity_type="person")
        kg.add_entity("auth migration", entity_type="project")
        kg.add_triple("Maya", "assigned_to", "auth migration")

        result = check_assertion("Soren finished the auth migration", kg)
        assert result.severity == "RED"
        assert len(result.conflicts) >= 1
        assert result.conflicts[0].field == "attribution"
        assert "Maya" in result.conflicts[0].message

    def test_correct_attribution_is_green(self, kg):
        """If KG says Maya is assigned and we claim Maya did it — no conflict."""
        kg.add_entity("Maya", entity_type="person")
        kg.add_entity("auth migration", entity_type="project")
        kg.add_triple("Maya", "assigned_to", "auth migration")

        result = check_assertion("Maya finished the auth migration", kg)
        assert result.severity == "GREEN"
        assert len(result.conflicts) == 0

    def test_no_kg_data_is_green(self, kg):
        """If KG has no info about the task, no conflict can be detected."""
        result = check_assertion("Soren finished the auth migration", kg)
        assert result.severity == "GREEN"


# ── Tenure mismatches ────────────────────────────────────────────────


class TestTenureMismatches:
    def test_detects_wrong_tenure(self, kg):
        """If KG shows Kai started in 2020, claiming 2 years is wrong in 2026."""
        kg.add_entity("Kai", entity_type="person")
        kg.add_entity("Acme Corp", entity_type="company")
        kg.add_triple("Kai", "works_at", "Acme Corp", valid_from="2020-03-01")

        result = check_assertion("Kai has been here 2 years", kg)
        assert result.severity == "YELLOW"
        assert len(result.conflicts) >= 1
        assert result.conflicts[0].field == "tenure"
        assert "2020" in result.conflicts[0].message

    def test_correct_tenure_is_green(self, kg):
        """If KG start date matches the claimed tenure, no conflict."""
        current_year = 2026  # test assumes current year
        start_year = current_year - 3
        kg.add_entity("Kai", entity_type="person")
        kg.add_entity("Acme Corp", entity_type="company")
        kg.add_triple("Kai", "works_at", "Acme Corp", valid_from=f"{start_year}-01-01")

        # Claiming ~3 years should be close enough (within 1 year tolerance)
        result = check_assertion("Kai has been here 3 years", kg)
        assert result.severity == "GREEN"

    def test_no_start_date_is_green(self, kg):
        """If KG has the employment but no start date, can't check tenure."""
        kg.add_entity("Kai", entity_type="person")
        kg.add_entity("Acme Corp", entity_type="company")
        kg.add_triple("Kai", "works_at", "Acme Corp")

        result = check_assertion("Kai has been here 5 years", kg)
        assert result.severity == "GREEN"


# ── Role conflicts ───────────────────────────────────────────────────


class TestRoleConflicts:
    def test_detects_wrong_role(self, kg):
        """If KG says Alice is an engineer, claiming she's a designer is RED."""
        kg.add_entity("Alice", entity_type="person")
        kg.add_entity("engineer", entity_type="role")
        kg.add_triple("Alice", "has_role", "engineer")

        result = check_assertion("Alice is a designer at the company", kg)
        assert result.severity == "RED"
        assert result.conflicts[0].field == "role"

    def test_correct_role_is_green(self, kg):
        """If KG says Alice is an engineer and we claim the same — green."""
        kg.add_entity("Alice", entity_type="person")
        kg.add_entity("engineer", entity_type="role")
        kg.add_triple("Alice", "has_role", "engineer")

        result = check_assertion("Alice is an engineer at the company", kg)
        assert result.severity == "GREEN"

    def test_partial_role_match_is_green(self, kg):
        """If KG says 'senior engineer' and claim says 'engineer' — no conflict."""
        kg.add_entity("Alice", entity_type="person")
        kg.add_entity("senior engineer", entity_type="role")
        kg.add_triple("Alice", "has_role", "senior engineer")

        result = check_assertion("Alice is an engineer at the company", kg)
        assert result.severity == "GREEN"


# ── Relationship conflicts ───────────────────────────────────────────


class TestRelationshipConflicts:
    def test_detects_wrong_relationship(self, seeded_kg):
        """seeded_kg has Alice parent_of Max. Claiming Max is Alice's partner is RED."""
        result = check_assertion("Max is Alice's partner", seeded_kg)
        assert result.severity == "RED"
        assert result.conflicts[0].field == "relationship"

    def test_correct_relationship_is_green(self, seeded_kg):
        """seeded_kg has Alice parent_of Max. Claiming Max is Alice's child is green."""
        result = check_assertion("Max is Alice's child", seeded_kg)
        assert result.severity == "GREEN"

    def test_no_relationship_data_is_green(self, kg):
        """If KG has no relationship between two people, no conflict."""
        kg.add_entity("Zara", entity_type="person")
        kg.add_entity("Liam", entity_type="person")

        result = check_assertion("Zara is Liam's sister", kg)
        assert result.severity == "GREEN"


# ── Expired facts ────────────────────────────────────────────────────


class TestExpiredFacts:
    def test_expired_attribution_not_flagged(self, kg):
        """Expired KG facts should not trigger conflicts."""
        kg.add_entity("Maya", entity_type="person")
        kg.add_entity("auth migration", entity_type="project")
        kg.add_triple(
            "Maya", "assigned_to", "auth migration",
            valid_from="2025-01-01", valid_to="2025-06-01",
        )

        result = check_assertion("Soren finished the auth migration", kg)
        assert result.severity == "GREEN"

    def test_expired_employment_not_flagged(self, seeded_kg):
        """Alice's old job at Acme Corp (ended 2024-12-31) shouldn't conflict."""
        # seeded_kg has: Alice works_at Acme Corp (valid_to=2024-12-31)
        #                Alice works_at NewCo (current)
        result = check_assertion("Alice has been here 1 years", seeded_kg)
        # Should only check current employment (NewCo, started 2025-01-01)
        # 2026 - 2025 = 1 year, claimed 1 year → GREEN
        assert result.severity == "GREEN"


# ── Result structure ─────────────────────────────────────────────────


class TestCheckResultStructure:
    def test_to_dict(self, kg):
        result = check_assertion("Hello world", kg)
        d = result.to_dict()
        assert "severity" in d
        assert "text" in d
        assert "conflicts" in d
        assert "entities_checked" in d
        assert isinstance(d["conflicts"], list)

    def test_entities_extracted(self, kg):
        result = check_assertion("Alice told Bob about the new plan", kg)
        assert "Alice" in result.entities_checked
        assert "Bob" in result.entities_checked

    def test_empty_text(self, kg):
        result = check_assertion("", kg)
        assert result.severity == "GREEN"
        assert len(result.conflicts) == 0


# ── MCP integration ──────────────────────────────────────────────────


class TestMcpIntegration:
    def test_tool_check_facts_returns_dict(self, kg):
        """Verify the result format matches what MCP tools expect."""
        kg.add_entity("Maya", entity_type="person")
        kg.add_triple("Maya", "assigned_to", "auth migration")

        result = check_assertion("Soren finished the auth migration", kg)
        d = result.to_dict()

        assert d["severity"] == "RED"
        assert len(d["conflicts"]) >= 1
        conflict = d["conflicts"][0]
        assert "severity" in conflict
        assert "entity" in conflict
        assert "field" in conflict
        assert "message" in conflict
