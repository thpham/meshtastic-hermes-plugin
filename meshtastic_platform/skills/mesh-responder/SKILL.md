---
name: mesh-responder
description: Reply briefly and safely to incoming mesh messages.
version: 0.1.0
author: Thomas Pham
platforms: [linux, macos]
metadata:
  hermes:
    tags: [meshtastic, gateway, messaging, etiquette]
    category: networking
---

# Mesh Responder Skill

How to behave when chatting over a Meshtastic LoRa mesh via the gateway: keep replies tiny,
plain, and well-targeted. The mesh is extremely low-bandwidth and high-latency, so
verbosity costs airtime for everyone. This is etiquette guidance, not a tool workflow —
your reply text is sent back over the radio automatically by the adapter.

## When to Use

Whenever you receive a message through the Meshtastic gateway — a direct message to the
node, or a message on an allowed channel.

## Prerequisites

- The `meshtastic-platform` gateway adapter is running and routing inbound messages.

## Quick Reference

- Reply length: aim for one short line; hard cap ~200 bytes per message.
- Format: plain text only — no markdown, no code fences, minimal punctuation.
- Optional identity lookups: `meshtastic_kb_neighbors` / `meshtastic_kb_nodes` to recall
  who a sender is.

## Procedure

1. Read the inbound message and answer the actual question in the fewest words possible.
2. Prefer a single message. If you must split, keep each part standalone and short.
3. Match the channel context: a DM is private (end-to-end); a channel reply is visible to
   everyone on that channel — never echo private details onto a channel.
4. Do not reply to your own messages or to acknowledgements — avoid loops.
5. If you cannot help, say so in one line rather than a long apology.

## Pitfalls

- Long, chatty, or markdown-formatted replies waste airtime and may be truncated or split.
- Replying on a public channel leaks anything you say to all of its members.
- Multi-hop delivery is lossy; do not assume the peer received earlier context.

## Verification

Replies are single short plain-text lines appropriate to the channel — no markdown, no
loops, no private content leaked onto channels.
