# Usage

## Prerequisites

- A Meshtastic node reachable over TCP/IP (WiFi-enabled ESP32 firmware, or `meshtasticd`).
  Default port is `4403`.
- Hermes installed, with this plugin linked/installed and **enabled**
  (`just link && just enable`, or `hermes plugins enable meshtastic`).

## Quick start

1. **Optionally** set a default node so the plugin auto-connects each session:

   ```bash
   export MESHTASTIC_HOST=192.168.1.50
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
  "arguments": { "host": "192.168.1.50", "port": 4403 }
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

## CLI

Outside a chat session:

```bash
hermes meshtastic status       # connection status as JSON
hermes meshtastic kb-summary   # KB summary as JSON
```

## Troubleshooting

- **Plugin not listed** — run `just hermes-debug` (`HERMES_PLUGINS_DEBUG=1 hermes plugins
list`) for verbose discovery logs; ensure it's in `plugins.enabled` in `~/.hermes/config.yaml`.
- **`radio_unavailable` error from a tool** — the `meshtastic` package is missing from
  Hermes' Python environment (happens with bare directory-drop installs). Install it there:
  `pip install meshtastic` (pip-based installs of this package pull it automatically).
- **Connect fails** — verify the node IP and that TCP port `4403` is reachable
  (`nc -z <host> 4403`).
