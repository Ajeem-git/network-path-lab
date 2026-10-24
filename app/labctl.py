#!/usr/bin/env python3
"""Scenario runner for the local Docker Compose routing lab."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from collections.abc import Sequence


class LabError(RuntimeError):
    pass


SCENARIO_CHOICES = ("baseline", "asymmetric", "failover", "mitigate", "failover-blocked", "restore")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    scenario = subparsers.add_parser("scenario", help="run an asserted routing experiment")
    scenario.add_argument("name", choices=SCENARIO_CHOICES)
    subparsers.add_parser("status", help="print BGP, route, and firewall state")
    subparsers.add_parser("probe", help="issue one HTTP request from the client container")
    return parser


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", "compose", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if check and result.returncode:
        raise LabError(result.stdout.strip() or f"docker compose exited {result.returncode}")
    return result


def inside(service: str, *command: str, check: bool = True) -> str:
    result = compose("exec", "-T", service, *command, check=check)
    return result.stdout.strip()


def route_device(service: str, destination: str) -> str:
    output = inside(service, "ip", "route", "get", destination)
    for token, value in zip(output.split(), output.split()[1:]):
        if token == "dev":
            return value
    raise LabError(f"Cannot determine route device on {service}: {output}")


def expect_route(service: str, destination: str, device: str) -> None:
    actual = route_device(service, destination)
    print(f"{service} -> {destination}: {actual}")
    if actual != device:
        raise LabError(f"Expected {service} -> {destination} via {device}, got {actual}")


def parse_drop_counter(output: str) -> int:
    for line in output.splitlines():
        if line.strip().endswith("drop"):
            match = re.search(r"counter packets (\d+)", line)
            if match:
                return int(match.group(1))
    raise LabError("Could not find the nftables forward-chain drop counter")


def firewall_drop_packets() -> int:
    output = inside("transit-fw", "nft", "list", "chain", "inet", "routing_lab", "forward")
    return parse_drop_counter(output)


def probe() -> int:
    result = compose("exec", "-T", "client", "python3", "/app/probe.py", check=False)
    output = result.stdout.strip()
    print(output)
    if result.returncode:
        return 0
    try:
        return int(output.split(" ", 2)[1].rstrip(":"))
    except (IndexError, ValueError) as exc:
        raise LabError(f"Unexpected HTTP probe output: {output}") from exc


def policy(direct_preference: int, transit_preference: int = 200) -> None:
    commands: Sequence[str] = (
        "configure terminal",
        "route-map DIRECT-IN permit 10",
        "set local-preference " + str(direct_preference),
        "route-map TRANSIT-IN permit 10",
        "set local-preference " + str(transit_preference),
        "end",
        "clear ip bgp * soft in",
    )
    inside("edge-b", "vtysh", *sum((("-c", item) for item in commands), ()))
    time.sleep(2)


def direct_export_policy(permit: bool) -> None:
    action = "permit" if permit else "deny"
    for service, peer, prefix_list in (
        ("edge-a", "172.16.12.3", "CLIENT"),
        ("edge-b", "172.16.12.2", "SERVER"),
    ):
        commands = (
            "configure terminal",
            "no route-map DIRECT-OUT permit 10",
            f"route-map DIRECT-OUT {action} 10",
            f"match ip address prefix-list {prefix_list}",
            "end",
            f"clear ip bgp {peer} soft out",
        )
        inside(service, "vtysh", *sum((("-c", item) for item in commands), ()))
    time.sleep(2)


def wait_for_routes(checks: Sequence[tuple[str, str, str]], timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            for service, destination, expected in checks:
                actual = route_device(service, destination)
                if actual != expected:
                    raise LabError(f"{service} route to {destination}: expected {expected}, got {actual}")
            return
        except LabError as exc:
            last_error = str(exc)
            time.sleep(1)
    raise LabError(f"Routes did not converge within {timeout:.0f}s: {last_error}")


def wait_for_no_routes(checks: Sequence[tuple[str, str]], timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        pending = []
        for service, destination in checks:
            result = compose("exec", "-T", service, "ip", "route", "get", destination, check=False)
            if result.returncode == 0:
                pending.append(f"{service} still routes {destination} via {result.stdout.strip()}")
            elif "Network is unreachable" not in result.stdout:
                raise LabError(f"Unexpected route lookup failure on {service}: {result.stdout.strip()}")
        if not pending:
            return
        last_error = "; ".join(pending)
        time.sleep(1)
    raise LabError(f"Protected routes were not withdrawn within {timeout:.0f}s: {last_error}")


def run_scenario(name: str) -> None:
    if name == "baseline":
        policy(100)
        checks = (("edge-a", "10.112.1.10", "eth2"), ("edge-b", "10.111.1.10", "eth2"))
        wait_for_routes(checks)
        for service, destination, device in checks:
            expect_route(service, destination, device)
        status = probe()
        if status != 200:
            raise LabError(f"Expected HTTP 200 in baseline, got {status}")
        print("PASS: both directions select the firewall transit links.")
    elif name == "asymmetric":
        policy(300)
        checks = (("edge-a", "10.112.1.10", "eth2"), ("edge-b", "10.111.1.10", "eth3"))
        wait_for_routes(checks)
        for service, destination, device in checks:
            expect_route(service, destination, device)
        drops_before = firewall_drop_packets()
        status = probe()
        drops_after = firewall_drop_packets()
        print(f"HTTP outcome under asymmetric routing: {status or 'failed'}")
        print(f"Firewall forward-chain drops during probe: {drops_after - drops_before}")
        if status != 0:
            raise LabError(f"Expected the stateful default-drop policy to block the asymmetric flow; got HTTP {status}")
        if drops_after <= drops_before:
            raise LabError("Expected the firewall drop counter to increase after the asymmetric probe")
        print("PASS: the direct return path bypasses conntrack; later client packets are dropped by the firewall.")
    elif name == "failover":
        direct_export_policy(True)
        inside("edge-a", "ip", "link", "set", "dev", "eth2", "down")
        checks = (("edge-a", "10.112.1.10", "eth3"), ("edge-b", "10.111.1.10", "eth3"))
        wait_for_routes(checks)
        for service, destination, device in checks:
            expect_route(service, destination, device)
        status = probe()
        if status != 200:
            raise LabError(f"Expected HTTP 200 over the direct failover path, got {status}")
        print("PASS: BGP reconverged over the direct edge link; the firewall is bypassed.")
    elif name == "mitigate":
        inside("edge-a", "ip", "link", "set", "dev", "eth2", "up")
        policy(100)
        direct_export_policy(False)
        checks = (("edge-a", "10.112.1.10", "eth2"), ("edge-b", "10.111.1.10", "eth2"))
        wait_for_routes(checks)
        for service, destination, device in checks:
            expect_route(service, destination, device)
        status = probe()
        if status != 200:
            raise LabError(f"Expected HTTP 200 through the firewall after mitigation, got {status}")
        print("PASS: protected prefixes use inspected transit; direct BGP advertisements are denied.")
    elif name == "failover-blocked":
        direct_export_policy(False)
        inside("edge-a", "ip", "link", "set", "dev", "eth2", "down")
        checks = (("edge-a", "10.112.1.10"), ("edge-b", "10.111.1.10"))
        wait_for_no_routes(checks)
        for service, destination in checks:
            print(f"{service} -> {destination}: no route (fail closed)")
        status = probe()
        if status == 200:
            raise LabError("Expected protected service to be unavailable when inspected transit fails")
        print("PASS: no direct route is advertised; service fails closed instead of bypassing inspection.")
    elif name == "restore":
        inside("edge-a", "ip", "link", "set", "dev", "eth2", "up")
        policy(100)
        direct_export_policy(True)
        checks = (("edge-a", "10.112.1.10", "eth2"), ("edge-b", "10.111.1.10", "eth2"))
        wait_for_routes(checks)
        for service, destination, device in checks:
            expect_route(service, destination, device)
        status = probe()
        if status != 200:
            raise LabError(f"Expected HTTP 200 after restoration, got {status}")
        print("PASS: transit recovered and both directions again prefer the firewall.")
    else:
        raise LabError(f"Unknown scenario: {name}")


def status() -> None:
    for service in ("edge-a", "transit-fw", "edge-b"):
        print(f"\n== {service}: BGP summary ==")
        print(inside(service, "vtysh", "-c", "show bgp summary"))
    print("\n== edge-a route to server ==")
    print(inside("edge-a", "ip", "route", "get", "10.112.1.10"))
    print("\n== edge-b route to client ==")
    print(inside("edge-b", "ip", "route", "get", "10.111.1.10"))
    print("\n== nftables forward-chain counters ==")
    print(inside("transit-fw", "nft", "list", "chain", "inet", "routing_lab", "forward"))


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.action == "scenario":
            run_scenario(args.name)
        elif args.action == "status":
            status()
        else:
            code = probe()
            if code != 200:
                return 1
    except LabError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
