# Hands-on graduate lab: routing, state, and path symmetry

## Learning contract

This guide takes you from address and interface inspection to a defensible
demonstration of how routing policy interacts with stateful security controls.
Do not treat a successful command as an explanation: predict the outcome first,
capture the evidence, explain why it follows, and note what the experiment does
not establish. Record actual outputs and timestamps in
[`../evidence/EXPERIMENT-LOG.md`](../evidence/EXPERIMENT-LOG.md).

### Learning objectives

By the end, you can:

1. Map Docker virtual Ethernet interfaces, connected subnets, gateways, and
   Linux forwarding paths without relying on interface order guesses.
2. Trace an advertised prefix across three eBGP autonomous systems and explain
   the selected route using BGP attributes and the kernel FIB.
3. Read the nftables forward policy and explain how conntrack classifies
   `new`, `established`, and `related` packets.
4. Produce evidence of a one-way firewall path and a direct return path, and
   distinguish policy bypass from application failure.
5. Trigger a BGP adjacency failure, measure route convergence, and restore the
   original symmetric state.
6. Diagnose a fail-open recovery, apply a prefix-scoped fail-closed export
   policy, and articulate its availability trade-off.
7. Design assertions that test outcomes without assuming an unmeasured timeout,
   and explain the model's limitations versus physical or cloud networks.

### Prerequisites and safety boundaries

Comfort with IPv4 prefixes, Linux shell commands, basic TCP, and reading
configuration files is recommended. You will learn BGP and nftables concepts
here; prior production routing experience is not required. You need Docker
Compose v2 and Python 3.10+ locally. All endpoints use RFC1918 addresses on
Docker bridge networks. No cloud accounts, credentials, internet targets,
traffic generators, privileged mode, or host network namespace changes are
used. Do not attach unrelated containers to the lab networks.

Start the lab:

```sh
docker compose config
docker compose up --build -d
docker compose ps
```

Wait for the web and router health checks. BGP readiness is separate from
container health; `labctl` polls routes and fails with a clear timeout if
expected routes do not converge.

## Conceptual model

The client route to the server is via Edge-A. Edge-A learns `10.112.1.0/24`
from both the firewall and Edge-B. The firewall advertises the learned server
prefix to Edge-A with its own AS in the path; Edge-B also advertises that same
prefix directly. Edge-A assigns local preference 200 to the transit-learned
path and 100 to the direct path. Edge-B applies the mirror policy to
`10.111.1.0/24`. LOCAL_PREF is compared before AS_PATH length in BGP selection,
so both edges prefer the transit route in baseline. The kernel installs a route
whose outgoing interface is `eth2`.

The firewall permits only new client-to-server HTTP/ICMP flows on its forward
chain and permits established/related flows in either direction. It does not
force packets that do not traverse it to return. If Edge-B prefers its direct
route, the initial SYN can pass through the firewall while the SYN/ACK returns
directly. The firewall's conntrack entry therefore never observes the reverse
handshake. The client's later ACK and request data still follow Edge-A's
firewall route, fail the established-state check, and hit the explicit drop
rule. This exact policy produces a timeout; a permissive or stateless policy
could instead let TCP complete despite the path asymmetry.

## Lab 0 — Baseline and prediction

**Prediction:** Both edge routers choose transit `eth2`; the client gets HTTP
200. Record which output would falsify your expectation before running it.

**Command:**

```sh
python3 app/labctl.py scenario baseline
python3 app/labctl.py status
```

**Evidence:** Save terminal output in the experiment log. Verify that Edge-A's
route to `10.112.1.10` has `dev eth2`, Edge-B's route to `10.111.1.10` has
`dev eth2`, the HTTP body reports `status: ok`, and the route maps are installed.

**Interpretation:** The runner checks the Linux route actually used to reach
each destination, and the application probe checks end-to-end reachability.
The runner does not use a BGP status label as a substitute for a forwarding
test. Explain how the locally configured preference influences those routes.

