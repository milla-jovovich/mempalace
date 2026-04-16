import pytest
from mempalace.cli import main
from mempalace.dream.reextract import JobAResult


def _fake_result(version="v1.0"):
    return JobAResult(
        job="A", version=version, started_at="now",
        elapsed_secs=0.1, drawers_processed=0, drawers_skipped=0,
        triples_inserted=0, triples_updated=0, qwen_failures=0,
        batches=0,
    )


def test_walker_extract_help(capsys):
    with pytest.raises(SystemExit):
        main(["walker", "extract", "--help"])
    out = capsys.readouterr().out
    for flag in ("--wing", "--concurrency", "--version", "--dry-run", "--qwen-url"):
        assert flag in out


def test_walker_extract_dispatches(monkeypatch, capsys):
    captured = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return _fake_result(version=kwargs.get("version", "v1.0"))

    monkeypatch.setattr("mempalace.dream.reextract.run_job_a", fake_run)
    rc = main([
        "--palace", "/tmp/p",
        "walker", "extract",
        "--version", "v1.5",
        "--wing", "mywing",
        "--qwen-url", "http://example:1234",
    ])
    assert rc == 0
    assert captured["version"] == "v1.5"
    assert captured["wing"] == "mywing"
    assert captured["qwen_url"] == "http://example:1234"
    assert captured["palace_path"] == "/tmp/p"
    assert "Extracted" in capsys.readouterr().out


def test_walker_extract_dry_run_propagates(monkeypatch):
    captured = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr("mempalace.dream.reextract.run_job_a", fake_run)
    main(["walker", "extract", "--dry-run"])
    assert captured["dry_run"] is True


def test_walker_extract_preflight_error_friendly(monkeypatch, capsys):
    async def boom(**kwargs):
        raise RuntimeError("Qwen endpoint http://localhost:43100 unreachable")

    monkeypatch.setattr("mempalace.dream.reextract.run_job_a", boom)
    rc = main(["walker", "extract"])
    assert rc != 0
    out = capsys.readouterr().out
    assert "unreachable" in out or "Qwen" in out


def test_dream_cycle_help(capsys):
    with pytest.raises(SystemExit):
        main(["dream-cycle", "--help"])
    out = capsys.readouterr().out
    for flag in ("--jobs", "--wing", "--dry-run"):
        assert flag in out


def test_dream_cycle_jobs_a(monkeypatch):
    captured = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr("mempalace.dream.reextract.run_job_a", fake_run)
    rc = main(["dream-cycle", "--jobs", "A", "--wing", "mywing", "--dry-run"])
    assert rc == 0
    assert captured["wing"] == "mywing"
    assert captured["dry_run"] is True


def test_dream_cycle_unsupported_jobs(capsys):
    rc = main(["dream-cycle", "--jobs", "B"])
    assert rc == 2
    assert "Phase 1" in capsys.readouterr().out
