import dataclasses
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from sandcastle import cli
from sandcastle import config as config_module
from sandcastle import state
from sandcastle import systemd
from sandcastle.errors import LifecycleError

RUNNER_PATH = "/nix/store/11111111111111111111111111111111-microvm-run"
NEW_RUNNER_PATH = "/nix/store/22222222222222222222222222222222-microvm-run"
CONTROL_KEY = "ssh-ed25519 AAAAtest sandcastle-control"


class CliTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="sandcastle-test-")
        self.addCleanup(directory.cleanup)
        self.root = directory.name
        self.state_dir = os.path.join(self.root, "state")
        self.config_path = os.path.join(self.root, "config.json")

        with open(self.config_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "stateDir": self.state_dir,
                    "gcRootDir": os.path.join(self.root, "gcroots"),
                    "flakeRef": "/nix/store/aaa-source",
                    "sshProxy": "/nix/store/aaa-systemd/lib/systemd/systemd-ssh-proxy",
                },
                handle,
            )

        self.config = config_module.load(self.config_path)
        state.ensure_directories(self.config)
        self.store = state.Store(self.config)

        # Nothing in these tests should reach systemd, Nix, or ssh-keygen.
        self.systemd = {}
        for name, value in (
            ("is_active", "inactive"),
            ("active_states", {}),
            ("properties", {}),
            ("confirm_running", {}),
            ("start", None),
            ("stop", None),
            ("restart", None),
        ):
            patcher = mock.patch.object(systemd, name, return_value=value)
            self.systemd[name] = patcher.start()
            self.addCleanup(patcher.stop)

        patcher = mock.patch("sandcastle.ssh.ensure_control_key", return_value=CONTROL_KEY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *arguments):
        out = io.StringIO()
        code = cli.main(["--config", self.config_path, *arguments], out=out)
        return code, out.getvalue()

    def create(self, name, **overrides):
        with state.allocation_lock(self.config):
            allocated = state.allocate(self.config, self.store, name)
            if overrides:
                allocated = dataclasses.replace(allocated, **overrides)
            self.store.save(allocated)
        return allocated


class ListTests(CliTestCase):
    def test_an_empty_installation_says_so(self):
        code, output = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("No sandboxes yet", output)

    def test_table_output_lists_every_sandbox(self):
        self.create("alpha")
        self.create("beta")

        code, output = self.run_cli("list")

        self.assertEqual(code, 0)
        self.assertIn("NAME", output)
        self.assertIn("alpha", output)
        self.assertIn("beta", output)

    def test_json_output_is_machine_readable(self):
        self.create("alpha", packages=["nodejs", "uv"])
        self.systemd["active_states"].return_value = {"alpha": "inactive"}

        code, output = self.run_cli("list", "--json")

        self.assertEqual(code, 0)
        rows = json.loads(output)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "alpha")
        self.assertEqual(rows[0]["packages"], 2)
        self.assertEqual(rows[0]["state"], "inactive")


class ShowTests(CliTestCase):
    def test_json_output_matches_the_stored_spec(self):
        created = self.create("alpha")
        code, output = self.run_cli("show", "alpha", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), created.to_dict())

    def test_human_output_includes_derived_state(self):
        self.create("alpha")
        code, output = self.run_cli("show", "alpha")
        self.assertEqual(code, 0)
        self.assertIn("homeImage:", output)
        self.assertIn("runner: (not installed)", output)

    def test_a_missing_sandbox_exits_non_zero(self):
        code, _ = self.run_cli("show", "absent")
        self.assertEqual(code, 3)

    def test_an_invalid_name_exits_with_the_validation_code(self):
        code, _ = self.run_cli("show", "Not A Name")
        self.assertEqual(code, 2)


class BuildCommandTests(CliTestCase):
    def test_build_prints_the_runner_without_installing_it(self):
        self.create("alpha")
        with mock.patch("sandcastle.build.build_runner", return_value=RUNNER_PATH):
            code, output = self.run_cli("build", "alpha")

        self.assertEqual(code, 0)
        self.assertIn(RUNNER_PATH, output)
        self.assertIsNone(state.installed_runner(self.config, "alpha"))

    def test_build_install_moves_the_current_symlink(self):
        self.create("alpha")
        with mock.patch("sandcastle.build.build_runner", return_value=RUNNER_PATH):
            code, _ = self.run_cli("build", "alpha", "--install")

        self.assertEqual(code, 0)
        self.assertEqual(state.installed_runner(self.config, "alpha"), RUNNER_PATH)
        self.assertEqual(state.read_gc_root(self.config, "alpha", "current"), RUNNER_PATH)


