# Contradiction Detection

::: info Integrated
Contradiction detection is built into `knowledge_graph.py`'s `add_triple()` method. Every triple insertion checks for conflicting open triples automatically.
:::

## What It Does

When a new triple is added, `add_triple()` checks for existing open triples with the same subject and predicate but a different object. If a conflict is found, a contradiction warning is returned alongside the new triple ID.

```python
from mempalace.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()
kg.add_triple("Kai", "works_at", "Acme")

# Later, a conflicting fact:
result = kg.add_triple("Kai", "works_at", "NewCo")
# result == {
#   "triple_id": "t_kai_works_at_newco_...",
#   "contradiction": {
#     "subject": "Kai",
#     "predicate": "works_at",
#     "existing_object": "Acme",
#     "new_object": "NewCo",
#     "invalidated": False
#   }
# }
```

## Auto-Invalidation

Pass `auto_invalidate=True` to automatically close the old conflicting triple when a contradiction is detected:

```python
result = kg.add_triple("Kai", "works_at", "NewCo", auto_invalidate=True)
# The old "Kai works_at Acme" triple is now closed (valid_to set)
# result["contradiction"]["invalidated"] == True
```

## How It Works

- **Same subject + predicate, different object** triggers a contradiction warning
- **Exact duplicate triples** (same subject, predicate, and object) are deduplicated — no warning
- **Different subjects** with the same predicate are independent — no conflict
- The check only considers open triples (where `valid_to IS NULL`)

## Scope

Contradiction detection operates at the triple level. It catches cases like:
- Two different employers for the same person (`works_at`)
- Two different assignees for the same role (`assigned_to`)
- Conflicting status values (`status_is`)

It does not perform semantic reasoning (e.g., inferring that "married_to Bob" and "single" are contradictory across different predicates).