**Reflection:** What would a route table prove that a successful HTTP request
does not? What would HTTP prove that a BGP summary does not?

## Lab 1 — L2/L3 topology and forwarding

**Prediction:** Each edge has three connected networks; the transit firewall
has two. A host route to its peer on a directly connected subnet needs no
gateway. A packet to the opposite LAN requires forwarding at both edge routers
and the firewall.

**Commands:**

```sh
docker compose exec client ip -br address
docker compose exec edge-a ip -br address
docker compose exec transit-fw ip -br address
docker compose exec edge-b ip -br address
docker compose exec client ip route
docker compose exec edge-a ip route
docker compose exec edge-a ip route get 10.112.1.10
docker compose exec transit-fw sysctl net.ipv4.ip_forward
```

**Evidence:** Record interface/address output and the `ip route get` result.
Compare each interface to the address table in the README.

**Interpretation:** A Docker network gives endpoints a shared virtual Ethernet
segment and connected route. It does not make a multi-homed Linux container a
router by itself; forwarding and a route are both needed. Static host routes
keep endpoint behavior explicit rather than depending on Docker's default
gateway choice.

**Reflection:** Which nodes perform a routing lookup? Which links are L2
segments, and which are merely represented by separate L2 segments in this
lab?

## Lab 2 — eBGP sessions and advertisements

**Prediction:** Each edge has two Established eBGP peers; the firewall has one
peer to each edge. Only the client and server LAN prefixes should be originated
by the edges.

**Commands:**

```sh
docker compose exec edge-a vtysh -c 'show bgp summary'
docker compose exec transit-fw vtysh -c 'show bgp summary'
docker compose exec edge-b vtysh -c 'show bgp summary'
docker compose exec edge-a vtysh -c 'show bgp ipv4 unicast'
docker compose exec edge-b vtysh -c 'show bgp ipv4 unicast'
```

**Evidence:** Record peer states, prefixes, and AS paths; capture the output,
not only a paraphrase. If a route output differs across FRR versions, include
the full command output and version (`docker compose exec edge-a vtysh -c
'show version'`).

**Interpretation:** The directly connected edge session is eBGP between
65010/65020. Each edge-to-firewall session is eBGP to 65000. The firewall
forwards selected learned routes; it does not originate either endpoint
prefix.

**Reflection:** Why does a route learned from Edge-A not loop back to Edge-A
through the firewall? Which configuration restricts each edge's advertised
prefixes?

## Lab 3 — BGP decision process and FIB

**Prediction:** Both route candidates exist for each remote prefix. LOCAL_PREF
200 via transit wins over 100 via direct despite the longer AS_PATH. The
selected kernel route uses `eth2`.

**Commands:**

```sh
docker compose exec edge-a vtysh -c 'show bgp ipv4 unicast 10.112.1.0/24'
docker compose exec edge-b vtysh -c 'show bgp ipv4 unicast 10.111.1.0/24'
docker compose exec edge-a ip route get 10.112.1.10
docker compose exec edge-b ip route get 10.111.1.10
```

**Evidence:** Preserve BGP output showing candidate paths and the route lookup
showing the selected interface. Note any FRR formatting/version differences.

**Interpretation:** BGP selects a path and programs a route; Linux then forwards
packets using the FIB. LOCAL_PREF is an intra-AS policy attribute and is not
sent to eBGP peers. The direct candidate has a shorter AS_PATH, but that does
not outrank the higher LOCAL_PREF.

**Reflection:** If local preference were equal, which attributes would you
inspect next? Why would changing MED on one edge not be equivalent to changing
LOCAL_PREF?

## Lab 4 — Stateful firewall and connection tracking

**Prediction:** A client request increments the firewall's client-to-server
HTTP rule counter. A response crossing the firewall matches `established`,
not the `new`-flow rule.

**Commands:**

```sh
docker compose exec transit-fw nft -a list chain inet routing_lab forward
docker compose exec transit-fw conntrack -L -p tcp
python3 app/labctl.py probe
docker compose exec transit-fw nft -a list chain inet routing_lab forward
docker compose exec transit-fw conntrack -L -p tcp
```

