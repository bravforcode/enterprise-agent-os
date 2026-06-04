"""Lightweight HTTP+token federation for Graxia Tool.

Two pieces:
- FederationServer: stdlib `http.server` that accepts JSON messages from
  peer nodes. Token auth via Authorization: Bearer <token>. No mTLS for
  v0.3.0 (token-only).
- FederationClient: `urllib.request`-based client that POSTs JSON to peers.

Wire format:
- All requests: {"type": <msg_type>, "from": <node_id>, "payload": {...}}
- Responses:   {"ok": bool, "result": {...} | "error": str}

Message types:
- "ping" / "pong": liveness
- "register": peer announces itself, server adds to peer table
- "agent_run": delegate an agent execution to a remote node
- "swarm_query": run a query through a remote swarm
- "heartbeat": periodic keepalive (recorded but no response expected)
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------

MSG_PING = "ping"
MSG_PONG = "pong"
MSG_REGISTER = "register"
MSG_AGENT_RUN = "agent_run"
MSG_SWARM_QUERY = "swarm_query"
MSG_HEARTBEAT = "heartbeat"
MSG_OK = "ok"
MSG_ERR = "error"


@dataclass
class FederationMessage:
    type: str
    from_node: str
    payload: Dict[str, Any] = field(default_factory=dict)
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "from": self.from_node,
            "payload": self.payload,
            "msg_id": self.msg_id,
            "timestamp_ms": self.timestamp_ms,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FederationMessage":
        return FederationMessage(
            type=str(d.get("type", "")),
            from_node=str(d.get("from", "")),
            payload=dict(d.get("payload", {}) or {}),
            msg_id=str(d.get("msg_id", uuid.uuid4())),
            timestamp_ms=int(d.get("timestamp_ms", int(time.time() * 1000))),
        )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


@dataclass
class Peer:
    node_id: str
    host: str
    port: int
    last_seen_ms: int = 0


class FederationServer:
    """Token-authenticated HTTP federation server.

    Handlers are registered per message type. Default handlers respond to
    ping/register/heartbeat. Application code can register `agent_run`
    and `swarm_query` handlers to actually execute delegated work.
    """

    def __init__(
        self,
        node_id: Optional[str] = None,
        host: str = "127.0.0.1",
        port: int = 0,
        token: Optional[str] = None,
    ):
        self.node_id = node_id or f"node-{uuid.uuid4().hex[:8]}"
        self.host = host
        self.port = int(port)
        self.token = token or uuid.uuid4().hex
        self.peers: Dict[str, Peer] = {}
        self.handlers: Dict[str, Callable[[FederationMessage], Dict[str, Any]]] = {}
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._stats = {
            "requests": 0,
            "accepted": 0,
            "rejected": 0,
            "started_at": int(time.time()),
        }

        # Default handlers
        self.handlers[MSG_PING] = self._handle_ping
        self.handlers[MSG_REGISTER] = self._handle_register
        self.handlers[MSG_HEARTBEAT] = self._handle_heartbeat
        self.handlers[MSG_PONG] = self._handle_pong

    # --- Handler registration ------------------------------------------------

    def register_handler(
        self,
        msg_type: str,
        handler: Callable[[FederationMessage], Dict[str, Any]],
    ) -> None:
        self.handlers[msg_type] = handler

    def _handle_ping(self, msg: FederationMessage) -> Dict[str, Any]:
        return {"ok": True, "type": MSG_PONG, "node": self.node_id}

    def _handle_pong(self, msg: FederationMessage) -> Dict[str, Any]:
        self._touch_peer(msg.from_node)
        return {"ok": True}

    def _handle_register(self, msg: FederationMessage) -> Dict[str, Any]:
        host = str(msg.payload.get("host", "127.0.0.1"))
        port = int(msg.payload.get("port", 0))
        if msg.from_node and port:
            with self._lock:
                self.peers[msg.from_node] = Peer(
                    node_id=msg.from_node, host=host, port=port,
                    last_seen_ms=int(time.time() * 1000),
                )
        return {"ok": True, "registered": msg.from_node}

    def _handle_heartbeat(self, msg: FederationMessage) -> Dict[str, Any]:
        self._touch_peer(msg.from_node)
        return {"ok": True}

    def _touch_peer(self, node_id: str) -> None:
        with self._lock:
            peer = self.peers.get(node_id)
            if peer:
                peer.last_seen_ms = int(time.time() * 1000)

    # --- HTTP server lifecycle ----------------------------------------------

    def start(self, timeout_s: float = 5.0) -> int:
        """Start the HTTP server in a background thread. Returns bound port."""
        if self._httpd is not None:
            return self.port

        node = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # silence stderr access log
                pass

            def _read_body(self) -> bytes:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0:
                    return b""
                return self.rfile.read(length)

            def _check_auth(self) -> bool:
                auth = self.headers.get("Authorization", "")
                if not auth.startswith("Bearer "):
                    return False
                token = auth[len("Bearer "):].strip()
                return bool(node.token) and token == node.token

            def _write(self, status: int, body: Dict[str, Any]) -> None:
                payload = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):  # noqa: N802
                if self.path == "/health":
                    self._write(200, {
                        "ok": True,
                        "node": node.node_id,
                        "peers": len(node.peers),
                    })
                    return
                if self.path == "/peers":
                    self._write(200, {
                        "ok": True,
                        "peers": [
                            {
                                "node_id": p.node_id,
                                "host": p.host,
                                "port": p.port,
                                "last_seen_ms": p.last_seen_ms,
                            }
                            for p in node.peers.values()
                        ],
                    })
                    return
                self._write(404, {"ok": False, "error": "not found"})

            def do_POST(self):  # noqa: N802
                node._stats["requests"] += 1
                if not self._check_auth():
                    node._stats["rejected"] += 1
                    self._write(401, {"ok": False, "error": "unauthorized"})
                    return
                try:
                    raw = self._read_body()
                    data = json.loads(raw.decode("utf-8"))
                    msg = FederationMessage.from_dict(data)
                except Exception as e:
                    self._write(400, {"ok": False, "error": f"bad request: {e}"})
                    return

                handler = node.handlers.get(msg.type)
                if not handler:
                    self._write(404, {
                        "ok": False,
                        "error": f"no handler for type '{msg.type}'",
                    })
                    return
                try:
                    result = handler(msg)
                    node._stats["accepted"] += 1
                    self._write(200, {"ok": True, "result": result})
                except Exception as e:
                    self._write(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

        # Bind
        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name=f"federation-{self.node_id}",
            daemon=True,
        )
        self._thread.start()
        # Wait for socket to be ready
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                with socket.create_connection((self.host, self.port), timeout=0.25):
                    return self.port
            except OSError:
                time.sleep(0.05)
        return self.port

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def is_running(self) -> bool:
        return self._httpd is not None

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "node_id": self.node_id,
                "host": self.host,
                "port": self.port,
                "is_running": self.is_running(),
                "peer_count": len(self.peers),
                **self._stats,
            }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class FederationClient:
    """HTTP client for federation. Talks to one or many peer servers."""

    def __init__(self, node_id: str, token: Optional[str] = None, timeout_s: float = 5.0):
        self.node_id = node_id
        self.token = token or ""
        self.timeout_s = timeout_s

    def _post(self, host: str, port: int, msg: FederationMessage) -> Dict[str, Any]:
        url = f"http://{host}:{port}/"
        data = json.dumps(msg.to_dict()).encode("utf-8")
        req = urlrequest.Request(
            url, data=data, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            return {"ok": False, "error": f"http {e.code}: {e.reason}"}
        except URLError as e:
            return {"ok": False, "error": f"url: {e.reason}"}
        except (TimeoutError, OSError) as e:
            return {"ok": False, "error": f"network: {e}"}

    def _get(self, host: str, port: int, path: str = "/health") -> Dict[str, Any]:
        url = f"http://{host}:{port}{path}"
        req = urlrequest.Request(url, method="GET")
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def ping(self, host: str, port: int) -> Dict[str, Any]:
        return self._post(host, port, FederationMessage(
            type=MSG_PING, from_node=self.node_id,
        ))

    def register(
        self, host: str, port: int, advertised_host: str = "127.0.0.1",
        advertised_port: int = 0,
    ) -> Dict[str, Any]:
        return self._post(host, port, FederationMessage(
            type=MSG_REGISTER, from_node=self.node_id,
            payload={"host": advertised_host, "port": advertised_port or port},
        ))

    def send(
        self,
        target: Tuple[str, int],
        message_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        host, port = target
        return self._post(host, port, FederationMessage(
            type=message_type, from_node=self.node_id,
            payload=payload or {},
        ))

    def delegate_agent_run(
        self,
        target: Tuple[str, int],
        agent: str,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.send(target, MSG_AGENT_RUN, {
            "agent": agent, "query": query, "context": context or {},
        })

    def delegate_swarm_query(
        self,
        target: Tuple[str, int],
        swarm_id: str,
        query: str,
    ) -> Dict[str, Any]:
        return self.send(target, MSG_SWARM_QUERY, {
            "swarm_id": swarm_id, "query": query,
        })

    def list_peers(self, target: Tuple[str, int]) -> Dict[str, Any]:
        return self._get(target[0], target[1], "/peers")


# ---------------------------------------------------------------------------
# Peer manager
# ---------------------------------------------------------------------------


class FederationRegistry:
    """Tracks peers this node has discovered."""

    def __init__(self):
        self._peers: Dict[str, Tuple[str, int]] = {}
        self._lock = threading.RLock()

    def add(self, node_id: str, host: str, port: int) -> None:
        with self._lock:
            self._peers[node_id] = (host, int(port))

    def remove(self, node_id: str) -> None:
        with self._lock:
            self._peers.pop(node_id, None)

    def get(self, node_id: str) -> Optional[Tuple[str, int]]:
        with self._lock:
            return self._peers.get(node_id)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {"node_id": k, "host": v[0], "port": v[1]}
                for k, v in self._peers.items()
            ]

    def targets(self) -> List[Tuple[str, int]]:
        with self._lock:
            return list(self._peers.values())


__all__ = [
    "FederationServer",
    "FederationClient",
    "FederationRegistry",
    "FederationMessage",
    "Peer",
    "MSG_PING", "MSG_PONG", "MSG_REGISTER",
    "MSG_AGENT_RUN", "MSG_SWARM_QUERY", "MSG_HEARTBEAT",
]
