# Experiment evidence log

Copy this file for each run. Do not replace **Expected** with a claim of fact
until you have executed the scenario and retained its output or capture.

## Run identity

- Operator:
- Date/time (UTC):
- Host OS / architecture:
- Docker Engine or Desktop version:
- Docker Compose version:
- Lab image IDs/digests (optional but recommended):
- FRR version (`docker compose exec edge-a vtysh -c 'show version'`):
- Git/revision or project snapshot:
- Scenario:
- Run number:

## Prediction

- Expected route from Edge-A to `10.112.1.10`:
- Expected route from Edge-B to `10.111.1.10`:
- Expected firewall path / nftables behavior:
- Expected HTTP result:
- What observation would falsify this prediction?

## Procedure and measured observations

| Time (UTC) | Command / action | Measured output or filename | Interpretation |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

- Scenario runner exit code:
- HTTP status/body:
- Firewall rule counters before and after:
- Conntrack observation:
- BGP peer/path observation:
- Capture filename(s), interface(s), and filter(s):
- Convergence timing method and raw samples (if measured):

## Interpretation and caveats

- What does the evidence establish?
- What does it not establish?
- Did observation match prediction? If not, what follow-up test will distinguish causes?
- Any platform-specific limitations or errors:

## Cleanup

- Recovery command run:
- Baseline route assertions pass:
- Lab stopped with `docker compose down`:
- Evidence reviewed for unintended data:
