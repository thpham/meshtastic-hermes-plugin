"""Tests for the standalone harness — no radio, no Hermes required."""

from __future__ import annotations

import json

from meshtastic_hermes.__main__ import build_registry, main


def test_registry_wires_everything():
    ctx = build_registry()
    assert len(ctx.tools) == 12
    # both lifecycle hooks registered
    assert "on_session_start" in ctx.hooks
    assert "on_session_end" in ctx.hooks
    # the /meshtastic slash command registered
    assert "meshtastic" in ctx.commands


def test_offline_kb_tool_returns_json():
    ctx = build_registry()
    result = ctx.tools["meshtastic_kb_summary"]["handler"]({})
    data = json.loads(result)  # must be valid JSON
    assert "nodes" in data and "packets" in data


def test_call_command_offline(capsys):
    rc = main(["call", "meshtastic_kb_summary"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "nodes" in out


def test_unknown_tool_errors(capsys):
    rc = main(["call", "does_not_exist"])
    assert rc == 1
    assert "unknown tool" in capsys.readouterr().out


def test_list_command(capsys):
    rc = main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "meshtastic_connect" in out
    assert "12 tools" in out


def test_repl_dispatches_offline_tools(capsys, monkeypatch):
    # Feed REPL input lines (no host -> no auto-connect), then quit.
    lines = iter(["meshtastic_kb_summary", "help", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(lines))
    rc = main(["repl"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"nodes"' in out      # kb_summary ran in-process
    assert "12 tools" in out     # help listed tools


def test_repl_reports_unknown_tool(capsys, monkeypatch):
    lines = iter(["bogus_tool", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(lines))
    rc = main(["repl"])
    assert rc == 0
    assert "unknown tool" in capsys.readouterr().out
