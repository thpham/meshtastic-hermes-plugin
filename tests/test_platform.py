"""Tests for the platform adapter package (no Hermes gateway runtime required)."""

from __future__ import annotations

from meshtastic_hermes import gateway_bridge as gb
from meshtastic_platform import adapter


def test_imports_sibling_package():
    # The cross-package import must resolve (regression for the directory-drop
    # ModuleNotFoundError: No module named 'meshtastic_hermes').
    import meshtastic_hermes  # noqa: F401


def test_allowed_channels_from_env(monkeypatch):
    monkeypatch.delenv("MESHTASTIC_REPLY_ALL", raising=False)
    monkeypatch.setenv("MESHTASTIC_REPLY_CHANNELS", "1,2")
    assert adapter._allowed_channels_from_env() == {1, 2}

    monkeypatch.setenv("MESHTASTIC_REPLY_ALL", "true")
    assert adapter._allowed_channels_from_env() == gb.ALL_CHANNELS

    monkeypatch.delenv("MESHTASTIC_REPLY_ALL", raising=False)
    monkeypatch.delenv("MESHTASTIC_REPLY_CHANNELS", raising=False)
    assert adapter._allowed_channels_from_env() is None  # DMs only


def test_register_bundles_skill():
    captured = {"skills": [], "platform": None}

    class Ctx:
        def register_skill(self, name, path):
            captured["skills"].append(name)

        def register_platform(self, **kw):
            captured["platform"] = kw

    adapter.register(Ctx())
    # The responder skill registers regardless of whether the gateway runtime is present.
    assert "mesh-responder" in captured["skills"]
