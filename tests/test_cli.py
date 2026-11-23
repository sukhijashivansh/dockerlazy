import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1] / "docker-lazy"
cli = runpy.run_path(str(PLUGIN))


def fixture():
    return {
        "Name": "/demo", "Id": "abcd", "Config": {"Image": "alpine"},
        "State": {"Status": "running"}, "HostConfig": {"NetworkMode": "bridge"},
        "NetworkSettings": {"Networks": {"dev": {"IPAddress": "172.18.0.2", "IPPrefixLen": 16}}},
        "Mounts": [{"Type": "volume", "Name": "v1", "Destination": "/data", "RW": True}],
    }


class PluginTests(unittest.TestCase):
    def test_metadata_without_daemon(self):
        result = subprocess.check_output([str(PLUGIN), "docker-cli-plugin-metadata"])
        self.assertEqual(json.loads(result)["SchemaVersion"], "0.1.0")

    def test_context_forwarding_and_scoped_json(self):
        stdout = io.StringIO()
        with patch.dict(os.environ, DOCKER_CLI_PLUGIN_ORIGINAL_CLI_COMMAND="docker"), \
                patch("subprocess.check_output", return_value=json.dumps([fixture()])) as call, \
                contextlib.redirect_stdout(stdout):
            cli["main"](["--context", "lazy", "lazy", "demo", "--only", "network", "--json"])
        call.assert_called_once_with(["docker", "--context", "lazy", "container", "inspect", "--", "demo"])
        sections = json.loads(stdout.getvalue())["sections"]
        self.assertEqual(list(sections), ["network"])
        self.assertIn("172.18.0.2/16", sections["network"][0]["value"])

    def test_stopped_with_limits(self):
        container = fixture()
        container["State"]["Status"] = "exited"
        container["HostConfig"].update(CpuQuota=50000, Memory=67108864, CpusetCpus="2-3")
        with patch("subprocess.run") as runner:
            snapshot = cli["resource_snapshot"](container, ["docker"], False)
            rows = dict(cli["resource_rows"](snapshot))
        runner.assert_not_called()
        self.assertIn("0.5 cores", rows["Limits"])
        self.assertIn("64 MiB", rows["Limits"])
        self.assertIn("2-3", rows["Limits"])
        self.assertIn("exited", rows["Usage"])

    def test_terminal_layout_at_multiple_widths(self):
        container = fixture()
        container["Config"]["Image"] = "registry.example/" + "image" * 15
        container["Mounts"][0]["Destination"] = "/資料/" + "data/" * 10
        for width in (32, 48, 80, 120):
            with self.subTest(width=width):
                stream = io.StringIO()
                stream.isatty = lambda: True
                with patch.dict(os.environ, COLUMNS=str(width), NO_COLOR="1"), \
                        patch("sys.platform", "linux"), \
                        patch("subprocess.check_output", return_value=json.dumps([container])), \
                        contextlib.redirect_stdout(stream):
                    cli["main"](["lazy", "demo", "--fast"])
                output = stream.getvalue()
                self.assertNotIn("\033", output)
                self.assertIn("Uncapped", output)
                self.assertNotIn("In use", output)
                self.assertIn("資料", output)
                for line in output.splitlines():
                    self.assertLessEqual(sum(map(cli["cell_width"], line)), width)

    def test_ports_and_storage(self):
        container = fixture()
        container["Config"]["ExposedPorts"] = {"80/tcp": {}, "443/tcp": {}}
        container["NetworkSettings"]["Ports"] = {
            "80/tcp": [{"HostIp": "::1", "HostPort": "8080"}, {"HostIp": "0.0.0.0", "HostPort": "8081"}],
            "443/tcp": None,
        }
        with patch("sys.platform", "linux"):
            ports = cli["access_rows"](container)
        self.assertIn(("Published", "[::1]:8080 -> 80/tcp  (loopback)"), ports)
        self.assertIn(("Published", "0.0.0.0:8081 -> 80/tcp  (all IPv4 interfaces)"), ports)
        self.assertIn(("Declared ports", "443/tcp (no active mapping)"), ports)
        self.assertIn("v1 -> /data", cli["storage_rows"](container)[0][1])

    def test_header_details_and_metrics_share_columns(self):
        header = dict(name="容器", image="alpine", id="123456789abc", status="running",
                      health=None, restarts=0)
        sections = {"network": [("Network", "n1", "172.18.0.2/16")],
                    "access": [("Mac app firewall", "Off")]}
        snapshot = dict(sample=("0.00%", "2.234MiB", "1"), cpu=None, memory=None,
                        pids=None, cpuset=None, message=None)
        stream = io.StringIO()
        stream.isatty = lambda: True
        with patch.dict(os.environ, COLUMNS="110", NO_COLOR="1"), contextlib.redirect_stdout(stream):
            cli["render"](header, sections, snapshot)
        lines = stream.getvalue().splitlines()

        def column(label, value):
            line = next(line for line in lines if line.startswith(label))
            return sum(map(cli["cell_width"], line[:line.index(value)]))

        self.assertEqual(column("Container", "容器"), column("Network", "n1"))
        self.assertEqual(column("Network", "n1"), column("Memory", "2.234 MiB"))
        self.assertEqual(column("Container", "running"), column("Image", "123456789abc"))
        self.assertEqual(column("Network", "172.18"), column("Resource", "Limit"))
        self.assertEqual(column("Resource", "Limit"), column("CPU", "Uncapped"))

    def diff_pair(self):
        left, right = fixture(), fixture()
        left["Name"], right["Name"] = "/c1", "/c2"
        left["Image"], right["Image"] = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        right["HostConfig"]["Memory"] = 67108864
        right["Mounts"] = []
        right["Config"]["ExposedPorts"] = {"80/tcp": {}}
        right["NetworkSettings"]["Ports"] = {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}
        return left, right

    def test_diff_json_reports_only_changes(self):
        left, right = self.diff_pair()
        stdout = io.StringIO()
        with patch("subprocess.check_output", side_effect=[json.dumps([left]), json.dumps([right])]) as call, \
                patch("subprocess.run") as runner, contextlib.redirect_stdout(stdout):
            cli["main"](["--context", "lazy", "lazy", "diff", "c1", "--json", "c2"])
        runner.assert_not_called()
        self.assertEqual(call.call_args_list[1].args[0],
                         ["docker", "--context", "lazy", "container", "inspect", "--", "c2"])
        report = json.loads(stdout.getvalue())
        self.assertFalse(report["identical"])
        self.assertEqual(list(report["differences"]), ["container", "storage", "resources", "access"])
        rows = {row["label"]: row for group in report["differences"].values() for row in group}
        self.assertEqual(rows["Memory limit"]["left"], "Uncapped")
        self.assertEqual(rows["Memory limit"]["right"], "64 MiB")
        self.assertIsNone(rows["Port 80/tcp"]["left"])
        self.assertIsNone(rows["Mount /data"]["right"])
        self.assertNotIn("Network dev", rows)

    def test_diff_identical_and_scoped(self):
        left, right = self.diff_pair()
        self.assertEqual(cli["compare"](left, left)[0], {})
        self.assertEqual(list(cli["compare"](left, right, "storage")[0]), ["storage"])

    def test_diff_layout_at_multiple_widths(self):
        left, right = self.diff_pair()
        right["Config"]["Image"] = "registry.example/" + "image" * 15
        changes, matching = cli["compare"](left, right)
        for width in (32, 48, 80, 120):
            with self.subTest(width=width):
                stream = io.StringIO()
                stream.isatty = lambda: True
                with patch.dict(os.environ, COLUMNS=str(width), NO_COLOR="1"), \
                        contextlib.redirect_stdout(stream):
                    cli["render_diff"](["c1", "c2"], changes, matching)
                output = stream.getvalue()
                self.assertIn("Memory limit", output)
                self.assertIn("differences", output)
                for line in output.splitlines():
                    self.assertLessEqual(sum(map(cli["cell_width"], line)), width)

    def test_container_named_diff_and_argument_errors(self):
        stdout = io.StringIO()
        with patch("subprocess.check_output", return_value=json.dumps([fixture()])) as call, \
                contextlib.redirect_stdout(stdout):
            cli["main"](["lazy", "diff", "--only", "network", "--json"])
        self.assertEqual(call.call_args.args[0][-1], "diff")
        for args in (["lazy", "diff", "c1"], ["lazy", "diff", "c1", "c2", "c3"], ["lazy", "c1", "c2"]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as raised:
                cli["main"](args)
            self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
