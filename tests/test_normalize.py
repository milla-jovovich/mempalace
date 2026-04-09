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


def test_aider_md():
    content = """#### How do I add a new route?

You can add a new route by creating a file in the `routes/` directory.

#### Can you also add tests for it?

Sure, here's a test file.
"""
    # Must use Aider's exact filename to trigger the parser
    path = os.path.join(tempfile.gettempdir(), ".aider.chat.history.md")
    with open(path, "w") as f:
        f.write(content)
    result = normalize(path)
    assert "How do I add a new route?" in result
    assert "You can add a new route" in result
    assert "Can you also add tests for it?" in result
    assert "Sure, here's a test file." in result
    os.unlink(path)


def test_aider_rejects_generic_md():
    """Regular markdown with #### headings should NOT trigger the Aider parser."""
    content = """#### Installation

Run pip install mempalace.

#### Usage

Import and call normalize().
"""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
    f.write(content)
    f.close()
    result = normalize(f.name)
    # Should return raw content, not normalized as chat
    assert result == content
    os.unlink(f.name)
