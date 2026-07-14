from __future__ import annotations

import socket
import socketserver
import threading
import unittest

from services.proxy_bridge_service import ProxyBridgeServer, _bridge_settings


class EchoHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        data = self.request.recv(1024)
        self.request.sendall(data)


class ProxyBridgeServiceTests(unittest.TestCase):
    def test_settings_use_safe_defaults(self) -> None:
        settings = _bridge_settings({"enabled": True})
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["listen_port"], 17890)
        self.assertEqual(settings["upstream_port"], 7890)
        self.assertIn("192.168.0.0/16", settings["allowed_networks"])

    def test_bridge_relays_loopback_traffic(self) -> None:
        upstream = socketserver.ThreadingTCPServer(("127.0.0.1", 0), EchoHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        bridge = ProxyBridgeServer(
            ("127.0.0.1", 0),
            ("127.0.0.1", upstream.server_address[1]),
            ["192.168.0.0/16"],
        )
        bridge_thread = threading.Thread(target=bridge.serve_forever, daemon=True)
        bridge_thread.start()
        try:
            with socket.create_connection(bridge.server_address, timeout=2) as client:
                client.sendall(b"ping")
                self.assertEqual(client.recv(4), b"ping")
        finally:
            bridge.shutdown()
            bridge.server_close()
            upstream.shutdown()
            upstream.server_close()
            bridge_thread.join(timeout=2)
            upstream_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
