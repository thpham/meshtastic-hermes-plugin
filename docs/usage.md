# Usage

## Prerequisites

- A Meshtastic node reachable over TCP/IP (WiFi-enabled ESP32 firmware, or `meshtasticd`).
  Default port is `4403`.
- Hermes installed, with this plugin installed and **enabled**. On desktop:
  `just link && just enable` (or `hermes plugins enable meshtastic`). On NixOS:
  declare it in your config (see below) — `hermes plugins enable` is blocked there
  because `config.yaml` is Nix-generated and `.managed`.

## Deploying on NixOS

Hermes ships a Nix flake (NixOS module) and this repo ships an overlay that adds the
package to your Python set. This one package provides **both** plugins:

| Plugin name (in `plugins.enabled`) | Package             | What it does                                                       |
| ---------------------------------- | ------------------- | ------------------------------------------------------------------ |
| `meshtastic`                       | the tools/KB plugin | 12 tools, knowledge base, slash + CLI commands                     |
| `meshtastic-platform`              | the gateway adapter | inbound mesh text drives the agent; replies go back over the radio |

Enable either or both. They cooperate over one radio connection (a process-wide
singleton), so you point them at the same `MESHTASTIC_HOST` — whichever connects first
wins and the other reuses it (no churn).

### 1. Flake wiring

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

### 2. Service config (complete example)

```nix
# hermes.nix
{ config, pkgs, ... }:
{
  services.hermes-agent = {
    enable = true;
    addToSystemPackages = true;          # put `hermes` on PATH + set HERMES_HOME system-wide

    # Hermes needs an LLM. Pick a model; keep the API key OUT of the Nix store by
    # supplying it via an environment file (sops-nix / agenix), not `environment`.
    settings.model.default = "anthropic/claude-sonnet-4";
    environmentFiles = [ config.sops.secrets."hermes-env".path ];  # e.g. ANTHROPIC_API_KEY=...

    # This package provides BOTH plugins; the overlay also populates python312Packages
    # etc. — use the set matching your Hermes build if it pins a specific Python.
    extraPythonPackages = [ pkgs.python3Packages.meshtastic-hermes-plugin ];

    # Enable plugins by name (CLI `hermes plugins enable` is blocked on NixOS — the
    # generated config.yaml is `.managed`). Drop "meshtastic-platform" if you only want
    # the tools/KB and no autonomous replies.
    settings.plugins.enabled = [ "meshtastic" "meshtastic-platform" ];

    # Non-secret env shared by both plugins:
    environment = {
      MESHTASTIC_HOST = "192.168.55.73";      # node to connect to (TCP)
      # Gateway reply policy (meshtastic-platform):
      MESHTASTIC_REPLY_CHANNELS = "1";        # reply to DMs + channel 1 (your private channel)
      # MESHTASTIC_REPLY_ALL = "true";        # …or reply on every channel incl. public Primary
      # MESHTASTIC_HERMES_DB = "/var/lib/hermes/meshtastic_kb.sqlite";  # KB path override
    };
  };
}
```

`meshtastic` (the radio library) comes in transitively — no need to list it. If you don't
use a secrets manager yet, you can put the API key in `environment` for testing, but it
lands in the world-readable Nix store — avoid for anything real.

### 3. Apply & verify

```bash
sudo nixos-rebuild switch
systemctl status hermes-agent
journalctl -u hermes-agent -f      # watch it connect to the node + load plugins
```

