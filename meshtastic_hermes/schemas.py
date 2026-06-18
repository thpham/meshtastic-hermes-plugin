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
        "Send a text message over the mesh. Broadcasts to a channel by default, or "
        "directs the message to a specific node when dest_id is given."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Message body to send."},
            "channel_index": {"type": "integer", "description": "Channel index to send on (default 0 / primary)."},
            "dest_id": {"type": "string", "description": "Destination node id like '!a1b2c3d4'. Omit to broadcast."},
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
