#!/usr/bin/env python3
"""Network Sentinel service: primary or checkpoint-restoring standby."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import random
import socket
import tempfile
from datetime import datetime

DEFAULT_BLOCKED = ['192.168.1.100', '10.0.0.66', '203.0.113.50']

def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')

def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')

def write_checkpoint(path, state):
    payload = {'version': 1, 'state': state, 'sha256': hashlib.sha256(canonical(state)).hexdigest()}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.checkpoint-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def load_checkpoint(path):
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
        state = doc['state']
        if doc['version'] != 1 or not isinstance(state, dict):
            raise ValueError('unsupported checkpoint schema')
        if doc['sha256'] != hashlib.sha256(canonical(state)).hexdigest():
            raise ValueError('checkpoint checksum mismatch')
        if set(state) != {'allowed', 'blocked', 'requests', 'dynamic_blacklist'}:
            raise ValueError('invalid checkpoint state fields')
        if any(type(state[k]) is not int or state[k] < 0 for k in ('allowed','blocked','requests')):
            raise ValueError('invalid counters')
        if state['requests'] != state['allowed'] + state['blocked']:
            raise ValueError('inconsistent counters')
        if not isinstance(state['dynamic_blacklist'], list) or any(not isinstance(x,str) for x in state['dynamic_blacklist']):
            raise ValueError('invalid blacklist')
        for ip in state['dynamic_blacklist']:
            ipaddress.ip_address(ip)
        return state
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f'checkpoint validation failed: {exc}') from exc

def new_state():
    return {'allowed': 0, 'blocked': 0, 'requests': 0, 'dynamic_blacklist': []}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--role', choices=['primary','backup'], default='primary')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=39001)
    p.add_argument('--checkpoint', default='checkpoint.json')
    p.add_argument('--failure-probability', type=float, default=0.02)
    args = p.parse_args()
    if not 0 <= args.failure_probability <= 1:
        p.error('failure-probability must be between 0 and 1')
    if not 1 <= args.port <= 65535:
        p.error('invalid port')
    path = Path(args.checkpoint)
    if args.role == 'backup':
        try:
            state = load_checkpoint(path)
        except ValueError as exc:
            print(f'[{now()}] RESTORE REFUSED: {exc}', flush=True)
            raise SystemExit(2)
    else:
        # Avoid resetting persistent state when a primary is restarted.
        if path.exists():
            try:
                state = load_checkpoint(path)
            except ValueError as exc:
                print(f'[{now()}] START REFUSED: {exc}', flush=True)
                raise SystemExit(2)
        else:
            state = new_state()
            write_checkpoint(path, state)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((args.host, args.port))
    except OSError as exc:
        print(f'[{now()}] BIND REFUSED (another service may own the port): {exc}', flush=True)
        raise SystemExit(3)
    print(f'[{now()}] SERVICE READY role={args.role} pid={os.getpid()} port={args.port} state={state}', flush=True)
    try:
        while True:
            raw, peer = sock.recvfrom(8192)
            if random.random() < args.failure_probability:
                print(f'[{now()}] SIMULATED CRASH role={args.role}', flush=True)
                os._exit(1)
            try:
                msg = json.loads(raw.decode('utf-8'))
                if not isinstance(msg, dict):
                    raise ValueError('message must be JSON object')
                kind = msg.get('type')
                if kind == 'PING':
                    reply = {'type': 'ACK', 'sequence': msg.get('sequence'), 'role': args.role}
                elif kind == 'STATUS':
                    reply = {'type': 'STATUS', 'role': args.role, 'state': state}
                elif kind == 'INSPECT':
                    ip = str(ipaddress.ip_address(msg['source_ip']))
                    port = msg.get('destination_port', 443)
                    if type(port) is not int or not 1 <= port <= 65535:
                        raise ValueError('invalid destination_port')
                    denied = ip in DEFAULT_BLOCKED or ip in state['dynamic_blacklist']
                    updated = {**state, 'requests': state['requests'] + 1,
                               'blocked': state['blocked'] + int(denied),
                               'allowed': state['allowed'] + int(not denied)}
                    write_checkpoint(path, updated)  # commit BEFORE acknowledging client
                    state = updated
                    reply = {'type': 'BLOCK' if denied else 'ALLOW', 'source_ip': ip, 'state': state}
                elif kind == 'BLOCK_IP':
                    ip = str(ipaddress.ip_address(msg['source_ip']))
                    updated = {**state, 'dynamic_blacklist': sorted(set(state['dynamic_blacklist']) | {ip})}
                    write_checkpoint(path, updated)
                    state = updated
                    reply = {'type': 'UPDATED', 'state': state}
                else:
                    reply = {'type': 'ERROR', 'reason': 'unknown message type'}
            except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
                reply = {'type': 'ERROR', 'reason': str(exc)}
            except OSError as exc:
                print(f'[{now()}] PERSISTENCE ERROR: {exc}', flush=True)
                reply = {'type': 'ERROR', 'reason': 'checkpoint write failed; state not committed'}
            sock.sendto(canonical(reply), peer)
    except KeyboardInterrupt:
        print(f'[{now()}] Service stopped', flush=True)
    finally:
        sock.close()

if __name__ == '__main__':
    main()
