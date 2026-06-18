"""Tests for the standalone harness — no radio, no Hermes required."""

from __future__ import annotations

import json

from meshtastic_hermes.__main__ import build_registry, main, repl_command


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
    lines = iter(["kb", "tools", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(lines))
    rc = main(["repl"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"nodes"' in out             # `kb` friendly verb ran kb_summary
    assert "meshtastic_connect" in out  # `tools` listed the tool names


def test_repl_reports_unknown_command(capsys, monkeypatch):
    lines = iter(["bogus_cmd", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(lines))
    rc = main(["repl"])
    assert rc == 0
    assert "unknown command" in capsys.readouterr().out


def test_repl_send_friendly_parsing():
    # `send <channel> <text...>` builds the right args; offline -> not connected.
    ctx = build_registry()
    assert "usage: send" in repl_command(ctx, "send")
    assert "integer index" in repl_command(ctx, "send notanint hi")
    # channel + multi-word text parses; tool runs (errors only because offline).
    assert "Not connected" in repl_command(ctx, "send 1 hello pommeraie")


def test_repl_kb_friendly_verb_offline():
    ctx = build_registry()
    assert '"nodes"' in repl_command(ctx, "kb")


def test_repl_kb_query_verbs_offline():
    ctx = build_registry()
    # neighbors requires a node_id
    assert "usage: neighbors" in repl_command(ctx, "neighbors")
    # neighbors <node> -> kb_neighbors (offline KB works, returns the node + list)
    out = repl_command(ctx, "neighbors !a696579c")
    assert '"node_id": "!a696579c"' in out and '"neighbors"' in out
    # interactions [node] [since] -> kb_interactions
    assert '"interactions"' in repl_command(ctx, "interactions")
    assert '"interactions"' in repl_command(ctx, "interactions !a696579c 1000")
    assert "since_unix_ts" in repl_command(ctx, "interactions !a notanumber")
    # kbnodes [sort] -> kb_nodes
    assert '"nodes"' in repl_command(ctx, "kbnodes packets")


def test_repl_dm_is_pki_no_channel():
    ctx = build_registry()
    assert "usage: dm" in repl_command(ctx, "dm")
    # dm needs only node + text (no channel); offline -> not connected proves it
    # reached the send tool.
    assert "Not connected" in repl_command(ctx, "dm !444a8c86 hi there")


def test_send_text_pki_requires_dest():
    # pki without dest_id is rejected before touching the radio.
    ctx = build_registry()
    res = ctx.tools["meshtastic_send_text"]["handler"]({"text": "hi", "pki": True})
    assert "requires dest_id" in res


def test_repl_watch_zero_seconds_returns(capsys, monkeypatch):
    # `watch 0` must not hang and must exit cleanly back to the prompt.
    lines = iter(["watch 0", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(lines))
    rc = main(["repl"])
    assert rc == 0
    assert "Watching for incoming messages" in capsys.readouterr().err