`conntrack -L` may exit nonzero when there are no listed entries. Run it while
a request is in progress for a short-lived connection, or repeat it while
capturing. Do not treat an empty post-request table as a failed firewall test.

**Evidence:** Compare packet/byte counters before and after the probe. Record
conntrack state if observable. Capture command exit status and error text if
the installed conntrack utility reports a permission or compatibility issue.

**Interpretation:** The policy is in `configs/nftables.conf`. `ct state
established,related` accepts reverse packets only when they traverse this
network namespace and conntrack has associated them with the flow. The `new`
rule authorizes only the intended client subnet, server subnet, interface
direction, and service port.

**Reflection:** Does conntrack create an in-path enforcement point for packets
that route elsewhere? What is the difference between “state exists” and “the
firewall observed both directions”?

## Lab 5 — Deliberate asymmetric return route

**Prediction:** Edge-A continues forwarding toward the server using firewall
transit `eth2`. Edge-B changes its client route to direct `eth3`. Under this
lab's stateful default-drop policy, the SYN/ACK bypasses the firewall and the
subsequent client ACK/data packets should be dropped because the firewall
never saw the reverse handshake. Expect an HTTP timeout and an increased
explicit nftables drop counter. This is a prediction about this exact policy,
not a universal claim about asymmetric routing.

**Command:**

```sh
python3 app/labctl.py scenario asymmetric
python3 app/labctl.py status
docker compose exec transit-fw nft -a list chain inet routing_lab forward
docker compose exec transit-fw conntrack -L -p tcp
```

For a short packet capture, open one terminal and run:

```sh
docker compose exec transit-fw tcpdump -ni any -w /captures/asymmetric-fw.pcap 'host 10.111.1.10 and host 10.112.1.10'
```

Stop capture with Ctrl-C, then generate a fresh HTTP request:

```sh
python3 app/labctl.py probe
```

The shared `evidence/captures` directory is local to this project. A
complementary capture on Edge-B's direct interface can establish the return
path:

```sh
docker compose exec edge-b tcpdump -ni eth3 -c 20 'host 10.111.1.10 and host 10.112.1.10'
```

**Evidence:** Record both route lookups, probe status/body, the firewall drop
counter before/after, conntrack state, and packet capture filenames/filters. A
useful packet sequence is SYN on the firewall's `eth1`, SYN/ACK on Edge-B
`eth3`, then client ACK/data dropped on the firewall. A capture showing one
path alone is not sufficient to prove the other direction.

**Interpretation:** One packet flow can use different routers in its two
directions. With a direct return, conntrack on the firewall sees only the SYN.
The client ACK and request data still route through Edge-A and the firewall;
because the firewall never saw the SYN/ACK, those packets fail its
`established,related` check and hit the explicit drop rule. The strict stateful
policy therefore times out this HTTP flow, even though the SYN/ACK physically
reaches the client. A more permissive or stateless policy could let the flow
complete while bypassing inspection. If your observation differs, inspect the
route, rule counters, and captures rather than generalizing.

**Reflection:** What changed—the BGP decision, the firewall rules, or the
application? Which observation is the strongest evidence of bypass? What
additional policy would be needed to make this particular lab fail closed?

## Lab 6 — Link failure, convergence, and recovery

**Prediction:** Disabling Edge-A `eth2` tears down its transit BGP session.
After route withdrawal, both edges use direct `eth3`; the service should be
reachable over that path, outside the firewall's enforcement.

**Commands:**

```sh
python3 app/labctl.py scenario failover
python3 app/labctl.py status
python3 app/labctl.py scenario restore
python3 app/labctl.py status
```

**Evidence:** Record the scenario start/end time, selected interfaces before
and after, BGP peer-state transitions, HTTP result, and recovery result. Repeat
the failover several times if measuring convergence; report each sample and
the measurement method rather than claiming a single run is a distribution.

