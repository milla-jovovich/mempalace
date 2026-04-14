#!/usr/bin/env python3
"""Example: mine a project folder into the palace.

See examples/quickstart.md for a full walkthrough and bundled demo_project.
"""

import sys

project_dir = sys.argv[1] if len(sys.argv) > 1 else "~/projects/my_app"
print("Step 1: Initialize rooms from folder structure")
print(f"  mempalace init {project_dir}")
print("\nStep 2: Mine everything")
print(f"  mempalace mine {project_dir}")
print("\nStep 3: Search")
print("  mempalace search 'why did we choose this approach'")
print("\nOr try the ready-made demo + script:")
print("  python examples/quickstart_demo.py --isolated")
