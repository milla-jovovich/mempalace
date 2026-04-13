#!/usr/bin/env python3
"""
onboarding.py — MemPalace first-run setup.

Asks the user:
  1. How they're using MemPalace (work / personal / combo)
  2. Who the people in their life are (names, nicknames, relationships)
  3. What their projects are
  4. What they want their wings called

Seeds the entity_registry with confirmed data so MemPalace knows your world
from minute one — before a single session is indexed.

Usage:
    python3 -m mempalace.onboarding
    or: mempalace init
"""

import json
from pathlib import Path

from mempalace.agents import ensure_default_agents
from mempalace.config import MempalaceConfig
from mempalace.entity_registry import EntityRegistry
from mempalace.entity_detector import detect_entities, scan_for_detection


# ─────────────────────────────────────────────────────────────────────────────
# Default wing taxonomies by mode
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_WINGS = {
    "work": [
        "projects",
        "clients",
        "team",
        "decisions",
        "research",
    ],
    "personal": [
        "family",
        "health",
        "creative",
        "reflections",
        "relationships",
    ],
    "combo": [
        "family",
        "work",
        "health",
        "creative",
        "projects",
        "reflections",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _hr():
    print(f"\n{'─' * 58}")


def _header(text):
    print(f"\n{'=' * 58}")
    print(f"  {text}")
    print(f"{'=' * 58}")


def _ask(prompt, default=None):
    if default:
        val = input(f"  {prompt} [{default}]: ").strip()
        return val if val else default
    return input(f"  {prompt}: ").strip()


def _yn(prompt, default="y"):
    val = input(f"  {prompt} [{'Y/n' if default == 'y' else 'y/N'}]: ").strip().lower()
    if not val:
        return default == "y"
    return val.startswith("y")


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Mode selection
# ─────────────────────────────────────────────────────────────────────────────


def _ask_mode() -> str:
    _header("Welcome to MemPalace")
    print("""
  MemPalace is a personal memory system. To work well, it needs to know
  a little about your world — who the people are, what the projects
  are, and how you want your memory organized.

  This takes about 2 minutes. You can always update it later.
""")
    print("  How are you using MemPalace?")
    print()
    print("    [1]  Work     — notes, projects, clients, colleagues, decisions")
    print("    [2]  Personal — diary, family, health, relationships, reflections")
    print("    [3]  Both     — personal and professional mixed")
    print()

    while True:
        choice = input("  Your choice [1/2/3]: ").strip()
        if choice == "1":
            return "work"
        elif choice == "2":
            return "personal"
        elif choice == "3":
            return "combo"
        print("  Please enter 1, 2, or 3.")


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: People
# ─────────────────────────────────────────────────────────────────────────────


def _ask_people(mode: str) -> tuple[list, dict]:
    """Returns (people_list, aliases_dict)."""
    people = []
    aliases = {}  # nickname → full name

    if mode in ("personal", "combo"):
        _hr()
        print("""
  Personal world — who are the important people in your life?

  Format: name, relationship (e.g. "Riley, daughter" or just "Devon")
  For nicknames, you'll be asked separately.
  Type 'done' when finished.
""")
        while True:
            entry = input("  Person: ").strip()
            if entry.lower() in ("done", ""):
                break
            parts = [p.strip() for p in entry.split(",", 1)]
            name = parts[0]
            relationship = parts[1] if len(parts) > 1 else ""
            if name:
                # Ask about nicknames
                nick = input(f"  Nickname for {name}? (or enter to skip): ").strip()
                if nick:
                    aliases[nick] = name
                people.append({"name": name, "relationship": relationship, "context": "personal"})

    if mode in ("work", "combo"):
        _hr()
        print("""
  Work world — who are the colleagues, clients, or collaborators
  you'd want to find in your notes?

  Format: name, role (e.g. "Ben, co-founder" or just "Sarah")
  Type 'done' when finished.
""")
        while True:
            entry = input("  Person: ").strip()
            if entry.lower() in ("done", ""):
                break
            parts = [p.strip() for p in entry.split(",", 1)]
            name = parts[0]
            role = parts[1] if len(parts) > 1 else ""
            if name:
                people.append({"name": name, "relationship": role, "context": "work"})

    return people, aliases


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Projects
# ─────────────────────────────────────────────────────────────────────────────


def _ask_projects(mode: str) -> list:
    if mode == "personal":
        return []

    _hr()
    print("""
  What are your main projects? (These help MemPalace distinguish project
  names from person names — e.g. "Lantern" the project vs. "Lantern" the word.)

  Type 'done' when finished.
""")
    projects = []
    while True:
        proj = input("  Project: ").strip()
        if proj.lower() in ("done", ""):
            break
        if proj:
            projects.append(proj)
    return projects


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Wings
# ─────────────────────────────────────────────────────────────────────────────


def _ask_wings(mode: str) -> list:
    defaults = DEFAULT_WINGS[mode]
    _hr()
    print(f"""
  Wings are the top-level categories in your memory palace.

  Suggested wings for {mode} mode:
    {", ".join(defaults)}

  Press enter to keep these, or type your own comma-separated list.
""")
    custom = input("  Wings: ").strip()
    if custom:
        return [w.strip() for w in custom.split(",") if w.strip()]
    return defaults


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Auto-detect from files
# ─────────────────────────────────────────────────────────────────────────────


def _auto_detect(directory: str, known_people: list) -> list:
    """Scan directory for additional entity candidates."""
    known_names = {p["name"].lower() for p in known_people}

    try:
        files = scan_for_detection(directory)
        if not files:
            return []
        detected = detect_entities(files)
        new_people = [
            e
            for e in detected["people"]
            if e["name"].lower() not in known_names and e["confidence"] >= 0.7
        ]
        return new_people
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Step 6: Ambiguity warnings
# ─────────────────────────────────────────────────────────────────────────────


def _warn_ambiguous(people: list) -> list:
    """
    Flag names that are also common English words.
    Returns list of ambiguous names for user awareness.
    """
    from mempalace.entity_registry import COMMON_ENGLISH_WORDS

    ambiguous = []
    for p in people:
        if p["name"].lower() in COMMON_ENGLISH_WORDS:
            ambiguous.append(p["name"])
    return ambiguous


# ─────────────────────────────────────────────────────────────────────────────
# Main onboarding flow
# ─────────────────────────────────────────────────────────────────────────────


def _generate_aaak_bootstrap(
    people: list, projects: list, wings: list, mode: str, config_dir: Path = None
):
    """
    Generate AAAK entity registry + critical facts bootstrap from onboarding data.
    These files teach the AI about the user's world from session one.
    """
    mempalace_dir = Path(config_dir) if config_dir else Path.home() / ".mempalace"
    mempalace_dir.mkdir(parents=True, exist_ok=True)

    # Build AAAK entity codes (first 3 letters of name, uppercase)
    entity_codes = {}
    for p in people:
        name = p["name"]
        code = name[:3].upper()
        # Handle collisions
        while code in entity_codes.values():
            code = name[:4].upper()
        entity_codes[name] = code

    # AAAK entity registry
    registry_lines = [
        "# AAAK Entity Registry",
        "# Auto-generated by mempalace init. Update as needed.",
        "",
        "## People",
    ]
    for p in people:
        name = p["name"]
        code = entity_codes[name]
        rel = p.get("relationship", "")
        registry_lines.append(f"  {code}={name} ({rel})" if rel else f"  {code}={name}")

    if projects:
        registry_lines.extend(["", "## Projects"])
        for proj in projects:
            code = proj[:4].upper()
            registry_lines.append(f"  {code}={proj}")

    registry_lines.extend(
        [
            "",
            "## AAAK Quick Reference",
            "  Symbols: ♡=love ★=importance ⚠=warning →=relationship |=separator",
            "  Structure: KEY:value | GROUP(details) | entity.attribute",
            "  Read naturally — expand codes, treat *markers* as emotional context.",
        ]
    )

    (mempalace_dir / "aaak_entities.md").write_text("\n".join(registry_lines), encoding="utf-8")

    # Critical facts bootstrap (pre-palace — before any mining)
    facts_lines = [
        "# Critical Facts (bootstrap — will be enriched after mining)",
        "",
    ]

    personal_people = [p for p in people if p.get("context") == "personal"]
    work_people = [p for p in people if p.get("context") == "work"]

    if personal_people:
        facts_lines.append("## People (personal)")
        for p in personal_people:
            code = entity_codes[p["name"]]
            rel = p.get("relationship", "")
            facts_lines.append(
                f"- **{p['name']}** ({code}) — {rel}" if rel else f"- **{p['name']}** ({code})"
            )
        facts_lines.append("")

    if work_people:
        facts_lines.append("## People (work)")
        for p in work_people:
            code = entity_codes[p["name"]]
            rel = p.get("relationship", "")
            facts_lines.append(
                f"- **{p['name']}** ({code}) — {rel}" if rel else f"- **{p['name']}** ({code})"
            )
        facts_lines.append("")

    if projects:
        facts_lines.append("## Projects")
        for proj in projects:
            facts_lines.append(f"- **{proj}**")
        facts_lines.append("")

    facts_lines.extend(
        [
            "## Palace",
            f"Wings: {', '.join(wings)}",
            f"Mode: {mode}",
            "",
            "*This file will be enriched by palace_facts.py after mining.*",
        ]
    )

    (mempalace_dir / "critical_facts.md").write_text("\n".join(facts_lines), encoding="utf-8")


def _wing_slug(name: str) -> str:
    """
    Turn a free-form label into the wing key format used across the palace.

    We keep this helper local to onboarding because the same slug rules are used
    for wing_config.json, default agent wings, and the identity scaffold text.
    """
    return f"wing_{name.strip().lower().replace(' ', '_')}"


def _infer_mode(people: list, projects: list) -> str:
    """
    Infer a reasonable onboarding mode when setup is running non-interactively.

    `mempalace init --yes` needs to generate the same bootstrap files as the
    guided flow, so we synthesize the mode from the entity contexts we have.
    """
    contexts = {entry.get("context") for entry in people if entry.get("context")}
    if {"personal", "work"} <= contexts:
        return "combo"
    if "work" in contexts or projects:
        return "work"
    return "personal"


def _generate_wing_config(
    people: list, projects: list, wings: list, mode: str, config_dir: Path = None
) -> Path:
    """
    Write ~/.mempalace/wing_config.json.

    The public docs have long said init generates this file. We now do that for
    both guided and non-interactive setup so the bootstrap output matches the
    documented shape.
    """
    mempalace_dir = Path(config_dir) if config_dir else Path.home() / ".mempalace"
    mempalace_dir.mkdir(parents=True, exist_ok=True)

    # Seed the chosen taxonomy wings first so the user's high-level palace shape
    # is visible even before any project or conversation has been mined.
    wing_map = {
        _wing_slug(wing): {
            "type": "taxonomy",
            "keywords": [wing.lower()],
            "label": wing,
        }
        for wing in wings
    }

    # Add person and project wings so simple keyword routing can start working
    # from day one. This is intentionally lightweight; mining still provides the
    # real storage and retrieval behavior later.
    for person in people:
        name = person["name"].strip()
        if not name:
            continue
        wing_map[_wing_slug(name)] = {
            "type": "person",
            "entity": name,
            "relationship": person.get("relationship", ""),
            "keywords": [name.lower(), f"{name.lower()}'s"],
        }

    for project in projects:
        clean = project.strip()
        if not clean:
            continue
        wing_map[_wing_slug(clean)] = {
            "type": "project",
            "entity": clean,
            "keywords": [clean.lower()],
        }

    payload = {
        "default_wing": "wing_general",
        "mode": mode,
        "wings": wing_map,
    }
    out_path = mempalace_dir / "wing_config.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_path


def _generate_identity_scaffold(
    people: list, projects: list, wings: list, mode: str, config_dir: Path = None
) -> Path:
    """
    Create identity.txt if it does not exist yet.

    Layer 0 reads this file directly, so generating a scaffold during init turns
    a documented manual follow-up into a working default for new users.
    """
    mempalace_dir = Path(config_dir) if config_dir else Path.home() / ".mempalace"
    mempalace_dir.mkdir(parents=True, exist_ok=True)
    out_path = mempalace_dir / "identity.txt"
    if out_path.exists():
        return out_path

    lines = [
        "## L0 — IDENTITY",
        "I am a memory-aware AI assistant working with the same human across sessions.",
        f"Mode: {mode}",
        f"Primary wings: {', '.join(wings)}",
    ]

    if people:
        lines.append("Known people:")
        for person in people:
            relationship = person.get("relationship", "").strip()
            detail = f" — {relationship}" if relationship else ""
            lines.append(f"- {person['name']}{detail}")

    if projects:
        lines.append("Known projects:")
        for project in projects:
            lines.append(f"- {project}")

    lines.extend(
        [
            "",
            "Update this file with your preferred tone, standing instructions, and durable facts.",
        ]
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _persist_topic_wings(wings: list, config_dir: Path = None) -> Path:
    """
    Save the chosen wing taxonomy into config.json.

    Without this, onboarding would ask for wings but later commands would still
    report the package defaults, which makes the guided flow feel fake.
    """
    config = MempalaceConfig(config_dir=config_dir)
    config.init()
    return config.set_topic_wings(wings)


def bootstrap_from_entities(
    people: list,
    projects: list,
    *,
    wings: list = None,
    mode: str = None,
    config_dir: Path = None,
    install_default_agents: bool = True,
) -> dict:
    """
    Generate the full first-run bootstrap without interactive prompts.

    This is the bridge between the old `mempalace init --yes` behavior and the
    richer guided onboarding promised in the README.
    """
    inferred_mode = mode or _infer_mode(people, projects)
    resolved_wings = wings or DEFAULT_WINGS[inferred_mode]

    _generate_aaak_bootstrap(people, projects, resolved_wings, inferred_mode, config_dir)
    wing_config_path = _generate_wing_config(
        people, projects, resolved_wings, inferred_mode, config_dir
    )
    identity_path = _generate_identity_scaffold(
        people, projects, resolved_wings, inferred_mode, config_dir
    )
    config_path = _persist_topic_wings(resolved_wings, config_dir)
    created_agents = ensure_default_agents(config_dir) if install_default_agents else []

    return {
        "mode": inferred_mode,
        "wings": resolved_wings,
        "config_path": config_path,
        "wing_config_path": wing_config_path,
        "identity_path": identity_path,
        "created_agents": created_agents,
    }


def registry_project_entities(registry: EntityRegistry) -> dict:
    """
    Convert the global entity registry into the simple project-level entities.json.

    The miner expects plain name lists, while the registry stores richer metadata
    and aliases. We filter out alias records here to avoid duplicating people.
    """
    canonical_people = []
    for name, info in registry.people.items():
        if info.get("canonical"):
            continue
        canonical_people.append(name)
    return {
        "people": sorted(canonical_people),
        "projects": sorted(registry.projects),
    }


def run_onboarding(
    directory: str = ".",
    config_dir: Path = None,
    auto_detect: bool = True,
) -> EntityRegistry:
    """
    Run the full onboarding flow.
    Returns the seeded EntityRegistry.
    """
    # Step 1: Mode
    mode = _ask_mode()

    # Step 2: People
    people, aliases = _ask_people(mode)

    # Step 3: Projects
    projects = _ask_projects(mode)

    # Step 4: Wings (stored in config, not registry — just show user)
    wings = _ask_wings(mode)

    # Step 5: Auto-detect additional people from files
    if auto_detect and _yn("\nScan your files for additional names we might have missed?"):
        directory = _ask("Directory to scan", default=directory)
        detected = _auto_detect(directory, people)
        if detected:
            _hr()
            print(f"\n  Found {len(detected)} additional name candidates:\n")
            for e in detected:
                print(
                    f"    {e['name']:20} confidence={e['confidence']:.0%}  "
                    f"({', '.join(e['signals'][:1])})"
                )
            print()
            if _yn("  Add any of these to your registry?"):
                for e in detected:
                    ans = input(f"    {e['name']} — (p)erson, (s)kip? ").strip().lower()
                    if ans == "p":
                        rel = input(f"    Relationship/role for {e['name']}? ").strip()
                        ctx = (
                            "personal"
                            if mode == "personal"
                            else (
                                "work"
                                if mode == "work"
                                else input("    Context — (p)ersonal or (w)ork? ")
                                .strip()
                                .lower()
                                .replace("w", "work")
                                .replace("p", "personal")
                            )
                        )
                        people.append({"name": e["name"], "relationship": rel, "context": ctx})

    # Step 6: Warn about ambiguous names
    ambiguous = _warn_ambiguous(people)
    if ambiguous:
        _hr()
        print(f"""
  Heads up — these names are also common English words:
    {", ".join(ambiguous)}

  MemPalace will check the context before treating them as person names.
  For example: "I picked up Riley" → person.
               "Have you ever tried" → adverb.
""")

    # Build and save registry
    registry = EntityRegistry.load(config_dir)
    registry.seed(mode=mode, people=people, projects=projects, aliases=aliases)

    # Guided onboarding should leave the whole bootstrap in place, not just the
    # entity registry. We call the same helper that non-interactive init uses so
    # both flows stay aligned over time.
    bootstrap = bootstrap_from_entities(
        people,
        projects,
        wings=wings,
        mode=mode,
        config_dir=config_dir,
    )

    # Summary
    _header("Setup Complete")
    print()
    print(f"  {registry.summary()}")
    print(f"\n  Wings: {', '.join(wings)}")
    print(f"\n  Registry saved to: {registry._path}")
    print("\n  AAAK entity registry: ~/.mempalace/aaak_entities.md")
    print("  Critical facts bootstrap: ~/.mempalace/critical_facts.md")
    print("  Wing config: ~/.mempalace/wing_config.json")
    print("  Identity scaffold: ~/.mempalace/identity.txt")
    if bootstrap["created_agents"]:
        print("  Specialist agents: ~/.mempalace/agents/*.json")
    print("\n  Your AI will know your world from the first session.")
    print()

    return registry


# ─────────────────────────────────────────────────────────────────────────────
# Quick setup (non-interactive, for testing)
# ─────────────────────────────────────────────────────────────────────────────


def quick_setup(
    mode: str,
    people: list,
    projects: list = None,
    aliases: dict = None,
    config_dir: Path = None,
) -> EntityRegistry:
    """
    Programmatic setup without interactive prompts.
    Used in tests and benchmark scripts.

    people: list of dicts {"name": str, "relationship": str, "context": str}
    """
    registry = EntityRegistry.load(config_dir)
    registry.seed(
        mode=mode,
        people=people,
        projects=projects or [],
        aliases=aliases or {},
    )
    return registry


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    directory = sys.argv[1] if len(sys.argv) > 1 else "."
    run_onboarding(directory=directory)
