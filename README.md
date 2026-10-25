# Network Sentinel Prototype

Two-process Python prototype for a simulated firewall and independent UDP heartbeat monitor.

## Requirements
- Python 3.10+ (uses standard library only)

## Run
Open two terminals in this directory.

Terminal 1:
```bash
python sentinel.py
```

Terminal 2:
```bash
python monitor.py
```

The monitor sends UDP `PING` messages to `127.0.0.1:39001`. The sentinel replies with `ACK`.
If three consecutive acknowledgments are missed (default), the monitor prints a timestamped alert and appends it to `monitor.log`. The monitor remains running after the sentinel exits.

## Test packet inspection
In a third terminal, run:
```bash
python -c "import json,socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(2); s.sendto(json.dumps({'type':'INSPECT','source_ip':'192.168.1.100','destination_port':443}).encode(),('127.0.0.1',39001)); print(s.recvfrom(4096)[0].decode())"
```
Change the source IP to `8.8.8.8` to see an `ALLOW` response (unless the service randomly crashes first).

## Simulate a crash
The default failure probability is 2% per received datagram. For a reliable demo, use:
```bash
python sentinel.py --failure-probability 0.20
```
This makes each received datagram have a 20% chance of terminating the entire sentinel process. For normal operation, use the default or set `--failure-probability 0`.

## Configuration
Both scripts accept `--host` and `--port`. The monitor also accepts:
- `--interval` (default 1 second)
- `--timeout` (default 2 seconds)
- `--misses` (default 3 consecutive misses)
- `--log` (default `monitor.log`)

Use the same host and port settings for both processes. This is a local educational prototype, not a production firewall.
