# Usage

## Prerequisites

- A Meshtastic node reachable over TCP/IP (WiFi-enabled ESP32 firmware, or `meshtasticd`).
  Default port is `4403`.
- Hermes installed, with this plugin installed and **enabled**. On desktop:
  `just link && just enable` (or `hermes plugins enable meshtastic`). On NixOS:
  declare it in your config (see below) — `hermes plugins enable` is blocked there
  because `config.yaml` is Nix-generated and `.managed`.

## Deploying on NixOS

Hermes ships a Nix flake with a NixOS module; this plugin ships an overlay. Wire them
together — `extraPythonPackages` takes the plugin (a list of packages), and
`settings.plugins.enabled` turns it on:

```nix
# flake.nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    hermes-agent.url = "github:NousResearch/hermes-agent";
    meshtastic-hermes-plugin.url = "github:thpham/meshtastic-hermes-plugin";
  };

  outputs = { nixpkgs, hermes-agent, meshtastic-hermes-plugin, ... }: {
    nixosConfigurations.myhost = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        hermes-agent.nixosModules.default
        { nixpkgs.overlays = [ meshtastic-hermes-plugin.overlays.default ]; }
        ./hermes.nix
      ];
    };
  };
}
```

```nix
# hermes.nix
{ pkgs, ... }:
{
  services.hermes-agent = {
    enable = true;

    # The plugin (meshtastic comes in transitively). The overlay also populates
    # python312Packages etc. — use the set matching your Hermes build if it pins one.
    extraPythonPackages = [ pkgs.python3Packages.meshtastic-hermes-plugin ];

    # Turn the plugin on (CLI `hermes plugins enable` is blocked on NixOS).
    settings.plugins.enabled = [ "meshtastic" ];

    # Auto-connect + observe on session start (non-secret env).
    environment.MESHTASTIC_HOST = "192.168.55.73";
    # KB defaults to $HERMES_HOME/meshtastic_kb.sqlite; override if you like:
    # environment.MESHTASTIC_HERMES_DB = "/var/lib/hermes/meshtastic_kb.sqlite";
  };
}
```

After `nixos-rebuild switch`, the KB persists at `/var/lib/hermes/.hermes/meshtastic_kb.sqlite`
(next to Hermes' own `config.yaml`).

## Quick start

1. **Optionally** set a default node so the plugin auto-connects each session:

   ```bash
   export MESHTASTIC_HOST=192.168.55.73
   ```

2. Start Hermes and confirm the plugin loaded:

   ```
   /plugins
   ```

   You should see `meshtastic` listed with its tools. Use `/meshtastic` for a quick
   status + KB summary at any time.

3. Drive it through the agent, e.g.:
   - "Connect to my meshtastic node." → `meshtastic_connect`
   - "Who's on the mesh?" → `meshtastic_list_nodes`
   - "Send 'hello mesh' on the primary channel." → `meshtastic_send_text`
   - "What have you observed about node !a1b2c3d4?" → `meshtastic_kb_neighbors` / `meshtastic_kb_interactions`
   - "Summarize mesh activity." → `meshtastic_kb_summary`

## Connecting explicitly

If `MESHTASTIC_HOST` is unset, ask the agent to connect with a host, which calls:

```json
{
  "name": "meshtastic_connect",
  "arguments": { "host": "192.168.55.73", "port": 4403 }
}
```

All other tools require an active connection except the `meshtastic_kb_*` tools, which
read the persistent knowledge base and work offline.

## The knowledge base

Every packet observed while connected is recorded as metadata (never content). Over time
the KB accumulates:

- **Nodes** — identities learned from `NODEINFO` frames plus signal/last-seen rollups.
- **Interactions** — from/to/channel/port/hops/SNR/RSSI per packet, including encrypted
  packets on private channels (logged as `ENCRYPTED`, metadata only).

Useful queries:

- `meshtastic_kb_summary` — totals, channels seen, top talkers.
- `meshtastic_kb_nodes` — `sort` by `last_seen`, `first_seen`, `packets`, or `name`.
- `meshtastic_kb_interactions` — filter by `node_id` and/or `since` (UNIX timestamp).
- `meshtastic_kb_neighbors` — inferred direct contacts of a node, ranked by count.

The KB path is resolved in priority order: `MESHTASTIC_HERMES_DB` (explicit override) →
`$HERMES_HOME` (Hermes' own home — `/var/lib/hermes/.hermes` under the NixOS service, so
the KB sits next to `config.yaml`) → systemd's `$STATE_DIRECTORY` → `~/.hermes/` (desktop
default). You can inspect it directly:

```bash
sqlite3 ~/.hermes/meshtastic_kb.sqlite "SELECT from_node, to_node, portnum, encrypted FROM interactions ORDER BY ts DESC LIMIT 20;"
```

## Standalone testing (without Hermes)

Before wiring the plugin into Hermes, you can exercise it directly via the bundled
harness. It registers the plugin through a fake Hermes context — so registration,
schemas, hooks and the real tool handlers all run — then dispatches tools for you. The
`meshtastic_kb_*` tools work fully offline; connecting/observing needs a reachable node.

```bash
# List everything register() wired up (tools, hooks, commands)
python -m meshtastic_hermes list                 # or: just standalone list

# Call a single tool with optional JSON args (handlers return JSON).
# NOTE: each `call` is its own process, so the live connection does NOT persist
# between calls — `call` is best for the offline meshtastic_kb_* tools.
python -m meshtastic_hermes call meshtastic_kb_summary

# Interactive shell with a PERSISTENT connection (auto-connects to the host, or
# MESHTASTIC_HOST). Connect once, then send/read across multiple calls:
python -m meshtastic_hermes repl 192.168.55.73
#   meshtastic> meshtastic_send_text {"text": "hello mesh"}
#   meshtastic> meshtastic_recent_messages {"limit": 5}
#   meshtastic> quit

# One-shot: connect, observe live traffic for N seconds, dump nodes + KB
python -m meshtastic_hermes observe 192.168.55.73 30
```

Because the live connection is an in-process singleton, stateful flows (connect → send →
read) must happen in **one** process — use `repl` (interactive) or `observe` (capture).
`observe` is the quickest end-to-end check against real hardware. Tools that need a radio
return a clear JSON error when not connected, so `list`/`call` are safe to run anywhere.

## CLI

Outside a chat session:

```bash
hermes meshtastic status       # connection status as JSON
hermes meshtastic kb-summary   # KB summary as JSON
```

## Troubleshooting

- **Plugin not listed** — run `just hermes-debug` (`HERMES_PLUGINS_DEBUG=1 hermes plugins
list`) for verbose discovery logs; ensure it's enabled — `plugins.enabled` in
`~/.hermes/config.yaml` (desktop) or `services.hermes-agent.settings.plugins.enabled` (NixOS).
- **`radio_unavailable` error from a tool** — the `meshtastic` package is missing from
  Hermes' Python environment (happens with bare directory-drop installs). Install it there:
  `pip install meshtastic` (pip-based installs of this package pull it automatically).
- **Connect fails** — verify the node IP and that TCP port `4403` is reachable
  (`nc -z <host> 4403`).
