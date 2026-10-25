#!/usr/bin/env python3
"""Network Sentinel: simulated firewall service with stochastic process failure.

Usage:
    python sentinel.py
    python sentinel.py --host 127.0.0.1 --port 39001 --failure-probability 0.02
"""
from __future__ import annotations

import argparse
import json
import os
import random
import socket
import time
from datetime import datetime, timezone
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 39001
BLACKLIST = {
    "192.168.1.100",
    "10.0.0.66",
    "203.0.113.50",
}


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def send_json(sock: socket.socket, address: tuple[str, int], payload: dict[str, Any]) -> None:
    sock.sendto(json.dumps(payload, separators=(",", ":")).encode("utf-8"), address)


def handle_message(message: dict[str, Any]) -> dict[str, Any]:
    """Handle a heartbeat or simulated packet inspection request."""
    msg_type = message.get("type")

    if msg_type == "PING":
        return {"type": "ACK", "timestamp": timestamp()}

    if msg_type == "INSPECT":
        source_ip = message.get("source_ip")
        destination_port = message.get("destination_port")

        if not isinstance(source_ip, str):
            return {"type": "ERROR", "reason": "source_ip must be a string"}
        try:
            # Validate that the input is an IP address.
            import ipaddress
            normalized_ip = str(ipaddress.ip_address(source_ip))
        except ValueError:
            return {"type": "ERROR", "reason": "Invalid source IP address"}

        if not isinstance(destination_port, int) or isinstance(destination_port, bool) or not 1 <= destination_port <= 65535:
            return {"type": "ERROR", "reason": "destination_port must be an integer from 1 to 65535"}

        blocked = normalized_ip in BLACKLIST
        response: dict[str, Any] = {
            "type": "BLOCK" if blocked else "ALLOW",
            "source_ip": normalized_ip,
            "destination_port": destination_port,
        }
        if blocked:
            response["reason"] = "Blacklisted source IP"
        return response

    return {"type": "ERROR", "reason": "Unknown message type"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulated Network Sentinel firewall service")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind address (default: loopback only)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--failure-probability", type=float, default=0.02,
        help="Probability (0.0-1.0) of process termination per received datagram (default: 0.02)",
    )
    args = parser.parse_args()

    if not 0.0 <= args.failure_probability <= 1.0:
        parser.error("--failure-probability must be between 0.0 and 1.0")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    # Use an independent PRNG seed from OS entropy.
    random.seed(os.urandom(32))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((args.host, args.port))
    except OSError as exc:
        sock.close()
        raise SystemExit(f"Could not bind {args.host}:{args.port}: {exc}")

    print(f"[{timestamp()}] Network Sentinel started on {args.host}:{args.port}", flush=True)
    print(f"Random fatal-failure probability per datagram: {args.failure_probability:.1%}", flush=True)
    print(f"Blacklist entries: {len(BLACKLIST)}", flush=True)

    while True:
        try:
            raw, peer = sock.recvfrom(65535)
        except OSError as exc:
            print(f"[{timestamp()}] Socket error: {exc}", flush=True)
            continue

        # The random trigger deliberately exits the whole critical process.
        if random.random() < args.failure_probability:
            print(f"[{timestamp()}] Simulated fatal failure while handling a request.", flush=True)
            sock.close()
            os._exit(1)

        try:
            message = json.loads(raw.decode("utf-8"))
            if not isinstance(message, dict):
                response = {"type": "ERROR", "reason": "JSON message must be an object"}
            else:
                response = handle_message(message)
        except (UnicodeDecodeError, json.JSONDecodeError):
            response = {"type": "ERROR", "reason": "Malformed JSON"}
        except Exception as exc:
            # A bad request should not ordinarily kill the service.
            response = {"type": "ERROR", "reason": f"Request processing error: {type(exc).__name__}"}

        try:
            send_json(sock, peer, response)
        except OSError:
            # If the service socket is unusable, continue; the monitor will detect loss.
            pass


if __name__ == "__main__":
    main()
