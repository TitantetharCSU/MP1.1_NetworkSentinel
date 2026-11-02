# Network Sentinel Part 2: Passive Redundancy

Python 3.10+; standard library only. No compilation or pip installation.

## Architecture

- **Primary:** UDP firewall on `127.0.0.1:39001`, with dynamic counters and blacklist.
- **Checkpoint:** `checkpoint.json`, written atomically and checksummed after every state-changing request **before** the client gets a success response.
- **Warm standby:** launched by the monitor only after the supervised primary process has exited and the missed-heartbeat threshold is met. Loads the validated checkpoint and binds the same service port.
- **Monitor:** independently probes using PING/ACK and logs `[Crash Detected]`, `[Failover Triggered]`, `[Service Restored]`.
- **Adversarial audit:** modifies a *temporary copy* of the checkpoint; backup must reject it without loading corrupted state.

## Quick start

From the project folder, run in terminal 1:

```bash
python monitor.py --failure-probability 0
```

The monitor starts the primary itself. **Do not start `sentinel.py` separately** when using the monitor.

In terminal 2:

```bash
python client.py status
python client.py inspect --ip 8.8.8.8
python client.py inspect --ip 192.168.1.100
python client.py block --ip 8.8.8.8
python client.py inspect --ip 8.8.8.8
python client.py status
```

To demonstrate a crash without manual process killing, stop the monitor with Ctrl+C, then restart it with a higher random failure probability:

```bash
python monitor.py --failure-probability 0.20
```

Send requests or wait for heartbeat traffic to trigger a random primary crash. After three missed responses, the monitor automatically starts a backup and restores the checkpoint. Retry `python client.py status` after `[Service Restored]` and confirm the counters and dynamic blacklist survived. Backup uses failure probability 0 to keep the demonstration stable.

## Checkpoint tampering audit (Task 4, Scenario 2)

With a valid checkpoint already generated:

```bash
python checkpoint_audit.py
```

The audit changes the `blocked` counter in a **temporary copy** without updating its SHA-256 checksum, launches an isolated backup on port 39099, and verifies that startup is rejected with exit code 2. The live checkpoint is not modified.

## Optional false-heartbeat-loss test

```bash
python monitor.py --failure-probability 0 --drop-acks
```

This intentionally discards received ACKs at the monitor. After three misses, the monitor logs `[Failover Suppressed]` because the supervised primary process is still alive. This reduces split-brain risk in the **single-host supervised prototype**.

## Parameters and limitations

Default heartbeat interval T = 1 second; ACK timeout W = 2 seconds; threshold N = 3 consecutive misses. Timed-out checks are sequential, so detection generally takes about 6 seconds after the first unanswered probe. A failure just after a successful check may take longer. With an alive but unresponsive primary, the monitor **does not promote** a backup, prioritizing safety over availability.

This is **single-host passive failover**, not zero-downtime active replication. During failover, some client UDP requests can time out and should be retried. It has no distributed quorum, no independent host failure recovery, no authenticated heartbeat, and no protection against a malicious actor who can rewrite both state and checksum. Atomic checkpoint writes protect against partial writes but not disk failure. Because requests have no unique IDs, a retry after an ambiguous timeout may increment counters twice; production code would need request IDs and deduplication. Avoid running multiple monitors simultaneously.