**Interpretation:** A BGP session failure withdraws paths learned over that
session. The remaining direct route allows reachability here because the
second topology path is intentionally available. This is not a test of every
failure mode: a control-plane state change, a carrier loss, a silent blackhole,
and an application failure can have different detection times.

**Reflection:** What failure did `ip link set down` simulate, and what did it
not? How would BFD or tuned hold timers affect detection? What security
trade-off did this failover policy make?

## Lab 7 — Incident response: preserve inspection on failover

The incident narrative, evidence checklist, rollback, and residual-risk
template are in [`INCIDENT.md`](INCIDENT.md). This lab operationalizes it.

**Prediction:** The deliberately fail-open `failover` scenario restores HTTP
through direct `eth3`; this violates the inspection requirement even though
the service is available. After applying `mitigate`, the protected prefixes
are not exported to the direct peer. If transit fails, the routes disappear
and the service becomes unavailable rather than bypassing the firewall.

**Commands:**

```sh
python3 app/labctl.py scenario failover
python3 app/labctl.py scenario restore
python3 app/labctl.py scenario mitigate
python3 app/labctl.py status
python3 app/labctl.py scenario failover-blocked
python3 app/labctl.py scenario restore
```

Run `restore` between the two different failure modes. Each scenario changes
in-memory router state. Recreate the lab if state is unknown:
`docker compose down && docker compose up --build -d`.

**Evidence:** For the fail-open case, retain route lookups for both endpoints
and HTTP status 200. For mitigation, inspect BGP routes and selected FIB
interfaces; both should use transit `eth2`. Under blocked failover, confirm
the protected routes are withdrawn (no route lookup succeeds), HTTP is not
200, and the firewall remains the only advertised path when transit is up.

**Interpretation:** Availability and policy compliance are distinct
objectives. The added `DIRECT-OUT` route maps deny `10.111.1.0/24` and
`10.112.1.0/24` only on the direct eBGP adjacencies; the firewall transit
advertisements remain allowed. The router entrypoint removes Docker's
injected default route so a missing protected BGP route cannot fall through
to an unmodeled gateway. The fail-closed outcome is an intentional availability
loss. In production, an alternate path must itself meet inspection requirements
before it can satisfy both goals.

**Reflection:** What evidence would prove that only the protected prefixes are
filtered? How might a more-specific prefix, route leak, policy-order mistake,
or new peer defeat this remediation? What SLO and escalation path should
accompany a security-mandated outage?

## Lab 8 — Test design and evidence quality

**Prediction:** A sound test will distinguish the expected route, policy,
packet path, and application outcome; none alone proves every layer.

**Command:**

```sh
python3 -m unittest discover -s tests -v
docker compose config
```

**Evidence:** Preserve test output and record Docker/Compose/FRR versions. The
unit tests validate route-output parsing, drop-counter parsing, and probe
status handling; Compose config validates declarative syntax. Neither starts
containers or verifies BGP convergence.

**Interpretation:** Assertions are scoped: baseline and failover assert exact
route interfaces and expected HTTP status; asymmetric asserts the route split,
the expected timeout under this exact stateful policy, and an increasing drop
counter. This avoids generalizing the observed timeout to every asymmetric
network.

**Reflection:** Which tests are unit, configuration, and integration tests?
What test would catch an accidentally broadened nftables rule? How would you
avoid a flaky fixed sleep when testing convergence?

## Lab 9 — Limitations and architecture trade-offs

Discuss each limitation using evidence from this project:

- Docker bridge networks model isolated L2 segments, not physical Ethernet,
  production switch policy, ECMP, hardware forwarding, or real link latency.
- FRR runs in containers with Linux namespaces/capabilities; control-plane
  timing and kernel details differ from appliances and cloud routers.
- `ip link set down` is a clean local interface failure, not a realistic
  fiber/underlay fault or silent upstream blackhole.
- This firewall is a routed nftables host, not a managed cloud firewall. Cloud
  route tables, appliance insertion, source/destination checks, security
  groups, NAT, and provider-specific health checks are not reproduced.
