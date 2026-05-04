"""Regression tests for SKIP_DIRS — make sure tooling/plugin config
trees (.obsidian/plugins, .terraform, vendor) never get mined as user
content.

Background: a real Obsidian vault audit found 26,320 drawers in
`wing=obsidian / room=operations` were `.obsidian/plugins/<plugin>/main.js`
JavaScript source. The vault had ~9 real markdown files. The mine walk
was not filtering `.obsidian/`. Adding it to palace.SKIP_DIRS (the
canonical set imported by miner.py and convo_miner.py) fixes the
file-walk path. The other modules (project_scanner, entity_detector,
room_detector_local) have their own sets — fixed in parallel for
consistency. Closes #1329.
"""

from __future__ import annotations

from pathlib import Path

from mempalace import entity_detector, palace, project_scanner
from mempalace.miner import scan_project


def _make_obsidian_fixture(root: Path) -> None:
    """Build a tiny Obsidian-shaped tree:
    <root>/Notes/index.md     <- legitimate user content
    <root>/.obsidian/plugins/excalidraw/main.js   <- bundled JS noise
    <root>/.obsidian/themes/Minimal/theme.css     <- bundled CSS noise
    """
    notes = root / "Notes"
    notes.mkdir(parents=True)
    (notes / "index.md").write_text("# Notes\n\nReal content.\n")

    plugin = root / ".obsidian" / "plugins" / "excalidraw"
    plugin.mkdir(parents=True)
    (plugin / "main.js").write_text("// 11k lines of bundled excalidraw JS pretend\n" * 100)

    theme = root / ".obsidian" / "themes" / "Minimal"
    theme.mkdir(parents=True)
    (theme / "theme.css").write_text("/* minimal theme */\n")


class TestPalaceSkipDirs:
    def test_obsidian_in_palace_skip_dirs(self):
        assert ".obsidian" in palace.SKIP_DIRS

    def test_terraform_in_palace_skip_dirs(self):
        assert ".terraform" in palace.SKIP_DIRS

    def test_vendor_in_palace_skip_dirs(self):
        assert "vendor" in palace.SKIP_DIRS


class TestProjectScannerSkipDirs:
    def test_obsidian_in_project_scanner_skip_dirs(self):
        assert ".obsidian" in project_scanner.SKIP_DIRS


class TestEntityDetectorSkipDirs:
    def test_obsidian_in_entity_detector_skip_dirs(self):
        assert ".obsidian" in entity_detector.SKIP_DIRS


class TestScanProjectHonorsObsidianSkip:
    """End-to-end: the file-walk that runs during `mempalace mine` must
    not yield files under .obsidian/. miner.scan_project is the canonical
    entry point; SKIP_DIRS is imported from palace.py."""

    def test_scan_project_skips_obsidian_plugins(self, tmp_path):
        _make_obsidian_fixture(tmp_path)

        files = list(scan_project(str(tmp_path)))
        rel_paths = {str(Path(f).relative_to(tmp_path)) for f in files}

        # Real content present
        assert "Notes/index.md" in rel_paths

        # No .obsidian/* under any path
        leaked = [p for p in rel_paths if ".obsidian" in p]
        assert leaked == [], (
            f"scan_project leaked .obsidian/ paths into mine corpus: {leaked}. "
            "SKIP_DIRS in palace.py must include '.obsidian'."
        )
