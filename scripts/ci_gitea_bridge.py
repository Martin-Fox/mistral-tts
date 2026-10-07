#!/usr/bin/env python3
"""
Lightweight TCP bridge for Gitea Actions runners.
Resolves and forwards http://gitea:3000 to the host Gitea instance
(probing GATEWAY_IP:8092, GATEWAY_IP:3000, and common Docker bridge addresses).
"""

import os
import select
import socket
import struct
import sys
import threading
import time


def get_default_gateway_from_proc(proc_route_path: str = "/proc/net/route") -> str | None:
    """Detects default gateway IP address from /proc/net/route."""
    try:
        if os.path.exists(proc_route_path):
            with open(proc_route_path, "r", encoding="utf-8") as f:
                for line in f:
                    fields = line.strip().split()
                    if len(fields) >= 3 and fields[1] == "00000000":
                        gw_hex = fields[2]
                        if gw_hex == "00000000":
                            continue
                        gw_ip = socket.inet_ntoa(struct.pack("<L", int(gw_hex, 16)))
                        print(f"[Bridge] Detected default gateway from {proc_route_path}: {gw_ip}", flush=True)
                        return gw_ip
    except Exception as exc:
        print(f"[Bridge] Warning: Failed to read {proc_route_path}: {exc}", flush=True)
    return None


def get_gateway() -> str | None:
    """Resolves gateway IP from sys.argv, GATEWAY_IP env var, or /proc/net/route."""
    if len(sys.argv) > 1 and sys.argv[1].strip():
        gw = sys.argv[1].strip()
        print(f"[Bridge] Using gateway from CLI argument: {gw}", flush=True)
        return gw
    env_gw = os.getenv("GATEWAY_IP", "").strip()
    if env_gw:
        print(f"[Bridge] Using gateway from GATEWAY_IP env var: {env_gw}", flush=True)
        return env_gw
    return get_default_gateway_from_proc()


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
    gw = get_gateway()
    candidates = []
    if gw:
        candidates.extend([(gw, 8092), (gw, 3000)])
    for sub in ["172.17.0.1", "172.18.0.1", "172.19.0.1", "172.80.0.1", "172.80.3.1"]:
        candidates.extend([(sub, 8092), (sub, 3000)])
    candidates.append(("172.80.3.2", 3000))

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for item in candidates:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped, gw


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
    candidates, gw = get_candidates()
    target = None
    for host, port in candidates:
        print(f"[Bridge] Probing {host}:{port}...", flush=True)
        if probe(host, port):
            target = (host, port)
            print(f"[Bridge] Successfully connected to Gitea service at {host}:{port}!", flush=True)
            break

    if not target:
        fallback_gw = gw or "172.17.0.1"
        target = (fallback_gw, 8092)
        print(f"[Bridge] No candidate responded. Defaulting to fallback target {target[0]}:{target[1]}", flush=True)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("127.0.0.1", 3000))
        server.listen(128)
    except OSError as e:
        print(f"[Bridge] Port 127.0.0.1:3000 is already in use or unavailable: {e}. Exiting bridge.", flush=True)
        sys.exit(0)

    print(f"[Bridge] Listening on 127.0.0.1:3000 -> {target[0]}:{target[1]}", flush=True)

    while True:
        try:
            client_sock, client_addr = server.accept()
        except Exception as e:
            print(f"[Bridge] Server accept error: {e}", flush=True)
            time.sleep(0.1)
            continue

        try:
            remote_sock = socket.create_connection(target, timeout=10)
        except Exception as e:
            print(f"[Bridge] Failed to connect to target {target} for client {client_addr}: {e}", flush=True)
            try:
                client_sock.close()
            except Exception:
                pass
            continue

        print(f"[Bridge] Forwarding connection {client_addr} <-> {target[0]}:{target[1]}", flush=True)
        t = threading.Thread(target=forward, args=(client_sock, remote_sock), daemon=True)
        t.start()


if __name__ == "__main__":
    main()
