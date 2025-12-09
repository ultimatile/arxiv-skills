#!/usr/bin/env python3
"""
Check if pdf skill is available in the environment.
"""

from pathlib import Path


def check_pdf_skill_available() -> bool:
    """Check if pdf skill is available."""
    possible_locations = [
        Path.home() / ".claude/skills/pdf/SKILL.md",
        Path(".claude/skills/pdf/SKILL.md"),
    ]
    return any(loc.exists() for loc in possible_locations)


def get_pdf_skill_path() -> Path | None:
    """Get the path to pdf skill if available."""
    possible_locations = [
        Path.home() / ".claude/skills/pdf",
        Path(".claude/skills/pdf"),
    ]
    for loc in possible_locations:
        if (loc / "SKILL.md").exists():
            return loc
    return None


if __name__ == "__main__":
    if check_pdf_skill_available():
        skill_path = get_pdf_skill_path()
        print(f"✓ pdf skill found at: {skill_path}")
        exit(0)
    else:
        print("✗ pdf skill not found")
        exit(1)
