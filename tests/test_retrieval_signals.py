"""Coverage for mined retrieval hints shared by miners and search strategies."""

from mempalace import retrieval_signals


def test_split_dialogue_content_handles_plain_docs_and_transcripts():
    plain_user, plain_assistant = retrieval_signals._split_dialogue_content(
        "Project notes about migrations and release safety."
    )
    assert plain_user == "Project notes about migrations and release safety."
    assert plain_assistant == ""

    convo_user, convo_assistant = retrieval_signals._split_dialogue_content(
        "> I prefer long battery life\n\n---\nYou might want to compare MacBook Air and XPS.",
        ingest_mode="convos",
    )
    assert convo_user == "I prefer long battery life"
    assert "compare MacBook Air" in convo_assistant


def test_infer_ingest_mode_prefers_metadata_then_falls_back_to_legacy_hints():
    assert retrieval_signals.infer_ingest_mode("Plain note", {"ingest_mode": "projects"}) == "project"
    assert retrieval_signals.infer_ingest_mode("Plain note", {"ingest_mode": "conversation"}) == "convos"
    assert retrieval_signals.infer_ingest_mode("Plain note", {"extract_mode": "exchange"}) == "convos"
    assert retrieval_signals.infer_ingest_mode("> user line\nassistant reply") == "convos"
    assert retrieval_signals.infer_ingest_mode("Design note without transcript markers") == "project"


def test_extract_preference_signals_deduplicates_and_support_doc_none_path():
    signals = retrieval_signals.extract_preference_signals(
        "I prefer electric cars. I prefer electric cars. Recently, I've been working on home automation.",
    )
    assert signals == ["electric cars", "working on home automation"]
    assert retrieval_signals.build_preference_support_document("Plain technical note.") is None


def test_extract_preference_signals_handles_tuple_matches(monkeypatch):
    monkeypatch.setattr(retrieval_signals, "_PREFERENCE_PATTERNS", [r"(battery) (life)"])

    signals = retrieval_signals.extract_preference_signals(
        "Battery life matters more than raw speed for this laptop."
    )

    assert signals == ["battery life"]


def test_build_preference_support_document_returns_embedding_friendly_text():
    doc = retrieval_signals.build_preference_support_document(
        "I've been struggling with battery life on my laptop lately."
    )
    assert doc == {
        "text": "User has mentioned: battery life on my laptop lately",
        "signals": ["battery life on my laptop lately"],
    }


def test_classify_document_hall_covers_preference_assistant_event_fact_and_general():
    assert (
        retrieval_signals.classify_document_hall("I prefer tea over coffee.")
        == retrieval_signals.HALL_PREFERENCES
    )
    assert (
        retrieval_signals.classify_document_hall(
            "> Need options\nI suggest three approaches.\nOption 1 is safest.\nFirst, back up data.",
            ingest_mode="convos",
        )
        == retrieval_signals.HALL_ASSISTANT
    )
    assert (
        retrieval_signals.classify_document_hall("We celebrated a graduation milestone and birthday party.")
        == retrieval_signals.HALL_EVENTS
    )
    assert (
        retrieval_signals.classify_document_hall(
            "I studied at university, my degree is physics, and I work at a robotics company."
        )
        == retrieval_signals.HALL_FACTS
    )
    assert (
        retrieval_signals.classify_document_hall("A short neutral implementation note.")
        == retrieval_signals.HALL_GENERAL
    )


def test_classify_question_halls_and_assistant_reference_detection():
    assert retrieval_signals.classify_question_halls("What did you suggest for login flow?") == [
        retrieval_signals.HALL_ASSISTANT,
        retrieval_signals.HALL_GENERAL,
    ]
    assert retrieval_signals.classify_question_halls(
        "What battery issues have I mentioned lately?"
    ) == [retrieval_signals.HALL_PREFERENCES, retrieval_signals.HALL_GENERAL]
    assert retrieval_signals.classify_question_halls("What happened last month?") == [
        retrieval_signals.HALL_EVENTS,
        retrieval_signals.HALL_FACTS,
        retrieval_signals.HALL_GENERAL,
    ]
    assert retrieval_signals.classify_question_halls("What degree did I study?") == [
        retrieval_signals.HALL_FACTS,
        retrieval_signals.HALL_GENERAL,
    ]
    assert retrieval_signals.classify_question_halls("Find the deployment checklist") == [
        retrieval_signals.HALL_GENERAL
    ]
    assert retrieval_signals.is_assistant_reference_query("Remind me what you recommended") is True
    assert retrieval_signals.is_assistant_reference_query("Find the deployment checklist") is False
