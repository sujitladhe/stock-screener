"""
ws_manager.py — tracks connected browser WebSocket clients.

Two kinds of outgoing messages now exist, and they need different
delivery:
  - broadcast(): sent to EVERY connected browser -- used for the
    shared screener feed, where all users see the same data.
  - send_to_client(client_id, ...): sent ONLY to that specific user's
    connection(s) -- used for personal alerts (requirement 9). Sending
    a user's own alert to everyone else connected would be a real
    privacy bug, not just noise, so this needed its own path rather
    than reusing broadcast().

Every message now includes a "type" field ("screener_alert" or
"user_alert") so the frontend can route it to the right handler
(update the live table vs. fire a browser notification + sound).

A single connection is registered in BOTH self.active_connections
(for broadcasts) and, if we could identify the connecting user,
self.connections_by_client (for targeted sends) -- one physical
WebSocket serves both purposes, rather than requiring two separate
connections per browser tab.
"""

import json

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections = []
        self.connections_by_client = {}

    async def connect(self, websocket: WebSocket, client_id: str = None):
        await websocket.accept()
        self.active_connections.append(websocket)
        if client_id:
            self.connections_by_client.setdefault(client_id, []).append(websocket)
        print(f"[ws_manager] Client connected (client_id={client_id}). "
              f"Total active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        for client_id, conns in list(self.connections_by_client.items()):
            if websocket in conns:
                conns.remove(websocket)
                if not conns:
                    del self.connections_by_client[client_id]
        print(f"[ws_manager] Client disconnected. Total active connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Sends to every connected browser -- used for the shared screener feed."""
        message.setdefault("type", "screener_alert")
        print(f"[ws_manager] Broadcasting to {len(self.active_connections)} connection(s): {message.get('trading_symbol')}")

        dead_connections = []
        payload = json.dumps(message)
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception as e:
                print(f"[ws_manager] Send failed for a connection ({e}) -- marking dead.")
                dead_connections.append(connection)

        for dead in dead_connections:
            self.disconnect(dead)

    async def send_to_client(self, client_id: str, message: dict):
        """
        Sends ONLY to the given user's connection(s) -- used for
        personal alerts, never the shared screener feed. If the user
        has no open connection right now (e.g. app not open in any
        browser tab), this silently does nothing -- the alert is still
        recorded in alert_history regardless, so nothing is lost, just
        not delivered live.
        """
        message.setdefault("type", "user_alert")
        connections = self.connections_by_client.get(client_id, [])
        print(f"[ws_manager] Sending user_alert to client_id={client_id}: {len(connections)} connection(s)")

        dead_connections = []
        payload = json.dumps(message)
        for connection in connections:
            try:
                await connection.send_text(payload)
            except Exception as e:
                print(f"[ws_manager] Send failed for client {client_id} ({e}) -- marking dead.")
                dead_connections.append(connection)

        for dead in dead_connections:
            self.disconnect(dead)


# One shared instance for the whole app -- imported by both the
# WebSocket endpoint (routers/screener.py) and the live engine
# (ws_client.py, alert_engine integration).
manager = ConnectionManager()
