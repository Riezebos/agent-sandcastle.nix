import dataclasses
import os
import tempfile
import unittest
from unittest import mock

from sandcastle import build
from sandcastle import config as config_module
from sandcastle import spec as spec_module
from sandcastle import ssh as ssh_module
from sandcastle import state
from sandcastle.errors import BuildError, StateError

CONTROL_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAtest sandcastle-control"

SPEC_STORE_PATH = "/nix/store/00000000000000000000000000000000-sandbox-spec.json"
RUNNER_PATH = "/nix/store/11111111111111111111111111111111-microvm-run"
OTHER_RUNNER_PATH = "/nix/store/22222222222222222222222222222222-microvm-run"


def make_spec(name="my-app", **overrides):
    values = {
        "name": name,
        "ipv4": "10.88.0.16",
        "mac": "02:00:aa:bb:cc:dd",
        "vsock_cid": 100,
        "machine_id": "9f2c" * 8,
    }
    values.update(overrides)
    return spec_module.Spec(**values)


class TemporaryStateTestCase(unittest.TestCase):
    """Base case with a throwaway state tree and a stubbed control key."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="sandcastle-test-")
        self.addCleanup(directory.cleanup)
        self.root = directory.name
        self.config = dataclasses.replace(
            config_module.Config(),
            state_dir=os.path.join(self.root, "state"),
            gc_root_dir=os.path.join(self.root, "gcroots"),
        )
        state.ensure_directories(self.config)

        # Nothing here should shell out to ssh-keygen.
        patcher = mock.patch.object(ssh_module, "ensure_control_key", return_value=CONTROL_KEY)
        patcher.start()
        self.addCleanup(patcher.stop)


class BuildInputTests(TemporaryStateTestCase):
    def test_network_parameters_come_from_the_host_config_not_the_spec(self):
        resolved = dataclasses.replace(
            self.config, subnet="10.88.0.0/24", host_address="10.88.0.1", nameservers=["10.88.0.1"]
        )
        document = build.build_input(resolved, make_spec())

        self.assertNotIn("network", make_spec().to_dict())
        self.assertEqual(
            document["network"],
            {"gateway": "10.88.0.1", "prefixLength": 24, "nameservers": ["10.88.0.1"]},
        )
        self.assertEqual(document["name"], "my-app")

    def test_prefix_length_follows_the_configured_subnet(self):
        resolved = dataclasses.replace(
            self.config, subnet="10.88.0.0/22", host_address="10.88.0.1"
        )
        self.assertEqual(build.build_input(resolved, make_spec())["network"]["prefixLength"], 22)

    def test_the_control_key_is_a_build_input_not_a_spec_field(self):
        document = build.build_input(self.config, make_spec())

        self.assertEqual(document["authorizedKeys"], [CONTROL_KEY])
        self.assertNotIn("authorizedKeys", make_spec().to_dict())


class BuildRunnerTests(TemporaryStateTestCase):
    def setUp(self):
        super().setUp()
        self.config = dataclasses.replace(self.config, flake_ref="/nix/store/aaa-source")

    def test_a_missing_flake_reference_is_refused_before_any_subprocess(self):
        with mock.patch("sandcastle.build._run") as run:
            with self.assertRaises(StateError):
                build.build_runner(dataclasses.replace(self.config, flake_ref=""), make_spec())
        run.assert_not_called()

    def test_the_expression_only_references_store_paths(self):
        captured = []

        def fake_run(command, what):
            captured.append(command)
            if command[0].endswith("nix-store"):
                return SPEC_STORE_PATH + "\n"
            return RUNNER_PATH + "\n"

        with mock.patch("sandcastle.build._run", side_effect=fake_run):
            result = build.build_runner(self.config, make_spec(packages=["nodejs"]))

        self.assertEqual(result, RUNNER_PATH)
        expression = captured[-1][captured[-1].index("--expr") + 1]
        self.assertIn(SPEC_STORE_PATH, expression)
        self.assertIn("/nix/store/aaa-source", expression)
        self.assertNotIn("nodejs", expression)

    def test_a_non_store_build_result_is_rejected(self):
        def fake_run(command, what):
            if command[0].endswith("nix-store"):
                return SPEC_STORE_PATH + "\n"
            return "/tmp/not-a-store-path\n"

        with mock.patch("sandcastle.build._run", side_effect=fake_run):
            with self.assertRaises(Exception):
                build.build_runner(self.config, make_spec())

    def test_nix_failures_surface_as_build_errors(self):
        with mock.patch("sandcastle.build._run", side_effect=BuildError("nix said no")):
            with self.assertRaises(BuildError):
                build.build_runner(self.config, make_spec())

    def test_flake_references_are_escaped_for_the_nix_string(self):
        self.assertEqual(build._escape_nix_string('a"b'), 'a\\"b')
        self.assertEqual(build._escape_nix_string("a${b}"), "a\\${b}")
        self.assertEqual(build._escape_nix_string("a\\b"), "a\\\\b")


class InstallRunnerTests(TemporaryStateTestCase):
    def test_the_vm_directory_stays_writable_by_the_microvm_user(self):
        # microvm-set-booted@.service runs unprivileged in this directory and
        # writes the `booted` symlink there, so root's umask must not win.
        build.install_runner(self.config, "my-app", RUNNER_PATH)
        mode = os.stat(self.config.vm_dir("my-app")).st_mode & 0o777
        self.assertEqual(mode, state.VM_DIRECTORY_MODE)

    def test_installing_points_current_and_the_gc_root_at_the_runner(self):
        previous = build.install_runner(self.config, "my-app", RUNNER_PATH)

        self.assertIsNone(previous)
        self.assertEqual(state.installed_runner(self.config, "my-app"), RUNNER_PATH)
        self.assertEqual(state.read_gc_root(self.config, "my-app", "current"), RUNNER_PATH)

    def test_the_replaced_runner_is_retained_for_rollback(self):
        build.install_runner(self.config, "my-app", RUNNER_PATH)
        previous = build.install_runner(self.config, "my-app", OTHER_RUNNER_PATH)

        self.assertEqual(previous, RUNNER_PATH)
        self.assertEqual(state.read_gc_root(self.config, "my-app", "previous"), RUNNER_PATH)
        self.assertEqual(state.installed_runner(self.config, "my-app"), OTHER_RUNNER_PATH)

    def test_rollback_restores_the_previous_runner(self):
        build.install_runner(self.config, "my-app", RUNNER_PATH)
        build.install_runner(self.config, "my-app", OTHER_RUNNER_PATH)

        restored = build.rollback_runner(self.config, "my-app")

        self.assertEqual(restored, RUNNER_PATH)
        self.assertEqual(state.installed_runner(self.config, "my-app"), RUNNER_PATH)

    def test_rollback_without_a_previous_runner_reports_nothing_to_do(self):
        build.install_runner(self.config, "my-app", RUNNER_PATH)
        self.assertIsNone(build.rollback_runner(self.config, "my-app"))

    def test_reinstalling_the_same_runner_does_not_overwrite_the_rollback_target(self):
        build.install_runner(self.config, "my-app", RUNNER_PATH)
        build.install_runner(self.config, "my-app", OTHER_RUNNER_PATH)
        build.install_runner(self.config, "my-app", OTHER_RUNNER_PATH)

        self.assertEqual(state.read_gc_root(self.config, "my-app", "previous"), RUNNER_PATH)

    def test_names_and_paths_are_validated(self):
        with self.assertRaises(Exception):
            build.install_runner(self.config, "../escape", RUNNER_PATH)
        with self.assertRaises(Exception):
            build.install_runner(self.config, "my-app", "/tmp/runner")


if __name__ == "__main__":
    unittest.main()
