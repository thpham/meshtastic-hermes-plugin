"""Standalone harness — exercise the plugin WITHOUT a running Hermes agent.

It registers the plugin through a fake Hermes context (so registration, schemas,
hooks and the real tool handlers are all exercised), then lets you invoke tools
directly. The ``meshtastic_kb_*`` tools work fully offline; connecting/observing
needs a reachable Meshtastic node over TCP.

Note: each invocation is a fresh process, so the live connection (an in-process
singleton) does NOT carry across separate `call` runs. Use `repl` for stateful
flows (connect once, then send/read), or `observe` for a one-shot capture.

Usage:
    python -m meshtastic_hermes list
    python -m meshtastic_hermes call meshtastic_kb_summary
    python -m meshtastic_hermes repl 192.168.55.73
    python -m meshtastic_hermes observe 192.168.55.73 30
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from . import register


class FakeContext:
    """Minimal stand-in for the Hermes registration context.

    Captures everything ``register(ctx)`` wires up so the harness can dispatch
    tools and (optionally) fire hooks exactly as Hermes would.
    """

    def __init__(self) -> None:
        self.tools: dict[str, dict[str, Any]] = {}
        self.hooks: dict[str, list] = {}
        self.commands: dict[str, dict[str, Any]] = {}
        self.cli_commands: dict[str, dict[str, Any]] = {}

    def register_tool(self, name, toolset, schema, handler, **_kw):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    def register_hook(self, event, fn):
        self.hooks.setdefault(event, []).append(fn)

    def register_command(self, name, handler, description=""):
        self.commands[name] = {"handler": handler, "description": description}

    def register_cli_command(self, name, help="", setup_fn=None, handler_fn=None):  # noqa: A002
        self.cli_commands[name] = {"help": help, "setup_fn": setup_fn, "handler_fn": handler_fn}


def build_registry() -> FakeContext:
    """Run the plugin's real ``register(ctx)`` against a fake context."""
    ctx = FakeContext()
    register(ctx)
    return ctx


def _pretty(result: str) -> str:
    """Tool handlers return JSON strings; pretty-print when possible."""
    try:
        return json.dumps(json.loads(result), indent=2)
    except (ValueError, TypeError):
        return str(result)


def _cmd_list(ctx: FakeContext, _args) -> int:
    for name, tool in ctx.tools.items():
        desc = (tool["schema"].get("description") or "").strip().splitlines()
        print(f"{name}\n    {desc[0] if desc else ''}")
    hooks = sum(len(v) for v in ctx.hooks.values())
    print(
        f"\n{len(ctx.tools)} tools, {hooks} hooks, "
        f"{len(ctx.commands)} slash command(s), {len(ctx.cli_commands)} CLI command(s)"
    )
    return 0


def _cmd_call(ctx: FakeContext, args) -> int:
    tool = ctx.tools.get(args.tool)
    if tool is None:
        print(json.dumps({"error": f"unknown tool {args.tool!r}", "available": sorted(ctx.tools)}))
        return 1
    try:
        payload = json.loads(args.args) if args.args else {}
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"invalid JSON args: {exc}"}))
        return 1
    print(_pretty(tool["handler"](payload)))
    return 0


def _cmd_observe(ctx: FakeContext, args) -> int:
    def call(name: str, payload: dict | None = None) -> str:
        return ctx.tools[name]["handler"](payload or {})

    print(_pretty(call("meshtastic_connect", {"host": args.host})))
    print(f"Observing {args.host} for {args.seconds}s (Ctrl-C to stop early)...", file=sys.stderr)
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass
    for tool in ("meshtastic_list_nodes", "meshtastic_recent_messages", "meshtastic_kb_summary"):
        print(f"\n# {tool}")
        print(_pretty(call(tool)))
    call("meshtastic_disconnect")
    return 0


_REPL_HELP = """Commands (channel is an INDEX from `channels`; 0 = Primary):
  send <channel> <text...>            broadcast on a channel (channel-PSK encrypted)
  dm <node_id> <text...>              private direct message (end-to-end / PKI)
  recent [count]                      recently decoded text messages
  nodes | channels | metrics          live radio info
  kb                                  knowledge-base summary
  connect [host] | disconnect         manage the link
  <tool_name> [json]                  call any tool raw (e.g. meshtastic_kb_nodes {"limit":5})
  tools | help | quit"""

# Friendly zero-argument verbs -> tool name.
_REPL_SIMPLE = {
    "nodes": "meshtastic_list_nodes",
    "channels": "meshtastic_list_channels",
    "metrics": "meshtastic_device_metrics",
    "kb": "meshtastic_kb_summary",
    "disconnect": "meshtastic_disconnect",
}


