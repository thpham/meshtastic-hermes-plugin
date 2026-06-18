---
name: mesh-recon
description: Map mesh nodes and relationships from observed traffic.
version: 0.1.0
author: Thomas Pham
platforms: [linux, macos]
metadata:
  hermes:
    tags: [meshtastic, mesh, reconnaissance, knowledge-base]
    category: networking
---

# Mesh Recon Skill

Build a picture of a Meshtastic mesh — which nodes exist, how active they are, and who
exchanges packets with whom — from passively observed traffic. It reads packet *metadata*
only and never decrypts private channels, so the map still covers encrypted traffic. It
does not modify the mesh or send anything.

## When to Use

- "Map the mesh", "who's on the network", "who talks to whom".
- Investigating a node's neighbors or activity level.
- Summarizing mesh activity over a window of time.

## Prerequisites

- The `meshtastic` plugin loaded and a reachable node (`MESHTASTIC_HOST`, or ask to connect).
- Observation time: the knowledge base fills only while connected — let it run.

## Quick Reference

- `meshtastic_connect` — open the link and start observing.
- `meshtastic_kb_summary` — totals, channels seen, top talkers.
- `meshtastic_kb_nodes` — known nodes (sort by last_seen/first_seen/packets/name).
- `meshtastic_kb_neighbors` — a node's inferred direct contacts (by interaction count).
- `meshtastic_kb_interactions` — raw interaction metadata (filter by node / since).
- `meshtastic_list_nodes` — the radio's live node DB (names, SNR, position).

## Procedure

1. Connect with `meshtastic_connect` (skip if already connected).
2. Let the knowledge base accumulate — observation is passive and ongoing. On a fresh
   connection, allow some minutes of traffic before drawing conclusions.
3. Start broad with `meshtastic_kb_summary`: node count, packet totals (note the
   encrypted-vs-decoded split), channels seen, top talkers.
4. Enumerate with `meshtastic_kb_nodes` (sort `packets` for the busiest, `last_seen` for
   who's active now). Cross-reference identities with `meshtastic_list_nodes`.
5. For a node of interest, call `meshtastic_kb_neighbors` with its id for direct contacts
   ranked by interaction count, and `meshtastic_kb_interactions` (filter `node_id`,
   optionally `since`) for the underlying records.
6. Infer relationships from counts and recency — frequent, recent exchanges suggest a real
   link; a `^all` peer is broadcast traffic, not a 1:1 contact.

## Pitfalls

- Encrypted packets on channels you lack keys for are metadata-only — you can see THAT two
  nodes exchanged a packet, never its contents. Never claim to read them.
- A node only appears once it has been heard; absence is not proof of absence.
- Counts are since-observation, not all-time, unless the KB persisted across runs.

## Verification

`meshtastic_kb_summary` returns non-zero `nodes`/`packets`, and `meshtastic_kb_neighbors`
returns ranked peers for an active node.
