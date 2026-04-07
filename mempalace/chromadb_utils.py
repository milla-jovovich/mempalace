"""
Utilities for safe ChromaDB collection reads.

ChromaDB's ``col.get()`` without an explicit ``limit`` applies a small
internal default that silently truncates results on large palaces.
Even with a limit, very large values can exceed SQLite's ~999 variable
cap.  The helper below reads in batches so every caller gets complete
results regardless of palace size.
"""

_BATCH_SIZE = 5000


def get_all(col, *, include=None, where=None, batch_size=_BATCH_SIZE):
    """Read **all** records from a ChromaDB collection in safe batches.

    Args:
        col: A ChromaDB collection object.
        include: List of fields to include (e.g. ``["metadatas"]``).
        where: Optional ChromaDB ``where`` filter dict.
        batch_size: Records per batch (default 5 000).

    Returns:
        A merged result dict with the same shape as ``col.get()``
        (keys: ``ids``, and whichever extras were requested via *include*).
    """
    total = col.count()
    if total == 0:
        result = {"ids": []}
        for field in include or []:
            result[field] = []
        return result

    all_ids = []
    all_fields = {field: [] for field in (include or [])}

    offset = 0
    while offset < total:
        kwargs = {"limit": batch_size, "offset": offset, "include": include or []}
        if where:
            kwargs["where"] = where
        batch = col.get(**kwargs)

        all_ids.extend(batch["ids"])
        for field in include or []:
            all_fields[field].extend(batch.get(field, []))

        # Guard against empty batches (e.g. filtered where returns nothing)
        if not batch["ids"]:
            break
        offset += len(batch["ids"])

    result = {"ids": all_ids}
    result.update(all_fields)
    return result
