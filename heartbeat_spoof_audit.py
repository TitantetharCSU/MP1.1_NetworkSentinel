#!/usr/bin/env python3
"""Local-only heartbeat spoofing assessment of the existing monitor.

Runs a monitor subprocess against a dummy UDP responder, with the real sentinel
not running. Demonstrates that an unauthenticated ACK can produce HEARTBEAT OK.
No packet capture, IP spoofing, elevated privileges, or external hosts required.
"""
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    # Select an unused loopback UDP port for the simulated 'down' service.
    fake = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    fake.bind(("127.0.0.1", 0))
    fake.settimeout(0.25)
    port = fake.getsockname()[1]
    stop = threading.Event()
    count = [0]

    def impersonator():
        while not stop.is_set():
            try:
                data, address = fake.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                request = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(request, dict) and request.get("type") == "PING":
                # Deliberately omit sequence and timestamp: monitor accepts ACK anyway.
                fake.sendto(b'{"type":"ACK"}', address)
                count[0] += 1

    thread = threading.Thread(target=impersonator, daemon=True)
    thread.start()
    command = [sys.executable, "-u", str(HERE / "monitor.py"),
               "--host", "127.0.0.1", "--port", str(port),
               "--interval", "0.3", "--timeout", "0.2", "--misses", "3",
               "--log", str(HERE / "audit_monitor.log")]
    print("TASK 5 — LOCAL HEARTBEAT SPOOFING AUDIT", flush=True)
    print("Real sentinel: NOT STARTED", flush=True)
    print(f"Dummy responder: 127.0.0.1:{port}", flush=True)
    print("Launching existing monitor for ~2 seconds...", flush=True)
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(2.2)
    finally:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
        stop.set()
        fake.close()
        thread.join(timeout=1)

    print("\n--- MONITOR OUTPUT ---")
    print(output.strip())
    ok = "HEARTBEAT OK" in output
    print("\n--- AUDIT RESULT ---")
    print(f"Dummy ACK responses sent: {count[0]}")
    if ok:
        print("VULNERABLE: Monitor reported HEARTBEAT OK without the real service.")
        print("Cause: monitor trusts any JSON ACK and does not authenticate the sender.")
    else:
        print("INCONCLUSIVE: no healthy heartbeat was observed. Check monitor output.")
    print("Mitigation: authenticate heartbeat responses, verify request nonce, and check peer identity.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
