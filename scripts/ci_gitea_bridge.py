#!/usr/bin/env python3
"""
Lightweight TCP bridge for Gitea Actions runners.
Resolves and forwards http://gitea:3000 to the host Gitea instance
(probing GATEWAY_IP:8092, GATEWAY_IP:3000, and common Docker bridge addresses).
"""

import os
import select
import socket
import sys
import threading
import time


def probe(host: str, port: int, timeout: float = 0.8) -> bool:
    """Checks if a TCP port is open and responding."""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def get_candidates():
    """Generates candidate host/port targets for the host Gitea service."""
    gw = sys.argv[1] if len(sys.argv) > 1 else os.getenv("GATEWAY_IP", "")
    candidates = []
    if gw:
        candidates.extend([(gw, 8092), (gw, 3000)])
    for sub in ["172.17.0.1", "172.18.0.1", "172.19.0.1", "172.80.0.1", "172.80.3.1"]:
        candidates.extend([(sub, 8092), (sub, 3000)])
    candidates.append(("172.80.3.2", 3000))
    return candidates


def forward(src: socket.socket, dst: socket.socket):
    """Bidirectional streaming between two sockets."""
    try:
        while True:
            r, _, _ = select.select([src, dst], [], [], 60)
            if not r:
                continue
            if src in r:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
            if dst in r:
                data = dst.recv(65536)
                if not data:
                    break
                src.sendall(data)
    except Exception:
        pass
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass


def main():
    candidates = get_candidates()
    target = None
    for host, port in candidates:
        print(f"[Bridge] Probing {host}:{port}...", flush=True)
        if probe(host, port):
            target = (host, port)
            print(f"[Bridge] Found active Gitea service at {host}:{port}!", flush=True)
            break

    if not target:
        gw = sys.argv[1] if len(sys.argv) > 1 else "172.17.0.1"
        target = (gw, 8092)
        print(f"[Bridge] Defaulting to {target[0]}:{target[1]}", flush=True)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 3000))
    server.listen(128)
    print(f"[Bridge] Listening on 127.0.0.1:3000 -> {target[0]}:{target[1]}", flush=True)

    while True:
        try:
            client_sock, _ = server.accept()
            remote_sock = socket.create_connection(target, timeout=10)
            t = threading.Thread(target=forward, args=(client_sock, remote_sock), daemon=True)
            t.start()
        except Exception:
            time.sleep(0.1)


if __name__ == "__main__":
    main()
