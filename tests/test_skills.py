"""Tests for bundled skills: registration + Hermes authoring conventions."""

from __future__ import annotations

import pathlib
import re

from meshtastic_hermes.__main__ import build_registry

REPO = pathlib.Path(__file__).parent.parent
SKILL_FILES = sorted(REPO.glob("meshtastic_*/skills/*/SKILL.md"))


def test_skill_files_present():
    names = {p.parent.name for p in SKILL_FILES}
    assert {"mesh-recon", "messaging-safety", "mesh-responder"} <= names


def test_tools_plugin_registers_its_skills():
    ctx = build_registry()
    assert set(ctx.skills) == {"mesh-recon", "messaging-safety"}
    # registered value is the Path to the SKILL.md
    assert all(p.name == "SKILL.md" for p in ctx.skills.values())


def test_skill_frontmatter_conventions():
    # Hermes hardline: description <= 60 chars, one sentence ending with a period.
    for md in SKILL_FILES:
        text = md.read_text()
        assert text.startswith("---"), md
        desc = re.search(r'^description:\s*"?(.*?)"?\s*$', text, re.MULTILINE)
        name = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
        assert name and desc, md
        d = desc.group(1)
        assert len(d) <= 60, (md.parent.name, len(d), d)
        assert d.endswith("."), (md.parent.name, d)
        # directory name matches the frontmatter name
        assert name.group(1).strip() == md.parent.name, md
