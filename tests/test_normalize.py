import os
import json
import tempfile
from mempalace.normalize import normalize


def test_plain_text():
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    f.write("Hello world\nSecond line\n")
    f.close()
    result = normalize(f.name)
    assert "Hello world" in result
    os.unlink(f.name)


def test_claude_json():
    data = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    result = normalize(f.name)
    assert "Hi" in result
    os.unlink(f.name)


def test_empty():
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    f.close()
    result = normalize(f.name)
    assert result.strip() == ""
    os.unlink(f.name)


def test_gemini_contents_format():
    """Gemini API 'contents' format used by Gemini CLI session files."""
    data = {
        "contents": [
            {"role": "user", "parts": [{"text": "What is the capital of France?"}]},
            {"role": "model", "parts": [{"text": "The capital of France is Paris."}]},
            {"role": "user", "parts": [{"text": "And Germany?"}]},
            {"role": "model", "parts": [{"text": "The capital of Germany is Berlin."}]},
        ]
    }
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    result = normalize(f.name)
    assert "> What is the capital of France?" in result
    assert "The capital of France is Paris." in result
    assert "> And Germany?" in result
    assert "The capital of Germany is Berlin." in result
    os.unlink(f.name)


def test_gemini_flat_messages_format():
    """Flat messages list with role='model' (Gemini convention)."""
    data = [
        {"role": "user", "content": "Explain recursion"},
        {"role": "model", "content": "Recursion is when a function calls itself."},
    ]
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    result = normalize(f.name)
    assert "> Explain recursion" in result
    assert "Recursion is when a function calls itself." in result
    os.unlink(f.name)


def test_gemini_multi_part_text():
    """Parts list with multiple text entries should be joined."""
    data = {
        "contents": [
            {"role": "user", "parts": [{"text": "Part one."}, {"text": "Part two."}]},
            {"role": "model", "parts": [{"text": "Got it."}]},
        ]
    }
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    result = normalize(f.name)
    assert "> Part one. Part two." in result
    assert "Got it." in result
    os.unlink(f.name)


def test_gemini_skips_non_text_parts():
    """Non-text parts (e.g. inline_data for images) should be skipped gracefully."""
    data = {
        "contents": [
            {"role": "user", "parts": [{"text": "Describe this"}, {"inline_data": {"mime_type": "image/png"}}]},
            {"role": "model", "parts": [{"text": "I see a cat."}]},
        ]
    }
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    result = normalize(f.name)
    assert "> Describe this" in result
    assert "I see a cat." in result
    os.unlink(f.name)


def test_gemini_single_message_returns_none():
    """A single message is not enough for a conversation."""
    data = {"contents": [{"role": "user", "parts": [{"text": "Hello"}]}]}
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    result = normalize(f.name)
    # Should fall through to plain text since Gemini parser returns None
    assert "Hello" in result
    os.unlink(f.name)
