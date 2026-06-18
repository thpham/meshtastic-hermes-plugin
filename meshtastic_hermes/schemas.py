"""Tool schemas — what the LLM sees when deciding to call a tool."""

CONNECT = {
    "name": "meshtastic_connect",
    "description": (
        "Connect to a Meshtastic node over TCP/IP. Opens the link and begins "
        "observing all mesh traffic into the knowledge base. If no host is given, "
        "uses the MESHTASTIC_HOST environment variable. Call this before any other "
        "Meshtastic tool."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "Node host/IP, e.g. '192.168.1.50'. Optional if MESHTASTIC_HOST is set."},
            "port": {"type": "integer", "description": "TCP port (default 4403)."},
        },
        "required": [],
    },
}

DISCONNECT = {
    "name": "meshtastic_disconnect",
    "description": "Close the active Meshtastic connection and stop observing traffic.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

SEND_TEXT = {
    "name": "meshtastic_send_text",
    "description": (
        "Send a text message over the mesh. Encryption depends on the arguments:\n"
        "- Broadcast (no dest_id): goes to everyone on the channel, encrypted with that "
        "channel's pre-shared key. On the default Primary channel that key is public, so "
        "treat plain channel sends as NON-private.\n"
        "- Direct to a node (dest_id) WITHOUT pki: still only channel-PSK encrypted — not "
        "private from other channel members.\n"
        "- Direct to a node with pki=true: end-to-end public-key encryption (Curve25519) to "
        "that node only. Use this for private direct messages. Requires the recipient's key "
        "to be known to the radio (firmware 2.5+)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Message body to send."},
            "channel_index": {"type": "integer", "description": "Channel index (default 0 / Primary). For pki sends this is only the routing slot, not the encryption key."},
            "dest_id": {"type": "string", "description": "Destination node id like '!a1b2c3d4'. Omit to broadcast to the channel."},
            "pki": {"type": "boolean", "description": "Encrypt end-to-end to the recipient's public key (requires dest_id). Use for private direct messages."},
            "want_ack": {"type": "boolean", "description": "Request reliable delivery (firmware retries + ack/nak). Default true; set false for fire-and-forget."},
            "wait_ack": {"type": "boolean", "description": "Block until the firmware confirms delivery, returning the result in the 'ack' field (status: delivered | failed | no_ack). Defaults true for direct messages (dest_id), false for broadcasts."},
            "ack_timeout": {"type": "number", "description": "Seconds to wait for the ack when wait_ack is set (default 15)."},
        },
        "required": ["text"],
    },
}

RECENT_MESSAGES = {
    "name": "meshtastic_recent_messages",
    "description": (
        "Return recently received TEXT messages we were able to decode (on channels "
        "we hold keys for). Encrypted private-channel messages are never decoded and "
        "do not appear here."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max messages to return (default 20)."},
        },
        "required": [],
    },
}

LIST_NODES = {
    "name": "meshtastic_list_nodes",
    "description": "List nodes currently known to the connected radio (live node DB): id, names, SNR, last heard, position.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max nodes to return (default 50)."},
        },
        "required": [],
    },
}

NODE_INFO = {
    "name": "meshtastic_node_info",
    "description": "Detailed info for one node from the live radio DB. Returns the local node when node_id is omitted.",
    "parameters": {
        "type": "object",
        "properties": {
            "node_id": {"type": "string", "description": "Node id like '!a1b2c3d4'. Omit for the local node."},
        },
        "required": [],
    },
}

LIST_CHANNELS = {
    "name": "meshtastic_list_channels",
    "description": "List the configured channels on the local node (index, name, role). Does not reveal PSK secrets.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

DEVICE_METRICS = {
    "name": "meshtastic_device_metrics",
    "description": "Local device metrics: battery level, voltage, channel utilization, uptime, and position if available.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

KB_SUMMARY = {
    "name": "meshtastic_kb_summary",
    "description": (
        "Overview of the node-interaction knowledge base built from observed traffic: "
        "node count, total/encrypted/decoded packet counts, channels seen, and top talkers."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

KB_NODES = {
    "name": "meshtastic_kb_nodes",
    "description": "List nodes recorded in the knowledge base with first/last seen, packet counts, and last signal quality.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max nodes (default 50)."},
            "sort": {"type": "string", "description": "One of: last_seen, first_seen, packets, name.", "enum": ["last_seen", "first_seen", "packets", "name"]},
        },
        "required": [],
    },
}

KB_INTERACTIONS = {
    "name": "meshtastic_kb_interactions",
    "description": (
        "Observed interaction records (packet metadata: from, to, channel, portnum, "
        "encrypted flag, hops, signal). Filter by node and/or by a UNIX timestamp lower bound."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "node_id": {"type": "string", "description": "Restrict to interactions involving this node id."},
            "since": {"type": "number", "description": "Only interactions with ts >= this UNIX timestamp."},
            "limit": {"type": "integer", "description": "Max records (default 100)."},
        },
        "required": [],
    },
}

KB_NEIGHBORS = {
    "name": "meshtastic_kb_neighbors",
    "description": (
        "Inferred direct contacts of a node: the counterpart nodes it has exchanged "
        "packets with, ranked by interaction count. Useful for mapping mesh relationships."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "node_id": {"type": "string", "description": "Node id like '!a1b2c3d4'."},
            "limit": {"type": "integer", "description": "Max neighbors (default 50)."},
        },
        "required": ["node_id"],
    },
}
