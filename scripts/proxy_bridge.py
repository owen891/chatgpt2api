"""将仅监听环回地址的本地代理桥接给 Docker Desktop 容器。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.proxy_bridge_service import ProxyBridgeServer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=17890)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, default=7890)
    parser.add_argument("--allow-network", action="append", default=["192.168.65.0/24"])
    args = parser.parse_args()

    with ProxyBridgeServer(
        (args.listen_host, args.listen_port),
        (args.upstream_host, args.upstream_port),
        args.allow_network,
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
