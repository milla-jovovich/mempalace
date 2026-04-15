"""TDD: save hook must actually mine conversations without MEMPAL_DIR.

The save hook should auto-discover the conversation transcript and mine it
without the user needing to set MEMPAL_DIR. Currently MEMPAL_DIR defaults
to empty, which means the mining block is skipped and nothing is saved
despite the hook telling the agent "saved in background."

Written BEFORE the fix.
"""

import os


class TestSaveHookAutoMines:
    """The save hook must mine the active transcript automatically."""

    def test_hook_mines_transcript_path(self):
        """The hook receives TRANSCRIPT_PATH from Claude Code.
        It should use that to mine the conversation, not depend on MEMPAL_DIR."""
        hook_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "hooks",
            "mempal_save_hook.sh",
        )
        src = open(hook_path).read()

        # The hook ALREADY receives TRANSCRIPT_PATH in the JSON input.
        # It should use this to mine the current session's transcript
        # regardless of whether MEMPAL_DIR is set.
        # The hook must have a path that uses TRANSCRIPT_PATH to determine
        # what to mine, separate from the MEMPAL_DIR path.
        uses_transcript = "TRANSCRIPT_PATH" in src
        has_mine = "mempalace mine" in src
        # TRANSCRIPT_PATH must appear in the mining logic, not just the parse block
        transcript_drives_mine = "MINE_DIR" in src and "dirname" in src and "TRANSCRIPT_PATH" in src

        assert uses_transcript and has_mine and transcript_drives_mine, (
            "Save hook only mines when MEMPAL_DIR is set (defaults to empty). "
            "The hook receives TRANSCRIPT_PATH from Claude Code — it should "
            "mine that file automatically so conversations are saved without "
            "the user setting an env var. Currently the hook says 'saved in "
            "background' but nothing actually saves."
        )

    def test_mempal_dir_default_not_empty(self):
        """If MEMPAL_DIR is still used, it should have a sensible default,
        not an empty string that silently disables mining."""
        hook_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "hooks",
            "mempal_save_hook.sh",
        )
        src = open(hook_path).read()

        # Check if MEMPAL_DIR defaults to empty
        has_empty_default = 'MEMPAL_DIR=""' in src

        # If it defaults to empty, mining is silently disabled
        if has_empty_default:
            # There must be an alternative mining path that doesn't need MEMPAL_DIR
            has_alternative = (
                src.count("mempalace mine") > 1
                or "TRANSCRIPT_PATH" in src.split("mempalace mine")[0]
            )
            assert has_alternative, (
                'MEMPAL_DIR defaults to "" which silently disables mining. '
                "Either set a default path or add transcript-based mining."
            )
