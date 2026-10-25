#!/usr/bin/env python3
"""Independent UDP heartbeat monitor for sentinel.py.

Usage:
    python monitor.py
    python monitor.py --host 127.0.0.1 --port 39001 --interval 1 --timeout 2 --misses 3

The monitor stays alive after the service becomes unresponsive. It records one incident
per transition into the FAILED state, and prints a recovery notice if ACKs resume.
"""
from __future__ import annotations

import argparse
import json
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 39001


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def encode_message(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def append_log(path: Path, line: str) -> None:
    try:
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(line + "\n")
            log_file.flush()
    except OSError as exc:
        print(f"[{timestamp()}] WARNING: could not write log {path}: {exc}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="UDP heartbeat monitor for Network Sentinel")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Sentinel host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between heartbeat attempts")
    parser.add_argument("--timeout", type=float, default=2.0, help="Seconds to wait for each ACK")
    parser.add_argument("--misses", type=int, default=3, help="Consecutive missed ACKs before declaring failure")
    parser.add_argument("--log", default="monitor.log", help="Incident log path (default: monitor.log)")
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.interval <= 0 or args.timeout <= 0:
        parser.error("--interval and --timeout must be positive")
    if args.misses < 1:
        parser.error("--misses must be at least 1")

    log_path = Path(args.log)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(args.timeout)
    destination = (args.host, args.port)
    failed = False
    sequence = 0

    print(
        f"[{timestamp()}] Monitor started; target={args.host}:{args.port}, "
        f"interval={args.interval}s, timeout={args.timeout}s, threshold={args.misses} misses",
        flush=True,
    )
    print(f"Incident log: {log_path.resolve()}", flush=True)

    try:
        while True:
            sequence += 1
            request = {"type": "PING", "sequence": sequence, "sent_at": timestamp()}
            received_ack = False
            start = time.monotonic()

            try:
                sock.sendto(encode_message(request), destination)
                raw, _peer = sock.recvfrom(65535)
                response = json.loads(raw.decode("utf-8"))
                received_ack = isinstance(response, dict) and response.get("type") == "ACK"
            except socket.timeout:
                received_ack = False
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                print(f"[{timestamp()}] Communication error: {exc}", flush=True)
                received_ack = False

            elapsed = time.monotonic() - start

            if received_ack:
                if failed:
                    line = f"[{timestamp()}] RECOVERY: Network Sentinel is responding again."
                    print(line, flush=True)
                    append_log(log_path, line)
                failed = False
                print(f"[{timestamp()}] HEARTBEAT OK (sequence={sequence}, rtt={elapsed:.3f}s)", flush=True)
            else:
                # Count consecutive misses across loop iterations.
                misses = getattr(main, "_misses", 0) + 1
                setattr(main, "_misses", misses)
                print(
                    f"[{timestamp()}] HEARTBEAT MISSED ({misses}/{args.misses} consecutive timeouts)",
                    flush=True,
                )
                if misses >= args.misses and not failed:
                    failed = True
                    line = (
                        f"[{timestamp()}] ALERT: Network Sentinel is unresponsive; "
                        f"{misses} consecutive heartbeat failures."
                    )
                    print(line, flush=True)
                    append_log(log_path, line)
            if received_ack:
                setattr(main, "_misses", 0)

            # Keep a roughly fixed interval between attempts, accounting for time spent waiting.
            remaining = args.interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print(f"\n[{timestamp()}] Monitor stopped by user.", flush=True)
    finally:
        sock.close()


if __name__ == "__main__":
    main()
