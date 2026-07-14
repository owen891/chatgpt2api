"""为 Docker Desktop 容器托管本机环回代理桥接。"""

from __future__ import annotations

import ipaddress
import select
import socket
import socketserver
import threading
from typing import Any

from services.config import config


class ProxyBridgeHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client_ip = ipaddress.ip_address(self.client_address[0])
        server = self.server
        allowed_networks = getattr(server, "allowed_networks", ())
        allowed = client_ip.is_loopback or client_ip.is_private or any(
            client_ip in network for network in allowed_networks
        )
        if not allowed:
            return

        upstream_address = getattr(server, "upstream")
        try:
            with socket.create_connection(upstream_address, timeout=10) as upstream:
                sockets = (self.request, upstream)
                while True:
                    readable, _, _ = select.select(sockets, (), (), 30)
                    if not readable:
                        continue
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        target = upstream if source is self.request else self.request
                        target.sendall(data)
        except (OSError, TimeoutError):
            return


class ProxyBridgeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, listen: tuple[str, int], upstream: tuple[str, int], allowed_networks: list[str]):
        self.upstream = upstream
        self.allowed_networks = tuple(ipaddress.ip_network(value) for value in allowed_networks)
        super().__init__(listen, ProxyBridgeHandler)


def _bridge_settings(raw: object) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    networks = source.get("allowed_networks")
    if not isinstance(networks, list):
        networks = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
    return {
        "enabled": bool(source.get("enabled")),
        "listen_host": str(source.get("listen_host") or "0.0.0.0").strip(),
        "listen_port": max(1, min(65535, int(source.get("listen_port") or 17890))),
        "upstream_host": str(source.get("upstream_host") or "127.0.0.1").strip(),
        "upstream_port": max(1, min(65535, int(source.get("upstream_port") or 7890))),
        "allowed_networks": [str(value).strip() for value in networks if str(value).strip()],
    }


class ProxyBridgeService:
    def __init__(self) -> None:
        self._server: ProxyBridgeServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def start(self) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            settings = _bridge_settings(config.data.get("proxy_bridge"))
            if not settings["enabled"]:
                return False
            try:
                self._server = ProxyBridgeServer(
                    (settings["listen_host"], settings["listen_port"]),
                    (settings["upstream_host"], settings["upstream_port"]),
                    settings["allowed_networks"],
                )
            except OSError as exc:
                print(f"[proxy-bridge] 启动失败: {exc}")
                self._server = None
                return False
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                kwargs={"poll_interval": 0.5},
                daemon=True,
                name="proxy-bridge",
            )
            self._thread.start()
            print(
                f"[proxy-bridge] {settings['listen_host']}:{settings['listen_port']}"
                f" -> {settings['upstream_host']}:{settings['upstream_port']}"
            )
            return True

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)


proxy_bridge_service = ProxyBridgeService()
