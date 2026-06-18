# Architecture

## Overview

The plugin bridges a stateless tool interface (Hermes) to a stateful, threaded radio
link (Meshtastic), and persists everything it observes into a knowledge base.

```
            register(ctx)                 pubsub "meshtastic.receive"
Hermes ──────────────────▶ __init__.py        (background thread)
   │                          │                      │
   │ tool calls               │ wires                ▼
   ▼                          ▼                  observer.Observer
tools.py ──────▶ connection.ConnectionManager ──────────┐
   │  (queries)         │  (TCPInterface)               │ record_packet / upsert_node
   └────────────────────┼───────────────────────────────┤
                        ▼                               ▼
                  observer.get_observer().kb  ◀────  knowledge.NodeGraph (SQLite)
                        (single shared KB instance)
```

## Components

### `__init__.py` — `register(ctx)`

Called once at startup. Registers the 12 tools under the `meshtastic` toolset, two
lifecycle hooks (`on_session_start` auto-connects when `MESHTASTIC_HOST` is set;
`on_session_end` disconnects), a `/meshtastic` slash command, and a `hermes meshtastic`
CLI command. Slash/CLI registration is feature-detected (`hasattr(ctx, ...)`) so older
Hermes builds still load the plugin. It also registers bundled skills from
`skills/<name>/SKILL.md` via `ctx.register_skill` (loaded on demand as `meshtastic:<name>`).

### `connection.py` — `ConnectionManager` (singleton)

Owns the single process-wide `TCPInterface`. `connect(host, port)` opens the link and
subscribes the observer to the `meshtastic.receive` pubsub topic (the **parent** topic,
which delivers _all_ packet types including encrypted `PRIVATE_APP` frames). A
`threading.Lock` guards connect/disconnect. The `meshtastic` import is lazy and raises
`MeshtasticUnavailable` (caught by the tool wrapper) when the `meshtastic` package is absent.

### `observer.py` — `Observer` (singleton)

The receive callback. It must never raise (that would kill the radio's listener thread),
so `on_receive` wraps everything in a try/except. For each packet it:

1. Normalizes addresses (`fromId`/`from` → `!hex`), detects encryption (no `decoded` key).
2. Records **metadata only** into the KB via `record_packet`.
3. Enriches node identity from `NODEINFO_APP` frames (`upsert_node`).
4. Appends to a bounded in-memory ring buffer **only** for decoded `TEXT_MESSAGE_APP`
   frames — encrypted content is never decoded or stored.

The observer owns the canonical `NodeGraph`; `tools.py` queries that same instance via
`get_observer().kb`, so observation and queries share one source of truth.

### `knowledge.py` — `NodeGraph` (SQLite)

Pure, stdlib-only, radio-independent (hence unit-testable). Two tables:

- `nodes` — identity + last-seen rollups (names, hw, role, signal, position, packet count).
- `interactions` — one row per observed packet: `from_node`, `to_node`, `channel`,
  `portnum`, `encrypted`, `hop_limit`, `rx_snr`, `rx_rssi`, `payload_size`, `ts`.
  **No content/payload column exists** — by construction we cannot persist message bodies.

Query methods: `nodes()`, `interactions()`, `neighbors()` (interaction-count graph edges),
`top_talkers()`, `summary()`. `sqlite3` is opened with `check_same_thread=False` and all
access is lock-guarded because writes come from the radio thread while reads come from the
tool/main thread.

`default_db_path()` resolves the DB location in priority order so it lands somewhere
writable in every deployment: `MESHTASTIC_HERMES_DB` (explicit) → `HERMES_HOME` (Hermes'
own dir, next to its `config.yaml`) → systemd `STATE_DIRECTORY` → `~/.hermes/`.

### `__main__.py` — standalone harness

A radio-and-Hermes-free entry point (`python -m meshtastic_hermes`) for development and
testing. It registers the plugin through a fake context (`FakeContext`) and exposes
`list` / `call` / `repl` / `observe` / `bridge`. The `bridge` subcommand simulates the
gateway loop using the same `gateway_bridge` routing as the real adapter. It is not part
of the Hermes runtime path.

## Threading notes

- Radio RX runs on a background thread created by `meshtastic`.
- Tool handlers run on the agent's main thread.
- Shared state (`NodeGraph`, the recent-message deque, the interface handle) is guarded by
  locks. `deque(maxlen=...)` bounds memory for the recent-message buffer.

## Gateway adapter (`meshtastic_platform`)

A second, separate plugin (`kind: platform`) makes the mesh a bidirectional Hermes
gateway. `meshtastic_platform/adapter.py` subclasses `BasePlatformAdapter`:

- **Inbound:** the radio RX thread's pubsub callback (`_on_rx`) normalizes a packet via
  `gateway_bridge.inbound_from_packet`, applies the reply policy, then crosses the
  thread→event-loop boundary with `asyncio.run_coroutine_threadsafe(self._dispatch(...))`.
  `_dispatch` builds a `MessageEvent` and calls `self.handle_message(event)`; the base
  routes it to the agent and calls `send()` with the reply.
- **Outbound:** `send(chat_id, content)` maps the `chat_id` back to radio params via
  `gateway_bridge.outbound_target` and reuses `tools.send_text` (run in an executor).
- **Decoupling:** all routing/policy lives in `gateway_bridge.py` (pure, unit-tested), so
  the same logic backs the REPL simulator (`python -m meshtastic_hermes bridge`). The
  `gateway.*` imports are lazy/guarded, so the module loads (as a no-op) outside Hermes.

## Dependency handling

`meshtastic` is a hard dependency in `pyproject.toml`, so any pip-based install pulls it
into Hermes' Python environment automatically (plugins share the `hermes` process's
interpreter — there is no per-plugin venv).

We deliberately do **not** use Hermes' `tools.lazy_deps.ensure()` runtime auto-installer:
it only installs packages whose feature key is on Hermes' maintainer-curated in-tree
`LAZY_DEPS` allowlist (and it can be globally disabled), so a third-party `meshtastic` key
would just raise `FeatureUnavailable`. Instead the handlers import-guard the radio stack
themselves and return `{"error": ..., "code": "radio_unavailable"}` with an install hint —
this only triggers on a bare directory-drop install that skipped pip. The KB tools have no
radio dependency and always work.