def repl_command(ctx: FakeContext, line: str) -> str:
    """Evaluate one REPL command line and return text to print.

    Supports friendly verbs (channel as a positional before the text) plus a raw
    ``<tool_name> [json]`` fallback. Pure function of (ctx, line) for testability.
    """
    def call(name: str, payload: dict | None = None) -> str:
        return _pretty(ctx.tools[name]["handler"](payload or {}))

    parts = line.split()
    verb = parts[0]

    if verb == "send":
        # send <channel> <text...>  — channel first, on purpose, to avoid an
        # accidental Primary (0) flood.
        if len(parts) < 3:
            return json.dumps({"error": "usage: send <channel> <text...>"})
        try:
            channel = int(parts[1])
        except ValueError:
            return json.dumps({"error": f"channel must be an integer index, got {parts[1]!r}"})
        text = line.split(None, 2)[2]
        return call("meshtastic_send_text", {"channel_index": channel, "text": text})

    if verb == "dm":
        # dm <node_id> <text...>  — end-to-end (PKI) encrypted to the node's keypair,
        # so no channel is needed and it is never sent in clear on a public channel.
        if len(parts) < 3:
            return json.dumps({"error": "usage: dm <node_id> <text...>  (end-to-end / PKI encrypted)"})
        text = line.split(None, 2)[2]
        return call("meshtastic_send_text", {"dest_id": parts[1], "pki": True, "text": text})

    if verb == "recent":
        if len(parts) > 1:
            try:
                return call("meshtastic_recent_messages", {"limit": int(parts[1])})
            except ValueError:
                return json.dumps({"error": "usage: recent [count]"})
        return call("meshtastic_recent_messages")

    if verb == "connect":
        return call("meshtastic_connect", {"host": parts[1]} if len(parts) > 1 else {})

    if verb in _REPL_SIMPLE:
        return call(_REPL_SIMPLE[verb])

    # Raw fallback: <tool_name> [json-args]
    name, _, raw = line.partition(" ")
    if name not in ctx.tools:
        return json.dumps({"error": f"unknown command {name!r}", "hint": "type 'help'"})
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"invalid JSON args: {exc}"})
    return call(name, payload)


def _enable_readline():
    """Enable arrow-key history + line editing for the REPL (best-effort).

    Importing `readline` is enough to give `input()` up/down history, left/right
    editing and Ctrl-R search. We also persist history across sessions. Skipped for
    non-interactive stdin (pipes/tests) and on platforms without readline.
    """
    if not sys.stdin.isatty():
        return None, None
    try:
        import readline
    except ImportError:
        return None, None
    histfile = os.path.expanduser("~/.meshtastic_hermes_history")
    try:
        readline.read_history_file(histfile)
    except OSError:
        pass  # no history yet, or unreadable
    readline.set_history_length(1000)
    return readline, histfile


def _cmd_repl(ctx: FakeContext, args) -> int:
    readline, histfile = _enable_readline()

    host = args.host or os.environ.get("MESHTASTIC_HOST")
    if host:
        print(_pretty(ctx.tools["meshtastic_connect"]["handler"]({"host": host})))

    print(
        "Interactive REPL — connection persists across commands in this process.\n"
        "Arrow keys recall history. Type 'help' for commands, 'quit' to exit.",
        file=sys.stderr,
    )
    while True:
        try:
            line = input("meshtastic> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("quit", "exit"):
            break
        if line in ("help", "?"):
            print(_REPL_HELP)
            continue
        if line == "tools":
            _cmd_list(ctx, args)
            continue
        print(repl_command(ctx, line))

    if readline and histfile:
        try:
            readline.write_history_file(histfile)
        except OSError:
            pass

    try:
        ctx.tools["meshtastic_disconnect"]["handler"]({})
    except Exception:
        pass
    return 0


def main(argv=None) -> int:
    ctx = build_registry()
    parser = argparse.ArgumentParser(
        prog="meshtastic_hermes", description="Standalone harness for the Meshtastic Hermes plugin"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="List registered tools, hooks and commands")
    p_call = sub.add_parser("call", help="Call a tool with optional JSON args")
    p_call.add_argument("tool")
    p_call.add_argument("args", nargs="?", default="", help="JSON object, e.g. '{\"limit\": 5}'")
    p_obs = sub.add_parser("observe", help="Connect to a node, observe traffic, dump nodes/KB")
    p_obs.add_argument("host")
    p_obs.add_argument("seconds", nargs="?", type=int, default=30)
    p_repl = sub.add_parser("repl", help="Interactive shell with a persistent connection")
    p_repl.add_argument("host", nargs="?", help="Auto-connect on start (else MESHTASTIC_HOST)")

    ns = parser.parse_args(argv)
    dispatch = {
        "list": _cmd_list,
        "call": _cmd_call,
        "observe": _cmd_observe,
        "repl": _cmd_repl,
    }
    return dispatch[ns.cmd](ctx, ns)


if __name__ == "__main__":
    raise SystemExit(main())
