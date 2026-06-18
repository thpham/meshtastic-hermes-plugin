# Meshtastic Hermes Plugin

A [Hermes Agent](https://hermes-agent.nousresearch.com/) plugin that lets the agent
interact with a [Meshtastic](https://meshtastic.org/) LoRa mesh over **TCP/IP**.

It provides three groups of tools:

- **Messaging** — connect, send text (broadcast or direct), read recently decoded messages.
- **Network inspection** — list nodes/channels, query node details and local device metrics.
- **Node-interaction knowledge base** — a persistent SQLite store built by passively
  observing _all_ mesh traffic. It records packet **metadata** (who transmitted, who
  they addressed, channel, port, hop count, SNR/RSSI, timestamps) so the agent can infer
  how nodes relate and how active the mesh is.

> **Privacy by design.** The plugin **never decrypts** traffic. Packets on private
> channels you don't hold keys for are recorded as metadata only — their contents are
> never read or stored. Only TEXT messages we can already decode (on channels the radio
> holds keys for) are surfaced via `meshtastic_recent_messages`.

It also ships a **bidirectional gateway** (Hermes platform adapter) so inbound mesh
messages can drive the agent and its replies go back out over the radio — see
[Bidirectional gateway](#bidirectional-gateway-hermes-platform-adapter).

## How it fits Hermes

Per the [plugin guides](https://hermes-agent.nousresearch.com/docs/guides/build-a-hermes-plugin),
this repo ships **two** Hermes plugins:

1. `meshtastic` (`meshtastic_hermes/`) — a tools/hooks plugin: the 12 tools, the
   knowledge base, the `/meshtastic` slash command and CLI.
2. `meshtastic-platform` (`meshtastic_platform/`) — a `kind: platform` **gateway
   adapter** so the mesh can drive the agent bidirectionally (see
   [Bidirectional gateway](#bidirectional-gateway-hermes-platform-adapter)).

```
meshtastic_hermes/        # tools plugin (name: meshtastic)
├── plugin.yaml           # manifest
├── __init__.py           # register(ctx) — wires tools, hooks, slash + CLI commands
├── schemas.py            # tool schemas (what the LLM sees)
├── tools.py              # tool handlers (return JSON strings, never raise)
├── connection.py         # ConnectionManager singleton (TCPInterface + pubsub)
├── observer.py           # receive handler → knowledge base + recent-text buffer
├── knowledge.py          # NodeGraph: SQLite store of nodes + interactions
├── gateway_bridge.py     # pure inbound/outbound mapping + reply policy (shared)
└── __main__.py           # standalone harness: list/call/repl/observe/bridge

meshtastic_platform/      # gateway adapter plugin (kind: platform)
├── plugin.yaml           # manifest (kind: platform)
├── __init__.py           # register(ctx) → ctx.register_platform(...)
└── adapter.py            # MeshtasticAdapter(BasePlatformAdapter)
```

The `meshtastic` radio library is a **hard dependency**, so any pip-based install pulls
it automatically into Hermes' Python environment. (The handlers still import-guard it, so
a bare directory-drop install without a pip step loads and degrades gracefully rather than
crashing.)

## Install

> **How the dependency is installed:** Hermes plugins import into the _same_ Python
> environment the `hermes` process runs under — there is no per-plugin venv. So installing
> the `meshtastic` dependency means `pip install`-ing this package into that environment.
> Any pip path below does that automatically. A manual directory-drop (no pip step) does
> **not** install dependencies — run `pip install meshtastic` into Hermes' env yourself.
> Hermes' `lazy_deps` auto-installer is **not** usable here: it only installs packages on
> its maintainer-curated in-tree allowlist, which a third-party `meshtastic` key isn't on.

### On NixOS (flake) — recommended for deployment

This plugin ships the `hermes_agent.plugins` entry point, so it plugs into Hermes'
[`extraPythonPackages`](https://hermes-agent.nousresearch.com/docs/getting-started/nix-setup/)
option (a list of packages). The flake's **overlay** injects `meshtastic-hermes-plugin`
into the Python package set so it builds against the _same_ Python your Hermes service
uses (the overlay populates `python311Packages`, `python312Packages`, … via
`pythonPackagesExtensions` — pick the set matching your Hermes build):

```nix
{
  inputs.hermes-agent.url = "github:NousResearch/hermes-agent";
  inputs.meshtastic-hermes-plugin.url = "github:thpham/meshtastic-hermes-plugin";

  # In your NixOS configuration (module args provide pkgs):
  nixpkgs.overlays = [ inputs.meshtastic-hermes-plugin.overlays.default ];

  services.hermes-agent = {
    enable = true;
    extraPythonPackages = [ pkgs.python3Packages.meshtastic-hermes-plugin ];

    # Enable it here — NOT via `hermes plugins enable`. On NixOS config.yaml is
    # Nix-generated and marked `.managed`, so CLI mutations are blocked.
    settings.plugins.enabled = [ "meshtastic" ];

    # Optional: auto-connect on session start (non-secret env).
    environment.MESHTASTIC_HOST = "192.168.55.73";
  };
}
```

`meshtastic` comes in transitively from nixpkgs (no need to list it separately).
Alternatively, pass the standalone package output directly:
`extraPythonPackages = [ inputs.meshtastic-hermes-plugin.packages.${pkgs.system}.default ];`
— but prefer the overlay so the build matches Hermes' Python ABI.

**Knowledge-base path:** no config needed. The KB resolves to `$HERMES_HOME` (Hermes'
own home — `/var/lib/hermes/.hermes` under the service), so it sits next to Hermes'
`config.yaml`. Override with `MESHTASTIC_HERMES_DB` via `services.hermes-agent.environment`
if you want it elsewhere. See [Configuration](#configuration).

### Local development (`nix develop` / direnv)

This repo ships a **reproducible, pip-free** dev shell (`flake.nix` + `.envrc`): every Python
dependency comes from nixpkgs and the working tree is on `PYTHONPATH`, so there's no venv to
manage and edits are picked up immediately.

```bash
direnv allow            # or: nix develop   — enters the shell, deps from nixpkgs
just test               # run the KB unit tests (no radio required)
just lint               # ruff
just link               # symlink meshtastic_hermes → ~/.hermes/plugins/meshtastic
just enable             # add "meshtastic" to plugins.enabled in ~/.hermes/config.yaml
just hermes-debug       # HERMES_PLUGINS_DEBUG=1 hermes plugins list  (verify discovery)
```

> On **macOS** the first shell entry builds `meshtastic` from source (it isn't in the
> binary cache for Darwin); subsequent entries are instant. On Linux it's fetched prebuilt.

### As a pip package (non-Nix)

```bash
pip install .                     # installs the entry point AND the meshtastic dependency
hermes plugins enable meshtastic  # plugins are disabled by default
```

## Configuration

Two optional environment variables (prompted during `hermes plugins install`):

| Variable               | Purpose                                            | Default                                                                                             |
| ---------------------- | -------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `MESHTASTIC_HOST`      | Node host/IP for TCP auto-connect on session start | _unset_ (no auto-connect)                                                                           |
| `MESHTASTIC_HERMES_DB` | SQLite knowledge-base path                         | `$HERMES_HOME/meshtastic_kb.sqlite` (next to Hermes' config), else `~/.hermes/meshtastic_kb.sqlite` |

When `MESHTASTIC_HOST` is set, the plugin auto-connects (and starts observing) on each
new session; otherwise call `meshtastic_connect` explicitly.

The KB path is resolved in priority order: `MESHTASTIC_HERMES_DB` → `$HERMES_HOME`
(Hermes' own home, e.g. `/var/lib/hermes/.hermes` under the NixOS service) → systemd's
`$STATE_DIRECTORY` → `~/.hermes/`.

## Tools

| Tool                         | Description                                                                                    |
| ---------------------------- | ---------------------------------------------------------------------------------------------- |
| `meshtastic_connect`         | Open TCP link to a node (uses `MESHTASTIC_HOST` if no host given)                              |
| `meshtastic_disconnect`      | Close the link, stop observing                                                                 |
| `meshtastic_send_text`       | Send text: broadcast (channel-PSK), or private DM to a node (`dest_id` + `pki` for end-to-end) |
| `meshtastic_recent_messages` | Recently decoded TEXT messages (never encrypted content)                                       |
| `meshtastic_list_nodes`      | Nodes from the live radio DB                                                                   |
| `meshtastic_node_info`       | Detail for one node (local node if omitted)                                                    |
| `meshtastic_list_channels`   | Configured channels (index, name, role — no PSK secrets)                                       |
| `meshtastic_device_metrics`  | Local battery, voltage, utilization, uptime, position                                          |
| `meshtastic_kb_summary`      | KB overview: nodes, packet counts, channels, top talkers                                       |
| `meshtastic_kb_nodes`        | Recorded nodes with first/last seen, counts, signal                                            |
| `meshtastic_kb_interactions` | Observed interaction metadata (filterable by node / time)                                      |
| `meshtastic_kb_neighbors`    | Inferred direct contacts of a node, ranked by interaction count                                |

It also registers a `/meshtastic` slash command (status + KB summary) and a
`hermes meshtastic <status|kb-summary>` CLI command.

## Bidirectional gateway (Hermes platform adapter)

Beyond the tools plugin, this repo ships a **platform adapter** (`kind: platform`,
package `meshtastic_platform`) that turns the mesh into a first-class Hermes gateway
channel: inbound mesh text **drives the agent**, and the agent's replies are sent back
over the radio. It mirrors Hermes' bundled adapters (e.g. IRC) and reuses this repo's
connection/observer/KB code.

- **Reply policy:** direct messages only by default (avoids channel spam and bot loops).
  Opt specific channels in with `MESHTASTIC_REPLY_CHANNELS="1,2"` (e.g. your private
  channels — public Primary/0 stays silent unless listed), or `MESHTASTIC_REPLY_ALL=true`
  for every channel.
- **Encryption:** replies to a DM go out **end-to-end (PKI)** to the sender; channel
  replies use the channel key. Opaque/undecryptable traffic is never answered.
- **Reachability:** the adapter only sees messages addressed to the node it's connected
  to, that actually arrive over the air — multi-hop DMs are often lost on lossy links.

### Enable the gateway on NixOS

It's a _separate_ plugin from the tools plugin, so enable it by its own name and configure
it via the service environment:

```nix
{ pkgs, ... }:
{
  nixpkgs.overlays = [ inputs.meshtastic-hermes-plugin.overlays.default ];
  services.hermes-agent = {
    enable = true;
    extraPythonPackages = [ pkgs.python3Packages.meshtastic-hermes-plugin ];
    # Enable the tools plugin and/or the gateway adapter (both come from this package):
    settings.plugins.enabled = [ "meshtastic" "meshtastic-platform" ];

    environment.MESHTASTIC_HOST = "192.168.55.73";   # node to connect to
    environment.MESHTASTIC_REPLY_CHANNELS = "1";     # DMs + channel 1 (omit for DMs only)
    # environment.MESHTASTIC_REPLY_ALL = "true";     # or: reply on every channel
  };
}
```

For local dev: `just link-platform` then add `meshtastic-platform` to `plugins.enabled`.

### Simulate the loop without Hermes

The inbound→reply routing lives in [gateway_bridge.py](meshtastic_hermes/gateway_bridge.py)
(pure + unit-tested) so it's shared by the adapter and a **REPL simulator**:

```bash
# Watch inbound DMs and print the reply the agent WOULD send (no transmit):
python -m meshtastic_hermes bridge 192.168.55.73        # or: just standalone bridge ...
# Reply on DMs + your private channel(s), and actually transmit (echo responder):
python -m meshtastic_hermes bridge 192.168.55.73 --channels 1 --send
# Or every channel incl. public Primary:
python -m meshtastic_hermes bridge 192.168.55.73 --all
```

It prints a line per matched message, e.g.:

```
[inbound DM] !a696579c: 'hello tom'
  -> reply to !a696579c: 'ack: hello tom'   (dry-run — pass --send to actually transmit)
```

The simulator's `simulate_reply()` is a stub echo — swap it for an LLM/webhook to
prototype an autonomous mesh bot before wiring up the full Hermes adapter. See
[docs/usage.md](docs/usage.md) for the full walkthrough.

## Development

```bash
just test               # unit tests (no radio required)
just lint               # ruff
just check              # import sanity
just standalone list    # run the plugin without Hermes (see docs/usage.md)
```

See [docs/architecture.md](docs/architecture.md) and [docs/usage.md](docs/usage.md).
