#!/usr/bin/env python3
"""Send one JSON request to the current owner of the stable service port."""
import argparse
import json
import socket

p = argparse.ArgumentParser()
p.add_argument('action', choices=['status','inspect','block'])
p.add_argument('--ip', default='8.8.8.8')
p.add_argument('--destination-port', type=int, default=443)
p.add_argument('--host', default='127.0.0.1')
p.add_argument('--port', type=int, default=39001)
a = p.parse_args()
msg = {'status': {'type':'STATUS'}, 'inspect': {'type':'INSPECT', 'source_ip':a.ip, 'destination_port':a.destination_port},
       'block': {'type':'BLOCK_IP', 'source_ip':a.ip}}[a.action]
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
    s.settimeout(3)
    s.sendto(json.dumps(msg).encode(), (a.host, a.port))
    try:
        data, _ = s.recvfrom(8192)
        print(json.dumps(json.loads(data), indent=2))
    except socket.timeout:
        raise SystemExit('No service response (possibly during failover). Retry after recovery.')
