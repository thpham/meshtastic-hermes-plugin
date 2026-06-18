"""Shared test fixtures."""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolate_kb_path():
    """Keep the knowledge base off the real ~/.hermes during tests.

    Tests that exercise the live tools (e.g. kb_summary) would otherwise create the
    default DB under $HOME, which fails in sandboxed/read-only-HOME environments
    (Nix build, CI). Point it at in-memory SQLite for the whole session. Path-
    resolution tests still monkeypatch this var per-test and are restored after.
    """
    os.environ["MESHTASTIC_HERMES_DB"] = ":memory:"
    yield
