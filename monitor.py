#!/usr/bin/env python3
"""Supervisor: starts primary, checks PING/ACK, launches standby after failure."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import socket
import subprocess
import sys
import time


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=39001)
    p.add_argument('--interval', type=float, default=1.0)
    p.add_argument('--timeout', type=float, default=2.0)
    p.add_argument('--misses', type=int, default=3)
    p.add_argument('--checkpoint', default='checkpoint.json')
    p.add_argument('--log', default='monitor.log')
    p.add_argument('--failure-probability', type=float, default=0.02)
    p.add_argument('--drop-acks', action='store_true', help='Audit: discard received ACKs to simulate heartbeat loss')
    args = p.parse_args()
    if args.interval <= 0 or args.timeout <= 0 or args.misses < 1:
        p.error('invalid timing parameters')
    log = Path(args.log)
    service = Path(__file__).with_name('sentinel.py')
    def event(message):
        line = f'[{now()}] {message}'
        print(line, flush=True)
        with log.open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    def launch(role, probability):
        return subprocess.Popen([sys.executable, '-u', str(service), '--role', role,
                                 '--host', args.host, '--port', str(args.port),
                                 '--checkpoint', args.checkpoint,
                                 '--failure-probability', str(probability)])
    proc = launch('primary', args.failure_probability)
    event(f'Primary launched pid={proc.pid}')
    role = 'primary'
    missed = 0
    failed = False
    seq = 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        while True:
            seq += 1
            start = time.monotonic()
            healthy = False
            try:
                # New ephemeral source port and sequence prevent stale replies from previous checks.
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                    probe.settimeout(args.timeout)
                    probe.sendto(json.dumps({'type': 'PING', 'sequence': seq}).encode(), (args.host, args.port))
                    raw, addr = probe.recvfrom(8192)
                    reply = json.loads(raw.decode())
                    healthy = (not args.drop_acks and addr == (args.host, args.port)
                               and isinstance(reply, dict) and reply.get('type') == 'ACK'
                               and reply.get('sequence') == seq and reply.get('role') == role)
            except (OSError, ValueError, UnicodeError):
                pass
            if healthy:
                missed = 0
                if failed:
                    event(f'[Service Restored] role={role} pid={proc.pid}')
                    failed = False
            else:
                missed += 1
                event(f'Heartbeat missed ({missed}/{args.misses}) role={role}')
                if missed >= args.misses and not failed:
                    failed = True
                    event(f'[Crash Detected] role={role} heartbeat threshold reached')
                    if proc.poll() is None:
                        # Heartbeat loss alone is insufficient proof of a crash.
                        event('[Failover Suppressed] Process is alive; possible network fault; avoiding split-brain')
                    elif role == 'primary':
                        event('[Failover Triggered] Launching standby from checkpoint')
                        proc = launch('backup', 0.0)
                        role = 'backup'
                        missed = 0
                    else:
                        event('[Service Unavailable] Backup exited; operator intervention required')
            # If we suppressed failover, re-evaluate only after another threshold.
            if failed and proc.poll() is not None and role == 'primary':
                event('[Failover Triggered] Primary exit confirmed; launching standby')
                proc = launch('backup', 0.0)
                role = 'backup'
                missed = 0
            elapsed = time.monotonic() - start
            if elapsed < args.interval:
                time.sleep(args.interval - elapsed)
    except KeyboardInterrupt:
        event('Monitor stopped by user')
    finally:
        sock.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

if __name__ == '__main__':
    main()
