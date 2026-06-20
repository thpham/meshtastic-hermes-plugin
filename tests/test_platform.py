"""Tests for the platform adapter package (no Hermes gateway runtime required)."""

from __future__ import annotations

from meshtastic_hermes import gateway_bridge as gb
from meshtastic_platform import adapter


def test_imports_sibling_package():
    # The cross-package import must resolve (regression for the directory-drop
    # ModuleNotFoundError: No module named 'meshtastic_hermes').
    import meshtastic_hermes  # noqa: F401


def test_split_text_respects_byte_limit():
    assert adapter._split_text("", 200) == []
    assert adapter._split_text("hello", 200) == ["hello"]

    # word-boundary splitting, no words lost, every chunk within the byte limit
    long = " ".join(["word"] * 100)
    parts = adapter._split_text(long, 50)
    assert all(len(p.encode("utf-8")) <= 50 for p in parts)
    assert " ".join(parts).split() == long.split()

    # a single oversized token is hard-split (no data lost), still within the limit
    parts = adapter._split_text("x" * 120, 50)
    assert all(len(p.encode("utf-8")) <= 50 for p in parts)
    assert "".join(parts) == "x" * 120

    # multibyte chars are not split mid-character
    parts = adapter._split_text("é" * 100, 50)
    assert all(len(p.encode("utf-8")) <= 50 for p in parts)
    assert "".join(parts) == "é" * 100


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