- Containers share a host kernel; avoid treating their isolation as a security
  boundary suitable for hostile workloads.
- Docker image base tags are pinned, but package repository contents can change.
  A regulated or archival run would snapshot/pin the package repository and
  record image digests.
- No Prometheus/Grafana stack is included: BGP/FIB/nftables/pcap evidence keeps
  the learning signal clear and avoids an additional telemetry architecture.

**Reflection:** Which limitation could invalidate your conclusion? Which is
merely a difference in implementation? What extra evidence or alternate
platform would address it?

## Oral-defense / interview prompts

1. Draw a packet's forward and return path in baseline. Which AS does each BGP
   update cross, and which next hop does the FIB select?
2. Why does LOCAL_PREF 200 beat a shorter AS_PATH? Where is LOCAL_PREF
   propagated, and where is it not?
3. What exact evidence establishes asymmetric routing? Why is one successful
   HTTP request not proof of symmetry?
4. Explain how nftables conntrack sees the initial SYN and what happens if the
   SYN/ACK bypasses the namespace. Why may the TCP connection still succeed?
5. How do interface-down withdrawal, BGP hold-timer expiry, and a silent
   blackhole differ? Which does this experiment represent?
6. How would you fail closed while preserving redundancy? Discuss route policy,
   service chaining, explicit path validation, and availability trade-offs.
7. What changes would be required to transfer the model to AWS or Azure? Name
   provider-managed constructs and state clearly that this lab deploys none.
8. Which assertions are deterministic, which depend on timing, and how would
   you measure convergence with defensible repeated samples?

## Capstone: design a policy-safe failover

Produce a short reproducible report and a live demonstration. Extend the lab
with one clearly scoped routing/security policy (for example, make the
firewall the only permitted path for server traffic and document the
availability consequence when transit fails). Do not claim a solution based
only on BGP routes: verify packet path and application behavior. Keep changes
local, document all commands, and retain a clean restore path.

### Required report

1. An annotated topology, address plan, ASNs, interface map, and threat/ trust
   boundary statement.
2. Hypotheses for baseline, asymmetric route policy, failure, and recovery.
3. Route/BGP output, nftables counters, at least one appropriately filtered
   packet capture, and HTTP results for each state.
4. A tested policy change, deterministic assertions, and explicit limitations.
5. Measured results labeled with platform/version, UTC timestamps, run count,
   and measurement method. Separate expected results from observations.
6. A five-minute oral explanation of route selection, conntrack, failure
   behavior, and the availability/security trade-off.

### Rubric (100 points)

| Area | Points | Full-credit evidence |
|---|---:|---|
| Topology and routing model | 20 | Correct L2/L3/AS/path explanation tied to route outputs |
| Firewall and flow-state reasoning | 20 | Correct rule/counter/conntrack interpretation; bypass vs. drop distinguished |
| Experiment quality | 20 | Falsifiable predictions, exact commands, useful captures, repeated timings where claimed |
| Implementation and recovery | 15 | Scoped policy, tested assertions, clean recovery and no unrelated host changes |
| Limitations and trade-offs | 15 | Honest simulation/cloud boundary and availability/security analysis |
| Communication and reproducibility | 10 | Another learner can repeat it; evidence and versions are clearly labeled |

## Glossary

| Term | Meaning in this lab |
|---|---|
| AS / ASN | BGP administrative routing domain and its number |
| eBGP | BGP session between different autonomous systems |
| Prefix | Network and mask, such as `10.112.1.0/24` |
| AS_PATH | AS sequence carried with a BGP route |
| LOCAL_PREF | Preference within an AS; higher value wins before AS_PATH comparison |
| RIB | Routing information base; protocol's candidate/selected routes |
| FIB | Forwarding information base used for packet forwarding |
| Conntrack | Linux connection tracking state used by stateful nftables rules |
| Asymmetry | Forward and return packets use different network paths |
| Convergence | Time for routing state to settle after a change or failure |
| Service chaining | Steering a flow through required middleboxes such as firewalls |
