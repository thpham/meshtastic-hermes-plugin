---
name: messaging-safety
description: "Send mesh text safely: broadcast, channel, or encrypted DM."
version: 0.1.0
author: Thomas Pham
platforms: [linux, macos]
metadata:
  hermes:
    tags: [meshtastic, messaging, encryption, privacy]
    category: networking
---

# Messaging Safety Skill

Send Meshtastic text without leaking it or flooding the wrong audience. Picks the right
delivery and encryption for the situation and confirms delivery. It does not read other
people's private channels.

## When to Use

- Any time you send a message: "tell node X ...", "post to channel ...", "DM ...".
- Especially when privacy matters or the message is directed at one person.

## Prerequisites

- The `meshtastic` plugin loaded and connected (`meshtastic_connect`).
- Know the target: a channel index (from `meshtastic_list_channels`) or a node id.

## Quick Reference

- `meshtastic_list_channels` — channel indices, names, roles (index 0 = Primary/public).
- `meshtastic_send_text` — send; key args:
  - `text` (required)
  - `channel_index` — broadcast on this channel (default 0 = public Primary)
  - `dest_id` — direct to one node
  - `pki=true` — end-to-end encrypt to that node (private DM; requires `dest_id`)
  - `want_ack` (default true) — the result's `ack` reports delivery

## Procedure

1. Decide the audience:
   - **Everyone on a channel** → broadcast: set `channel_index`. Confirm the index with
     `meshtastic_list_channels` first.
   - **One person, privately** → `dest_id` + `pki=true` (end-to-end, Curve25519).
   - **One person, on a shared channel (not private)** → `dest_id` without `pki`.
2. Avoid accidental public flooding: channel 0 (Primary) usually uses the well-known public
   key, so anyone can read it. Prefer a private channel index or a PKI DM for anything
   sensitive. Never put secrets on Primary.
3. Send with `meshtastic_send_text`. For directed messages, check the returned `ack`:
   `delivered` = confirmed; `no_ack`/`failed` = it may not have arrived (lossy multi-hop
   links drop packets — consider retrying).
4. Report what you sent, to whom, on which channel, and the encryption used.

## Pitfalls

- `pki=true` requires `dest_id` and the recipient's key known to the node (firmware 2.5+).
- A directed message WITHOUT `pki` is still readable by everyone on that channel.
- Broadcasts have no single recipient, so they get no delivery ack — don't wait for one.

## Verification

For a DM, `meshtastic_send_text` returns `"ack": {"status": "delivered"}`. For a channel
send, it returns `"sent": true` with the chosen `channel_index`.
