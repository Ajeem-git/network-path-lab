# Incident exercise: failover restored service but bypassed inspection

## Executive summary

**Classification:** simulated security-control bypass in an isolated lab; no
cloud resources or external systems are involved.

**Customer symptom:** after a transit-link failure, the HTTP service is
reachable again.

**Security symptom:** packets are using the direct Edge-A/Edge-B link and no
longer traverse the required stateful firewall. Service availability alone
would have reported a successful recovery while concealing a policy violation.

**Root cause:** both edge routers advertised workload LAN prefixes to each
other over the direct eBGP session. On transit failure, BGP selected those
alternate paths. The topology had configured redundant reachability but had
not encoded the requirement that these particular prefixes must pass through
the inspection point.

**Remediation in this lab:** explicit outbound route maps on the direct eBGP
peers deny the client and server LAN prefixes. Transit remains the only
advertised path for protected traffic. If transit is unavailable, those routes
are withdrawn and the flow fails closed. Docker-injected default routes are
removed from router namespaces so the lab has no undeclared fallback path.

## Incident timeline — reproduce, don't assume

From the project root with a fresh lab:

```sh
docker compose up --build -d --force-recreate
python3 app/labctl.py scenario baseline
python3 app/labctl.py scenario failover
```

**Prediction:** baseline routes select `eth2` through the firewall. When
Edge-A's transit interface goes down, the direct `eth3` route takes over and
HTTP returns 200.

**Evidence to capture:**

```sh
python3 app/labctl.py status
docker compose exec edge-a vtysh -c 'show bgp ipv4 unicast 10.112.1.0/24'
docker compose exec edge-b vtysh -c 'show bgp ipv4 unicast 10.111.1.0/24'
docker compose exec transit-fw nft -a list chain inet routing_lab forward
```

Record the selected interfaces, probe result, BGP peer/path changes, and
firewall counters in [`../evidence/EXPERIMENT-LOG.md`](../evidence/EXPERIMENT-LOG.md).
The expected direct path demonstrates the incident: **HTTP recovered, but the
firewall was bypassed.** This test establishes reachability and route selection
in this container topology; it is not a measurement of real production
convergence.

## Diagnosis

1. Separate the service symptom from the security invariant. HTTP 200 says the
   application replied, not that the approved control path was used.
2. Compare FIB output on both edges. `eth3` for both destinations identifies
   direct forwarding.
3. Inspect both BGP candidate paths and their AS paths/preferences. The direct
   peer is learning and exporting the protected LAN prefixes.
4. Inspect firewall counters/captures. The direct route avoids the firewall;
   a quiet counter alone is not enough unless paired with path evidence.
5. State the missing control as an invariant: client/server prefixes may be
   advertised only through the approved firewall transit path.

## Remediation and verification

Apply outbound route maps that deny the protected prefixes on both direct
eBGP peers, while preserving advertisements to the transit firewall:

```sh
python3 app/labctl.py scenario mitigate
python3 app/labctl.py status
docker compose exec edge-a vtysh -c 'show bgp ipv4 unicast 10.112.1.0/24'
docker compose exec edge-b vtysh -c 'show bgp ipv4 unicast 10.111.1.0/24'
python3 app/labctl.py scenario failover-blocked
```

`mitigate` verifies that both protected routes still use firewall `eth2` and
HTTP remains 200. `failover-blocked` brings down Edge-A's transit link and
asserts that neither edge has a route for the remote protected prefix and that
the HTTP probe does not succeed. In contrast to the intentionally fail-open
`failover` experiment, this is the lab's fail-closed policy test. The command
asserts observable FIB and application behavior; inspect BGP RIB and nftables
state too before drawing a security conclusion.

Then return the lab to baseline:

```sh
python3 app/labctl.py scenario restore
python3 app/labctl.py status
```

`restore` brings the link up, re-allows direct advertisements for the original
experiments, restores the normal local preference, waits for transit routes,
and requires HTTP 200.

## Rollback, change safety, and residual risk

- Roll back only after confirming the transit route is healthy and the required
  inspection path is restored. `restore` does this in the lab; do not use a
  general “permit all” policy as a production rollback.
- The direct-path deny is intentionally scoped to the two lab LAN prefixes.
  It does not secure arbitrary, newly introduced, or more-specific prefixes.
  Production controls must use reviewed prefix-lists, route-policy tests,
  peer-specific export policies, and explicit defaults.
- Denying the backup path sacrifices availability when transit fails. Decide
  explicitly whether inspection is mandatory or whether an approved alternate
  inspection-capable path exists. Never silently trade away a security
  invariant for HTTP availability.
- Route filtering alone does not validate application identity, packet path
  across every network domain, NAT behavior, or other firewall failure modes.
  Use end-to-end telemetry and path evidence in a real architecture.
- Review failure detection, convergence timers, stateful flow handling, and
  failback behavior separately. This exercise uses `ip link set down`, not a
  silent blackhole or a real provider failure.
- The lab's BGP peers are configured with 3-second keepalive and 9-second hold
  timers so withdrawal can be exercised within the scenario runner's bounded
  wait. These are not recommendations for a production network; timer choices
  require platform, scale, and failure-mode analysis.
- This is a Docker/FRR/nftables simulation only; it does not configure or
  represent AWS, Azure, or another cloud provider.

## Runtime validation recorded

On 2026-10-24, the complete scenario sequence was executed on Docker Desktop
(Docker Engine 29.9.2, Compose 5.6.1, FRRouting 8.4.4, aarch64/LinuxKit):

| Scenario | Observed routes | Observed service/security result |
|---|---|---|
| `baseline` | Edge-A and Edge-B via `eth2` | HTTP 200 |
| `asymmetric` | Edge-A via `eth2`; Edge-B via `eth3` | HTTP timeout; forward drop counter +9 |
| `failover` | Both edges via direct `eth3` | HTTP 200 while bypassing inspection |
| `mitigate` | Both edges via inspected `eth2` | HTTP 200; direct prefix exports denied |
| `failover-blocked` | No route to either remote protected prefix | HTTP probe reported `Network is unreachable` |
| `restore` | Both edges via inspected `eth2` | HTTP 200 |

These are measured results for this local run and policy. Re-run and record
your own observations; do not infer equivalent timing or behavior in production.

## Incident report template

Copy into the experiment log or a separate report:

| Field | Record |
|---|---|
| Start/end time (UTC), operator, runtime versions | |
| User-visible symptom and security invariant | |
| Detection source and measured impact | |
| Evidence: BGP, FIB, firewall counters, pcap, HTTP | |
| Root cause and contributing conditions | |
| Mitigation applied and change scope | |
| Verification criteria and actual results | |
| Rollback decision and recovery result | |
| Residual risk, owner, and follow-up | |
