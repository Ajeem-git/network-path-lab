# Operations and troubleshooting

## Lifecycle

```sh
docker compose config
docker compose up --build -d
docker compose ps
python3 app/labctl.py status
python3 app/labctl.py scenario baseline
python3 app/labctl.py scenario mitigate
python3 app/labctl.py scenario failover-blocked
python3 app/labctl.py scenario restore
docker compose down
```

Run `docker compose down --rmi local` to remove locally built images too.
Scenario runner commands must be run from the project root. The runner changes
in-memory LOCAL_PREF, direct-peer route maps, and Edge-A's `eth2` state.
`restore` returns these to baseline. The router entrypoint removes each
container's Docker-injected default route; protected traffic therefore cannot
fall through an unmodeled default path when BGP withdraws its route. If a
scenario is interrupted or the current state is unknown, run restore; if that
does not converge, recreate the lab with
`docker compose down && docker compose up --build -d`.

The production-style incident sequence is documented in
[`INCIDENT.md`](INCIDENT.md). `failover` intentionally demonstrates a fail-open
design; use `mitigate` to filter protected-prefix advertisements on direct
peers, then `failover-blocked` to verify that transit loss causes an outage
instead of firewall bypass. This is a teaching model, not a production change
procedure.

Captured packet files go to `evidence/captures/` and are ignored by version
control. Keep only captures needed for a report; inspect packet data before
sharing it. Do not put credentials or unrelated traffic in evidence.

## Troubleshooting decision tree

### Compose fails before startup

Run `docker compose config` and read its exact validation error. Confirm
Compose v2 supports `interface_name`, and no other local network uses any of
the lab's fixed subnets. Docker Desktop must be running and have enough memory
and CPU to build Debian-based images.

### Containers start, but health is unhealthy

```sh
docker compose ps
docker compose logs --tail=100 edge-a transit-fw edge-b web
docker compose exec edge-a vtysh -c 'show daemons'
docker compose exec edge-a ip -br address
```

Confirm `zebra` and `bgpd` are enabled in `configs/frr/daemons`, and that
`frrinit.sh` started them. Check the mounted FRR configuration and logs before
editing policy. Router health means FRR's route command responds, not that every
BGP neighbor is Established.

### BGP is Established but no expected route appears

```sh
docker compose exec edge-a vtysh -c 'show bgp summary'
docker compose exec edge-a vtysh -c 'show bgp ipv4 unicast'
docker compose exec edge-a vtysh -c 'show ip route'
docker compose exec edge-a ip -br address
```

Check that the `network` prefix exactly exists in the kernel RIB, prefix-list
and route-map names match, and the route-map is applied in the intended
direction and address family. Compare peer addresses to the topology table.

### Baseline picks the wrong interface

```sh
docker compose exec edge-a vtysh -c 'show bgp ipv4 unicast 10.112.1.0/24'
docker compose exec edge-a ip route get 10.112.1.10
docker compose exec edge-b vtysh -c 'show bgp ipv4 unicast 10.111.1.0/24'
docker compose exec edge-b ip route get 10.111.1.10
```

Check LOCAL_PREF on both candidates, then soft-clear inbound updates:

```sh
docker compose exec edge-a vtysh -c 'clear ip bgp * soft in'
docker compose exec edge-b vtysh -c 'clear ip bgp * soft in'
```

The scenario runner waits up to 45 seconds; if it times out, inspect the route
outputs rather than repeatedly rerunning without diagnosing the cause.

### Route is correct but the probe fails

```sh
docker compose exec client ip route get 10.112.1.10
docker compose exec web ip route get 10.111.1.10
docker compose exec transit-fw nft -a list ruleset
docker compose exec transit-fw sysctl net.ipv4.ip_forward
docker compose logs --tail=50 web
```

Check the endpoint static route, firewall `forward` counters, web health, and
router forwarding. Test path evidence with narrowly filtered captures on the
client, firewall, and direct link. A successful route lookup is not proof that
the packet traverses the intended firewall.

### Return-path assertion fails after a previous scenario

```sh
python3 app/labctl.py scenario restore
python3 app/labctl.py status
```

`failover` leaves Edge-A's interface down until `restore`. `asymmetric` changes
Edge-B's in-memory route preference until `restore`. `mitigate` changes
direct-peer outbound route maps in memory; `failover-blocked` leaves Edge-A's
transit interface down. These changes are not written to the mounted FRR
configuration and disappear when containers are recreated. Always use
`restore` before unrelated experiments.

## Platform and evidence notes

Docker Desktop runs these Linux containers inside its VM. Host packet capture
tools may not see container traffic as expected; capture inside the specific
router namespace with `docker compose exec`. Timestamp and label measurements
as observations from this VM/runtime, not as a general property of cloud
networks. Do not expose router ports to the host or add public port publishing.
The Debian FRR package's privilege setup requires `SYS_ADMIN` alongside
`NET_ADMIN` and `NET_RAW`; this is why only the three routing containers receive
it. This is elevated container capability, not `--privileged`; understand the
host's container isolation boundary before adapting the lab to a shared Linux
machine.
