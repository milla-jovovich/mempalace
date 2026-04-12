import os
import sys


def is_valid_palace_dir(path):
    """Check if the path exists, is a directory, and contains a ChromaDB database.

    Guards against symlinks and normalizes paths to prevent unsafe deletions.
    """
    if not path:
        return False

    path = os.path.abspath(os.path.expanduser(path))

    if not os.path.isdir(path):
        return False

    if os.path.islink(path):
        # Prevent following symlinks for deletion
        return False

    return os.path.exists(os.path.join(path, "chroma.sqlite3"))


def confirm_deletion(path):
    """Prompt the user for confirmation before deleting a directory.

    Normalizes path and skips confirmation in non-interactive environments.
    """
    if not path:
        return False

    path = os.path.abspath(os.path.expanduser(path))

    if not sys.stdin.isatty():
        return True

    confirm = input(f"Are you sure you want to delete {path}? (yes/no): ")
    if confirm.lower() != "yes":
        print("Aborted by user.")
        return False

    return True