class StatusCommandTests(CliTestCase):
    def test_status_reports_runtime_state_and_the_ssh_destination(self):
        self.create("alpha")
        self.systemd["properties"].return_value = {
            "ActiveState": "active",
            "SubState": "running",
        }

        code, output = self.run_cli("status", "alpha", "--json")

        self.assertEqual(code, 0)
        document = json.loads(output)
        self.assertEqual(document["state"], "active")
        self.assertEqual(document["unit"], "microvm@alpha.service")
        self.assertEqual(document["sshDestination"], f"vsock/{document['vsockCid']}")

    def test_a_stale_guest_is_told_how_to_pick_the_new_runner_up(self):
        self.create("alpha")
        with mock.patch("sandcastle.build.build_runner", return_value=RUNNER_PATH):
            self.run_cli("build", "alpha", "--install")
        state.atomic_symlink(
            os.path.join(self.config.vm_dir("alpha"), "booted"), NEW_RUNNER_PATH
        )

        code, output = self.run_cli("status", "alpha")

        self.assertEqual(code, 0)
        self.assertIn("sandcastle restart alpha", output)


class CreateCommandTests(CliTestCase):
    def test_create_builds_installs_and_leaves_the_sandbox_stopped(self):
        with mock.patch("sandcastle.build.build_runner", return_value=RUNNER_PATH):
            code, output = self.run_cli("create", "alpha", "--packages", "node", "ripgrep")

        self.assertEqual(code, 0)
        self.assertEqual(self.store.load("alpha").packages, ["nodejs", "pnpm", "ripgrep"])
        self.assertEqual(state.installed_runner(self.config, "alpha"), RUNNER_PATH)
        self.assertIn("sandcastle start alpha", output)
        self.systemd["start"].assert_not_called()

    def test_create_start_starts_it(self):
        with mock.patch("sandcastle.build.build_runner", return_value=RUNNER_PATH):
            code, _ = self.run_cli("create", "alpha", "--start")

        self.assertEqual(code, 0)
        self.systemd["start"].assert_called_once_with("alpha")

    def test_an_invalid_package_attribute_is_refused_before_building(self):
        with mock.patch("sandcastle.build.build_runner") as builder:
            code, _ = self.run_cli("create", "alpha", "--packages", "nodejs; rm -rf /")

        self.assertEqual(code, 2)
        builder.assert_not_called()
        self.assertEqual(self.store.names(), [])

    def test_a_duplicate_name_exits_with_the_conflict_code(self):
        self.create("alpha")
        with mock.patch("sandcastle.build.build_runner", return_value=RUNNER_PATH):
            code, _ = self.run_cli("create", "alpha")
        self.assertEqual(code, 4)


class LifecycleCommandTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.create("alpha")
        with mock.patch("sandcastle.build.build_runner", return_value=RUNNER_PATH):
            self.run_cli("build", "alpha", "--install")

    def test_start_stop_and_restart_drive_the_generic_units(self):
        self.assertEqual(self.run_cli("start", "alpha")[0], 0)
        self.systemd["start"].assert_called_once_with("alpha")

        self.assertEqual(self.run_cli("stop", "alpha")[0], 0)
        self.systemd["stop"].assert_called_once_with("alpha")

        self.assertEqual(self.run_cli("restart", "alpha")[0], 0)
        self.systemd["restart"].assert_called_once_with("alpha")

    def test_no_wait_skips_the_readiness_confirmation(self):
        self.assertEqual(self.run_cli("start", "alpha", "--no-wait")[0], 0)
        self.systemd["confirm_running"].assert_not_called()

    def test_a_start_that_never_settles_exits_with_the_lifecycle_code(self):
        self.systemd["confirm_running"].side_effect = LifecycleError("never booted")
        code, _ = self.run_cli("start", "alpha")
        self.assertEqual(code, 8)

    def test_rebuild_prints_the_runner_and_says_when_nothing_changed(self):
        with mock.patch("sandcastle.build.build_runner", return_value=RUNNER_PATH):
            code, output = self.run_cli("rebuild", "alpha")

        self.assertEqual(code, 0)
        self.assertIn("already up to date", output)
        self.assertIn(RUNNER_PATH, output)

    def test_rebuild_installs_a_changed_runner(self):
        with mock.patch("sandcastle.build.build_runner", return_value=NEW_RUNNER_PATH):
            code, output = self.run_cli("rebuild", "alpha")

        self.assertEqual(code, 0)
        self.assertIn(NEW_RUNNER_PATH, output)
        self.assertEqual(state.installed_runner(self.config, "alpha"), NEW_RUNNER_PATH)

    def test_logs_reads_the_hypervisor_and_its_companion_units(self):
        with mock.patch("sandcastle.cli.subprocess.call", return_value=0) as call:
            code, _ = self.run_cli("logs", "alpha", "-n", "5")

        self.assertEqual(code, 0)
        command = call.call_args.args[0]
        self.assertIn("microvm@alpha.service", command)
        self.assertIn("microvm-virtiofsd@alpha.service", command)
        self.assertEqual(command[command.index("--lines") + 1], "5")


class DeleteCommandTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.create("alpha")
        with mock.patch("sandcastle.build.build_runner", return_value=RUNNER_PATH):
            self.run_cli("build", "alpha", "--install")

    def test_delete_needs_confirmation(self):
        code, _ = self.run_cli("delete", "alpha")
        self.assertEqual(code, 1)
        self.assertEqual(self.store.names(), ["alpha"])

    def test_delete_yes_removes_the_sandbox(self):
        code, output = self.run_cli("delete", "alpha", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(self.store.names(), [])
        self.assertIn("removed", output)

    def test_a_running_sandbox_exits_with_the_conflict_code(self):
        self.systemd["is_active"].return_value = "active"
        code, _ = self.run_cli("delete", "alpha", "--yes")
        self.assertEqual(code, 4)


class SshCommandTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.create("alpha")
        state.atomic_write_text(self.config.control_key_path, "PRIVATE\n")

    def run_ssh(self, *arguments):
        with mock.patch("sandcastle.ssh.exec_ssh", return_value=0) as executed:
            code, output = self.run_cli("ssh", *arguments)
        return code, output, executed

    def test_ssh_targets_the_sandbox_vsock_destination_as_dev(self):
        code, _, executed = self.run_ssh("alpha")

        self.assertEqual(code, 0)
        command = executed.call_args.args[0]
        cid = self.store.load("alpha").vsock_cid
        self.assertEqual(command[-1], f"vsock/{cid}")
        self.assertIn("User=dev", command)

    def test_a_trailing_command_runs_in_the_guest(self):
        _, _, executed = self.run_ssh("alpha", "uname", "-a")
        self.assertEqual(executed.call_args.args[0][-2:], ["uname", "-a"])

    def test_options_after_a_double_dash_go_to_ssh(self):
        _, _, executed = self.run_ssh("alpha", "--", "-A")
        command = executed.call_args.args[0]
        self.assertLess(command.index("-A"), len(command) - 1)
        self.assertTrue(command[-1].startswith("vsock/"))

    def test_an_option_placed_after_the_name_is_explained_rather_than_sent(self):
        code, _, executed = self.run_ssh("alpha", "-L", "8080:localhost:8080")
        self.assertEqual(code, 2)
        executed.assert_not_called()

    def test_agent_forwarding_is_only_offered_when_an_agent_exists(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            code, _, executed = self.run_ssh("-A", "alpha")
        self.assertEqual(code, 8)
        executed.assert_not_called()


class ConfigResolutionTests(CliTestCase):
    def test_command_line_overrides_beat_the_host_config(self):
        parser = cli.build_parser()
        arguments = parser.parse_args(
            ["--config", self.config_path, "--state-dir", "/srv/other", "--flake", "/nix/store/x", "list"]
        )
        resolved = cli.resolve_config(arguments)
        self.assertEqual(resolved.state_dir, "/srv/other")
        self.assertEqual(resolved.flake_ref, "/nix/store/x")

    def test_an_explicit_missing_config_is_an_error(self):
        code, _ = self.run_cli("list")
        self.assertEqual(code, 0)

        out = io.StringIO()
        code = cli.main(["--config", os.path.join(self.root, "absent.json"), "list"], out=out)
        self.assertEqual(code, 7)

    def test_unknown_config_keys_are_rejected(self):
        path = os.path.join(self.root, "bad.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"stateDir": self.state_dir, "surprise": True}, handle)

        out = io.StringIO()
        self.assertEqual(cli.main(["--config", path, "list"], out=out), 7)


if __name__ == "__main__":
    unittest.main()
