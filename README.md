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

## How it fits Hermes

Per the [plugin guide](https://hermes-agent.nousresearch.com/docs/guides/build-a-hermes-plugin),
this is a standard Python plugin:

```
meshtastic_hermes/
├── plugin.yaml      # manifest (name: meshtastic)
├── __init__.py      # register(ctx) — wires tools, hooks, slash + CLI commands
├── schemas.py       # tool schemas (what the LLM sees)
├── tools.py         # tool handlers (return JSON strings, never raise)
├── connection.py    # ConnectionManager singleton (TCPInterface + pubsub)
├── observer.py      # receive handler → knowledge base + recent-text buffer
└── knowledge.py     # NodeGraph: SQLite store of nodes + interactions
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
into the Python package set so it builds against the *same* Python your Hermes service
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

| Variable               | Purpose                                            | Default                          |
| ---------------------- | -------------------------------------------------- | -------------------------------- |
| `MESHTASTIC_HOST`      | Node host/IP for TCP auto-connect on session start | _unset_ (no auto-connect)        |
| `MESHTASTIC_HERMES_DB` | SQLite knowledge-base path                         | `$HERMES_HOME/meshtastic_kb.sqlite` (next to Hermes' config), else `~/.hermes/meshtastic_kb.sqlite` |

When `MESHTASTIC_HOST` is set, the plugin auto-connects (and starts observing) on each
new session; otherwise call `meshtastic_connect` explicitly.

The KB path is resolved in priority order: `MESHTASTIC_HERMES_DB` → `$HERMES_HOME`
(Hermes' own home, e.g. `/var/lib/hermes/.hermes` under the NixOS service) → systemd's
`$STATE_DIRECTORY` → `~/.hermes/`.

## Tools

| Tool                         | Description                                                       |
| ---------------------------- | ----------------------------------------------------------------- |
| `meshtastic_connect`         | Open TCP link to a node (uses `MESHTASTIC_HOST` if no host given) |
| `meshtastic_disconnect`      | Close the link, stop observing                                    |
| `meshtastic_send_text`       | Send text to a channel (or direct to a node via `dest_id`)        |
| `meshtastic_recent_messages` | Recently decoded TEXT messages (never encrypted content)          |
| `meshtastic_list_nodes`      | Nodes from the live radio DB                                      |
| `meshtastic_node_info`       | Detail for one node (local node if omitted)                       |
| `meshtastic_list_channels`   | Configured channels (index, name, role — no PSK secrets)          |
| `meshtastic_device_metrics`  | Local battery, voltage, utilization, uptime, position             |
| `meshtastic_kb_summary`      | KB overview: nodes, packet counts, channels, top talkers          |
| `meshtastic_kb_nodes`        | Recorded nodes with first/last seen, counts, signal               |
| `meshtastic_kb_interactions` | Observed interaction metadata (filterable by node / time)         |
| `meshtastic_kb_neighbors`    | Inferred direct contacts of a node, ranked by interaction count   |

It also registers a `/meshtastic` slash command (status + KB summary) and a
`hermes meshtastic <status|kb-summary>` CLI command.

## Development

```bash
just test               # unit tests (no radio required)
just lint               # ruff
just check              # import sanity
just standalone list    # run the plugin without Hermes (see docs/usage.md)
```

See [docs/architecture.md](docs/architecture.md) and [docs/usage.md](docs/usage.md).
