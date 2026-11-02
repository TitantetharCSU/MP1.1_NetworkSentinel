#!/usr/bin/env python3
"""Local adversarial test: corrupt a COPY of the checkpoint and verify fail-closed restore."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

p = argparse.ArgumentParser()
p.add_argument('--checkpoint', default='checkpoint.json')
a = p.parse_args()
source = Path(a.checkpoint)
if not source.exists():
    raise SystemExit('Checkpoint not found. Start the monitor and send requests first.')
with tempfile.TemporaryDirectory(prefix='sentinel-audit-') as tmp:
    copy = Path(tmp) / 'tampered_checkpoint.json'
    doc = json.loads(source.read_text(encoding='utf-8'))
    doc['state']['blocked'] += 1000  # tamper WITHOUT updating checksum
    copy.write_text(json.dumps(doc), encoding='utf-8')
    cmd = [sys.executable, str(Path(__file__).with_name('sentinel.py')),
           '--role', 'backup', '--checkpoint', str(copy), '--port', '39099',
           '--failure-probability', '0']
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    print('AUDIT: modified blocked count in temporary checkpoint copy')
    print(result.stdout.strip())
    print(result.stderr.strip())
    print('PASS: corrupted checkpoint rejected; standby did not start' if result.returncode == 2
          else f'FAIL: unexpected backup exit code {result.returncode}')
    sys.exit(0 if result.returncode == 2 else 1)
