from mempalace.general_extractor import extract_memories


def test_empty_text_returns_empty_list():
    assert extract_memories("") == []


def test_short_paragraph_is_filtered_out():
    # Segments shorter than 20 chars are dropped even when they match markers.
    assert extract_memories("we decided") == []


def test_extracts_a_decision():
    text = (
        "We debated for a while, but we decided to go with Postgres instead of "
        "MySQL because the JSONB support and the replication story are a much "
        "better fit for the analytics workload we have in front of us."
    )
    memories = extract_memories(text)
    assert len(memories) == 1
    assert memories[0]["memory_type"] == "decision"
    assert "Postgres" in memories[0]["content"]
    assert memories[0]["chunk_index"] == 0


def test_extracts_a_preference():
    text = (
        "Quick style note for future work on this module: I prefer snake_case "
        "for all identifiers, and we always use explicit imports. Please never "
        "use wildcard imports here, it makes the diffs impossible to review."
    )
    memories = extract_memories(text)
    assert len(memories) == 1
    assert memories[0]["memory_type"] == "preference"


def test_extracts_a_milestone():
    text = (
        "After two days of fighting the build, it finally works end to end. "
        "We shipped v1.0 of the sync pipeline, the integration tests turned "
        "green, and I can reproduce the happy path on a clean machine."
    )
    memories = extract_memories(text)
    assert len(memories) == 1
    assert memories[0]["memory_type"] == "milestone"


def test_extracts_a_problem():
    text = (
        "The worker keeps crashing on startup and the logs are not useful. "
        "The problem is a bug in the retry loop, it won't work when the "
        "upstream service is slow. Everything is stuck and we have no "
        "workaround ready yet."
    )
    memories = extract_memories(text)
    assert len(memories) == 1
    assert memories[0]["memory_type"] == "problem"


def test_extracts_an_emotional_memory():
    text = (
        "I'm scared that I am burning out on this project and I miss the "
        "days when the code felt fun. I love what we built together but "
        "lately I feel stretched too thin and I am not sure how to ask "
        "for help without letting the team down."
    )
    memories = extract_memories(text)
    assert len(memories) == 1
    assert memories[0]["memory_type"] == "emotional"


def test_skips_fenced_code_blocks_when_prose_has_no_markers():
    # _extract_prose strips fenced blocks, so the only signal left comes
    # from the surrounding prose. That's a single match at best, which
    # lands below the default 0.3 confidence threshold and gets filtered
    # out, even though the fenced block is full of decision-ish words.
    text = (
        "Just pasting this snippet for reference, nothing to call out.\n\n"
        "```python\n"
        "def choose_backend():\n"
        "    return 'postgres'  # we decided to go with postgres\n"
        "```\n\n"
        "That's all, moving on to the next review item now."
    )
    memories = extract_memories(text)
    # Whatever is returned should not pick up the fenced block as a decision.
    for m in memories:
        assert "we decided to go with postgres" not in m["content"].lower()


def test_multiple_paragraphs_produce_sequential_chunk_indices():
    text = (
        "After a long debugging session we finally shipped v2.0 and it works. "
        "The integration tests turned green for the first time this week.\n\n"
        "The pipeline kept failing because of a bug in the retry loop. "
        "The fix was to add exponential backoff with jitter to the retries."
    )
    memories = extract_memories(text)
    assert len(memories) >= 2
    indices = [m["chunk_index"] for m in memories]
    assert indices == list(range(len(memories)))


def test_min_confidence_threshold_filters_weak_matches():
    text = (
        "We set a small default for the cache timeout on the staging "
        "environment to avoid blowing up the request budget during reviews."
    )
    permissive = extract_memories(text, min_confidence=0.1)
    strict = extract_memories(text, min_confidence=0.95)
    assert len(strict) <= len(permissive)


def test_speaker_turns_become_separate_segments():
    # _split_into_segments switches to turn-based splitting only when it
    # sees at least 3 speaker markers; below that it falls back to
    # paragraph-based splitting. Three turns here exercise the real
    # turn-splitter path.
    text = (
        "Human: Can we unpack what happened during yesterday's outage and "
        "why the worker keeps crashing? I'd like to write this one up.\n\n"
        "Assistant: Sure. The retry loop was piling up requests once the "
        "upstream service slowed down, which eventually exhausted the pool "
        "and knocked the worker over.\n\n"
        "Human: Right. The fix was to add a jittered exponential backoff "
        "so the retries do not stack. Finally got it working cleanly."
    )
    memories = extract_memories(text)
    assert len(memories) >= 1
    # At least one of the three turns should classify as a problem or a
    # milestone given the wording.
    types = {m["memory_type"] for m in memories}
    assert types & {"problem", "milestone"}


def test_memory_dict_has_expected_keys():
    text = (
        "We decided to go with Postgres because the JSONB support matches "
        "the analytics workload much better than the MySQL alternative."
    )
    memories = extract_memories(text)
    assert memories
    for m in memories:
        assert set(m.keys()) == {"content", "memory_type", "chunk_index"}
        assert isinstance(m["content"], str)
        assert isinstance(m["memory_type"], str)
        assert isinstance(m["chunk_index"], int)