After switch, the KB persists at `/var/lib/hermes/.hermes/meshtastic_kb.sqlite` (next to
Hermes' own `config.yaml`).

## Gateway: autonomous replies over the mesh

With `meshtastic-platform` enabled, the mesh becomes a Hermes chat channel — no tool calls
needed. Someone messages your node and the agent answers:

1. A peer sends a message **to your connected node** (`MESHTASTIC_HOST`).
2. The adapter decodes it and hands it to the agent as a normal turn.
3. The agent's reply is sent back over the radio — **PKI end-to-end** for a DM, or on the
   channel for a channel message.

**Reply policy** (env on the service):

| Env                                        | Effect                                                                         |
| ------------------------------------------ | ------------------------------------------------------------------------------ |
| _unset_                                    | DMs only (default) — safest, no channel noise                                  |
| `MESHTASTIC_REPLY_CHANNELS="1"` or `"1,2"` | DMs + those channel indices (your private channels; public Primary/0 excluded) |
| `MESHTASTIC_REPLY_ALL="true"`              | DMs + every channel (incl. public Primary — use with care)                     |

**Before deploying, validate the exact behavior locally** with the bridge simulator (no
Hermes, no transmit) — see [Simulate the gateway loop](#standalone-testing-without-hermes)
below. It uses the same routing/policy code as the adapter.

**Reachability caveat:** the agent only answers messages it actually _receives_. A peer's
message must be addressed to your connected node and survive the RF path — multi-hop DMs on
weak links are frequently lost, so an unanswered message is usually packet loss, not a bug.

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
# MESHTASTIC_HOST). Connect once, then send/read across multiple commands.
# Friendly verbs take the channel INDEX before the text (avoids a Primary flood):
python -m meshtastic_hermes repl 192.168.55.73
#   meshtastic> channels                         # find the index you want
#   meshtastic> send 1 hello pommeraie           # broadcast on channel 1 (channel-PSK)
#   meshtastic> dm !444a8c86 hi there            # private direct message (end-to-end/PKI)
#   meshtastic> watch 120                         # print incoming messages live (catch replies)
#   meshtastic> recent 5                          # last 5 decoded messages (RAM buffer)
#   meshtastic> nodes                             # type 'help' for all commands
#   meshtastic> quit

# One-shot: connect, observe live traffic for N seconds, dump nodes + KB
python -m meshtastic_hermes observe 192.168.55.73 30

# Simulate the GATEWAY loop (same routing/policy as the platform adapter, no Hermes):
# prints each matched inbound message and the reply it WOULD send.
python -m meshtastic_hermes bridge 192.168.55.73              # DMs only, dry-run (no transmit)
python -m meshtastic_hermes bridge 192.168.55.73 --channels 1 # DMs + channel 1, dry-run
python -m meshtastic_hermes bridge 192.168.55.73 --channels 1 --send  # actually echo-reply
python -m meshtastic_hermes bridge 192.168.55.73 --all        # every channel incl. Primary
```

The `bridge` simulator prints a line per matched message and exits after the window
(default 300s, or pass a seconds arg; Ctrl-C stops early):

```
[inbound DM] !a696579c: 'hello tom'
  -> reply to !a696579c: 'ack: hello tom'   (dry-run — pass --send to actually transmit)
```

Its reply comes from a stub `simulate_reply()` (echo) — replace it with an LLM/webhook to
prototype an autonomous bot. The real Hermes adapter uses the agent/LLM instead. Only
messages addressed to your connected node and decryptable are matched; DMs you send _to
other_ nodes are encrypted to them and never appear here.

The `repl` supports arrow-key history (↑/↓), inline line editing and Ctrl-R search, and
persists history across sessions in `~/.meshtastic_hermes_history`.

`recent` reads an **in-memory, per-process** buffer — it only holds text received during
the _current_ connection (it's never persisted; only metadata goes to the KB). To catch a
reply to a `dm`, use **`watch`** in the same session: it prints incoming messages live as
they arrive. Note that replies can still be lost to RF (multi-hop / low SNR) and won't show
if they never reach your node.

Because the live connection is an in-process singleton, stateful flows (connect → send →
read) must happen in **one** process — use `repl` (interactive) or `observe` (capture).
`observe` is the quickest end-to-end check against real hardware. Tools that need a radio
return a clear JSON error when not connected, so `list`/`call` are safe to run anywhere.

### Send encryption: `send` vs `dm`

These are not the same privacy level:

- **`send <channel> <text>`** (broadcast) is encrypted with that **channel's pre-shared
  key**. On the default Primary channel the key is public, so anyone can read it — treat
  channel sends as non-private.
- **`dm <node_id> <text>`** uses **end-to-end public-key encryption** (Curve25519) to that
  node only — it is _not_ sent in clear on a public channel. This maps to
  `meshtastic_send_text` with `pki=true`, which goes through the firmware's PKI path
  (`sendData(pkiEncrypted=True)`), so the channel is just a routing slot.

PKI requires the recipient's public key to be known to your node (Meshtastic firmware
2.5+). A directed message _without_ `pki` (`meshtastic_send_text` with `dest_id` but no
`pki`) is only channel-PSK encrypted — addressed to one node, but readable by anyone on
that channel.

**Reliable delivery + confirmation:** sends request an ack by default (`want_ack=true`), so
the firmware retries on lossy multi-hop links. For **direct messages** the call also blocks
briefly for the firmware's ack/nak and reports it in an `ack` field:

- `{"status": "delivered", "reason": "NONE"}` — confirmed delivered
- `{"status": "failed", "reason": "MAX_RETRANSMIT"}` — no ack after retries
- `{"status": "no_ack", "reason": "TIMEOUT"}` — no response within `ack_timeout` (default 15s)

In the REPL, `dm` prints this `ack` block directly. Broadcasts don't block (no single
recipient). Tune with `wait_ack` / `ack_timeout`, or `want_ack=false` for fire-and-forget.

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
