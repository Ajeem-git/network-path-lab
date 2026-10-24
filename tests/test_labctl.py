import unittest
import sys
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
from subprocess import CompletedProcess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import labctl


class RouteDeviceTests(unittest.TestCase):
    @patch("labctl.inside", return_value="10.112.1.10 via 172.16.10.3 dev eth2 src 172.16.10.2")
    def test_route_device_extracts_selected_interface(self, _inside):
        self.assertEqual(labctl.route_device("edge-a", "10.112.1.10"), "eth2")

    @patch("labctl.inside", return_value="10.112.1.10 dev eth3 src 172.16.12.2")
    def test_route_device_handles_directly_connected_route_output(self, _inside):
        self.assertEqual(labctl.route_device("edge-a", "10.112.1.10"), "eth3")

    @patch("labctl.inside", return_value="unreachable 10.112.1.10")
    def test_route_device_fails_if_no_device_is_selected(self, _inside):
        with self.assertRaises(labctl.LabError):
            labctl.route_device("edge-a", "10.112.1.10")


class ProbeTests(unittest.TestCase):
    @patch("labctl.compose", return_value=CompletedProcess([], 0, "HTTP 200: {\"status\":\"ok\"}\n", ""))
    def test_probe_runs_and_returns_http_status(self, _compose):
        with redirect_stdout(StringIO()):
            self.assertEqual(labctl.probe(), 200)

    @patch("labctl.compose", return_value=CompletedProcess([], 1, "HTTP probe failed: timeout\n", ""))
    def test_probe_reports_failure_without_claiming_http_status(self, _compose):
        with redirect_stdout(StringIO()):
            self.assertEqual(labctl.probe(), 0)


class DropCounterTests(unittest.TestCase):
    def test_parse_drop_counter(self):
        output = "ct state established counter packets 4 bytes 240 accept\ncounter packets 7 bytes 420 drop"
        self.assertEqual(labctl.parse_drop_counter(output), 7)

    def test_parse_drop_counter_rejects_missing_rule(self):
        with self.assertRaises(labctl.LabError):
            labctl.parse_drop_counter("ct state established counter packets 4 bytes 240 accept")


class PolicyTests(unittest.TestCase):
    @patch("labctl.time.sleep")
    @patch("labctl.inside")
    def test_direct_export_policy_denies_protected_prefixes_at_both_edges(self, inside, _sleep):
        labctl.direct_export_policy(False)
        self.assertEqual(inside.call_count, 2)
        self.assertEqual(inside.call_args_list[0][0][0], "edge-a")
        self.assertIn("-c", inside.call_args_list[0][0])
        self.assertIn("route-map DIRECT-OUT deny 10", inside.call_args_list[0][0])
        self.assertIn("match ip address prefix-list CLIENT", inside.call_args_list[0][0])
        self.assertIn("clear ip bgp 172.16.12.3 soft out", inside.call_args_list[0][0])
        self.assertEqual(inside.call_args_list[1][0][0], "edge-b")
        self.assertIn("route-map DIRECT-OUT deny 10", inside.call_args_list[1][0])
        self.assertIn("match ip address prefix-list SERVER", inside.call_args_list[1][0])
        self.assertIn("clear ip bgp 172.16.12.2 soft out", inside.call_args_list[1][0])

    @patch("labctl.time.sleep")
    @patch("labctl.inside")
    def test_direct_export_policy_can_restore_permitted_experiment_path(self, inside, _sleep):
        labctl.direct_export_policy(True)
        self.assertTrue(all("route-map DIRECT-OUT permit 10" in call_args[0] for call_args in inside.call_args_list))

    def test_scenario_parser_exposes_incident_and_recovery_commands(self):
        parser = labctl.build_parser()
        scenario_action = next(
            action
            for action in parser._subparsers._group_actions[0].choices["scenario"]._actions
            if action.dest == "name"
        )
        self.assertEqual(set(scenario_action.choices), set(labctl.SCENARIO_CHOICES))
        self.assertIn("mitigate", scenario_action.choices)
        self.assertIn("failover-blocked", scenario_action.choices)
        self.assertIn("restore", scenario_action.choices)


if __name__ == "__main__":
    unittest.main()
