import dataclasses
import os
import tempfile
import unittest
from unittest import mock

from sandcastle import build
from sandcastle import config as config_module
from sandcastle import lifecycle
from sandcastle import ssh as ssh_module
from sandcastle import state
from sandcastle import systemd
from sandcastle.errors import BuildError, ConflictError, LifecycleError, StateError

RUNNER = "/nix/store/11111111111111111111111111111111-microvm-run"
NEW_RUNNER = "/nix/store/22222222222222222222222222222222-microvm-run"
CONTROL_KEY = "ssh-ed25519 AAAAtest sandcastle-control"


class LifecycleTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="sandcastle-test-")
        self.addCleanup(directory.cleanup)
        self.root = directory.name
        self.config = dataclasses.replace(
            config_module.Config(),
            state_dir=os.path.join(self.root, "state"),
            gc_root_dir=os.path.join(self.root, "gcroots"),
            flake_ref="/nix/store/aaa-source",
        )
        state.ensure_directories(self.config)
        self.store = state.Store(self.config)
        self.messages = []

        for target, value in (
            ("sandcastle.ssh.ensure_control_key", CONTROL_KEY),
            ("sandcastle.build.build_runner", RUNNER),
        ):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

        # Every test states its own systemd expectations; nothing reaches the
        # real systemctl.
        self.systemd = self.patch_systemd()

    def patch_systemd(self, states=None):
        stubs = {}
        for name, value in (
            ("active_states", states or {}),
            ("is_active", "inactive"),
            ("properties", {"ActiveState": "inactive", "SubState": "dead"}),
            ("confirm_running", {}),
            ("start", None),
            ("stop", None),
            ("restart", None),
        ):
            patcher = mock.patch.object(systemd, name, return_value=value)
            stubs[name] = patcher.start()
            self.addCleanup(patcher.stop)
        return stubs

    def report(self, message):
        self.messages.append(message)

    def create(self, name="my-app", **kwargs):
        kwargs.setdefault("report", self.report)
        return lifecycle.create(self.config, self.store, name, **kwargs)

    def output(self):
        return "\n".join(self.messages)


class CreateTests(LifecycleTestCase):
    def test_create_allocates_builds_installs_and_leaves_the_vm_stopped(self):
        spec = self.create("my-app", packages=["nodejs"])

        self.assertEqual(spec.ipv4, self.config.allocation_start)
        self.assertEqual(spec.packages, ["nodejs"])
        self.assertEqual(self.store.load("my-app").machine_id, spec.machine_id)
        self.assertEqual(state.installed_runner(self.config, "my-app"), RUNNER)
        self.assertEqual(state.read_gc_root(self.config, "my-app", "current"), RUNNER)
        self.assertTrue(os.path.isdir(self.config.credentials_path("my-app")))
        self.assertTrue(os.path.exists(self.config.known_hosts_path("my-app")))
        self.systemd["start"].assert_not_called()

    def test_profiles_expand_into_package_attributes(self):
        spec = self.create("my-app", packages=["python", "ripgrep"])
        self.assertEqual(spec.packages, ["python3", "ripgrep", "uv"])

    def test_resource_overrides_are_validated(self):
        spec = self.create("my-app", vcpu=4, memory_mib=4096, home_disk_mib=8192)
        self.assertEqual((spec.vcpu, spec.memory_mib, spec.home_disk_mib), (4, 4096, 8192))

        with self.assertRaises(Exception):
            self.create("other", vcpu=0)

    def test_an_empty_agent_list_is_distinct_from_the_default(self):
        self.assertEqual(self.create("with-agents").agents, ["claude-code", "codex"])
        self.assertEqual(self.create("without", agents=[]).agents, [])

    def test_a_duplicate_name_is_refused_before_any_build(self):
        self.create("my-app")
        with self.assertRaises(ConflictError):
            self.create("my-app")

    def test_a_failed_build_leaves_nothing_addressable_behind(self):
        with mock.patch("sandcastle.build.build_runner", side_effect=BuildError("nope")):
            with self.assertRaises(BuildError):
                self.create("my-app")

        self.assertEqual(self.store.names(), [])
        self.assertFalse(os.path.exists(self.config.vm_dir("my-app")))
        self.assertFalse(os.path.exists(self.config.credentials_path("my-app")))
        self.assertIsNone(state.read_gc_root(self.config, "my-app", "current"))

        # The address the failed create reserved is free again.
        self.assertEqual(self.create("my-app").ipv4, self.config.allocation_start)

    def test_an_unwind_keeps_credentials_a_previous_delete_deliberately_kept(self):
        credentials = self.config.credentials_path("my-app")
        os.makedirs(credentials, mode=0o700)
        state.atomic_write_text(os.path.join(credentials, "token"), "secret\n")

        with mock.patch("sandcastle.build.build_runner", side_effect=BuildError("nope")):
            with self.assertRaises(BuildError):
                self.create("my-app")

        self.assertTrue(os.path.exists(os.path.join(credentials, "token")))

    def test_a_create_that_would_not_fit_on_disk_is_refused(self):
        with mock.patch("sandcastle.state.free_space_mib", return_value=100):
            with self.assertRaises(StateError):
                self.create("my-app")
        self.assertEqual(self.store.names(), [])

    def test_an_unknown_parent_is_refused(self):
        with self.assertRaises(StateError):
            self.create("child", parent="absent")


class StartStopTests(LifecycleTestCase):
    def setUp(self):
        super().setUp()
        self.create("my-app")

    def test_start_refuses_a_sandbox_with_no_installed_runner(self):
        state.remove_vm_dir(self.config, "my-app")
        with self.assertRaises(StateError):
            lifecycle.start(self.config, self.store, "my-app", report=self.report)

    def test_start_confirms_the_sandbox_stayed_up(self):
        lifecycle.start(self.config, self.store, "my-app", report=self.report)
        self.systemd["start"].assert_called_once_with("my-app")
        self.systemd["confirm_running"].assert_called_once()

    def test_no_wait_skips_the_readiness_check(self):
        lifecycle.start(self.config, self.store, "my-app", wait=False, report=self.report)
        self.systemd["confirm_running"].assert_not_called()

    def test_starting_an_already_running_sandbox_is_a_no_op(self):
        self.systemd["active_states"].return_value = {"my-app": "active"}
        lifecycle.start(self.config, self.store, "my-app", report=self.report)
        self.systemd["start"].assert_not_called()
        self.assertIn("already running", self.output())

    def test_the_host_concurrency_limit_is_enforced_before_starting(self):
        resolved = dataclasses.replace(self.config, max_running=1)
        self.create("other")
        self.systemd["active_states"].return_value = {"other": "active", "my-app": "inactive"}

        with self.assertRaises(ConflictError) as raised:
            lifecycle.start(resolved, self.store, "my-app", report=self.report)
        self.assertIn("other", str(raised.exception))
        self.systemd["start"].assert_not_called()

    def test_stop_and_restart_delegate_to_the_generic_units(self):
        lifecycle.stop(self.config, self.store, "my-app", report=self.report)
        self.systemd["stop"].assert_called_once_with("my-app")

        lifecycle.restart(self.config, self.store, "my-app", report=self.report)
        self.systemd["restart"].assert_called_once_with("my-app")


class RebuildTests(LifecycleTestCase):
    def setUp(self):
        super().setUp()
        self.create("my-app")

    def rebuild(self, **kwargs):
        kwargs.setdefault("report", self.report)
        return lifecycle.rebuild(self.config, self.store, "my-app", **kwargs)

    def test_an_unchanged_runner_is_reported_without_moving_anything(self):
        runner, changed = self.rebuild()
        self.assertEqual((runner, changed), (RUNNER, False))
        self.systemd["restart"].assert_not_called()

    def test_a_stopped_sandbox_gets_the_new_runner_but_stays_stopped(self):
        with mock.patch("sandcastle.build.build_runner", return_value=NEW_RUNNER):
            runner, changed = self.rebuild()

        self.assertEqual((runner, changed), (NEW_RUNNER, True))
        self.assertEqual(state.installed_runner(self.config, "my-app"), NEW_RUNNER)
        self.systemd["restart"].assert_not_called()

    def test_a_running_sandbox_comes_back_on_the_new_runner(self):
        self.systemd["is_active"].return_value = "active"
        with mock.patch("sandcastle.build.build_runner", return_value=NEW_RUNNER):
            self.rebuild()

        self.systemd["restart"].assert_called_once_with("my-app")
        self.assertEqual(state.installed_runner(self.config, "my-app"), NEW_RUNNER)
        self.assertEqual(state.read_gc_root(self.config, "my-app", "previous"), RUNNER)

    def test_no_restart_leaves_a_running_guest_on_its_old_closure(self):
        self.systemd["is_active"].return_value = "active"
        with mock.patch("sandcastle.build.build_runner", return_value=NEW_RUNNER):
            self.rebuild(restart_guest=False)

        self.systemd["restart"].assert_not_called()
        self.assertIn("until it is restarted", self.output())

    def test_a_failed_build_never_touches_the_installed_runner(self):
        with mock.patch("sandcastle.build.build_runner", side_effect=BuildError("bad package")):
            with self.assertRaises(BuildError):
                self.rebuild()

        self.assertEqual(state.installed_runner(self.config, "my-app"), RUNNER)
        self.systemd["restart"].assert_not_called()

    def test_a_failed_activation_rolls_current_back_and_restarts_the_old_runner(self):
        self.systemd["is_active"].return_value = "active"
        self.systemd["confirm_running"].side_effect = [LifecycleError("guest never booted"), {}]

        with mock.patch("sandcastle.build.build_runner", return_value=NEW_RUNNER):
            with self.assertRaises(LifecycleError) as raised:
                self.rebuild()

        self.assertIn("Rolled back", str(raised.exception))
        self.assertEqual(state.installed_runner(self.config, "my-app"), RUNNER)
        self.assertEqual(self.systemd["restart"].call_count, 2)

    def test_a_rollback_that_also_fails_says_the_sandbox_is_down(self):
        self.systemd["is_active"].return_value = "active"
        self.systemd["confirm_running"].side_effect = LifecycleError("guest never booted")

        with mock.patch("sandcastle.build.build_runner", return_value=NEW_RUNNER):
            with self.assertRaises(LifecycleError) as raised:
                self.rebuild()

        self.assertIn("failed to come back", str(raised.exception))

    def test_with_no_previous_runner_a_failed_activation_says_so(self):
        # Nix garbage collection cannot take the retained runner, but an
        # operator can, so the branch has to report rather than crash.
        self.systemd["is_active"].return_value = "active"
        self.systemd["confirm_running"].side_effect = LifecycleError("guest never booted")

        with mock.patch("sandcastle.build.build_runner", return_value=NEW_RUNNER):
            with mock.patch("sandcastle.build.rollback_runner", return_value=None):
                with self.assertRaises(LifecycleError) as raised:
                    self.rebuild()

        self.assertIn("no previous runner", str(raised.exception))


class DeleteTests(LifecycleTestCase):
    def setUp(self):
        super().setUp()
        self.create("my-app")
        self.credential = os.path.join(self.config.credentials_path("my-app"), "token")
        state.atomic_write_text(self.credential, "secret\n")

    def delete(self, **kwargs):
        kwargs.setdefault("report", self.report)
        return lifecycle.delete(self.config, self.store, "my-app", **kwargs)

    def test_a_running_sandbox_is_never_deleted(self):
        self.systemd["is_active"].return_value = "active"
        with self.assertRaises(ConflictError):
            self.delete()
        self.assertEqual(self.store.names(), ["my-app"])

    def test_delete_removes_the_disks_spec_roots_and_host_key_pin(self):
        self.delete()

        self.assertEqual(self.store.names(), [])
        self.assertFalse(os.path.exists(self.config.vm_dir("my-app")))
        self.assertIsNone(state.read_gc_root(self.config, "my-app", "current"))
        self.assertFalse(os.path.exists(self.config.known_hosts_path("my-app")))

    def test_credentials_survive_unless_they_are_explicitly_deleted(self):
        self.delete()
        self.assertTrue(os.path.exists(self.credential))
        self.assertIn("kept credentials", self.output())

    def test_delete_credentials_removes_them_and_says_so(self):
        removed = self.delete(delete_credentials=True)
        self.assertFalse(os.path.exists(self.credential))
        self.assertIn(self.config.credentials_path("my-app"), removed)

    def test_a_sandbox_with_web_routes_is_not_deleted_silently(self):
        state.atomic_write_text(
            os.path.join(self.config.caddy_dir, "my-app.example.com.caddy"),
            "# sandcastle-sandbox: my-app\nreverse_proxy 10.88.0.16:3000\n",
        )
        with self.assertRaises(ConflictError) as raised:
            self.delete()
        self.assertIn("my-app.example.com.caddy", str(raised.exception))

    def test_another_sandbox_route_does_not_block_the_delete(self):
        state.atomic_write_text(
            os.path.join(self.config.caddy_dir, "other.example.com.caddy"),
            "# sandcastle-sandbox: other\nreverse_proxy 10.88.0.17:3000\n",
        )
        self.delete()
        self.assertEqual(self.store.names(), [])

    def test_the_freed_address_and_cid_are_reused_by_the_next_create(self):
        first = self.store.load("my-app")
        self.delete()
        second = self.create("replacement")
        self.assertEqual(second.ipv4, first.ipv4)
        self.assertEqual(second.vsock_cid, first.vsock_cid)


class StatusTests(LifecycleTestCase):
    def setUp(self):
        super().setUp()
        self.create("my-app")

    def test_status_reads_state_without_evaluating_nix(self):
        self.systemd["properties"].return_value = {
            "ActiveState": "active",
            "SubState": "running",
            "Result": "success",
            "ExecMainStartTimestamp": "Sun 2026-07-26 10:00:00 UTC",
        }
        with mock.patch("sandcastle.build.build_runner") as builder:
            document = lifecycle.status(self.config, self.store, "my-app")
        builder.assert_not_called()

        self.assertEqual(document["state"], "active")
        self.assertEqual(document["unit"], "microvm@my-app.service")
        self.assertEqual(document["runner"], RUNNER)
        self.assertEqual(document["sshDestination"], "vsock/100")
        self.assertEqual(document["tapDevice"], state.tap_name("my-app"))
        self.assertFalse(document["stale"])

    def test_a_guest_running_an_older_runner_is_reported_as_stale(self):
        state.atomic_symlink(os.path.join(self.config.vm_dir("my-app"), "booted"), NEW_RUNNER)
        self.assertTrue(lifecycle.status(self.config, self.store, "my-app")["stale"])


class RemovalGuardTests(LifecycleTestCase):
    def test_a_vm_directory_that_escapes_the_state_tree_is_refused(self):
        os.makedirs(os.path.join(self.root, "elsewhere"))
        os.symlink(os.path.join(self.root, "elsewhere"), self.config.vm_dir("my-app"))
        with self.assertRaises(StateError):
            state.remove_vm_dir(self.config, "my-app")
        self.assertTrue(os.path.isdir(os.path.join(self.root, "elsewhere")))

    def test_credentials_outside_the_credential_tree_are_refused(self):
        os.makedirs(os.path.join(self.root, "elsewhere"))
        os.symlink(os.path.join(self.root, "elsewhere"), self.config.credentials_path("my-app"))
        with self.assertRaises(StateError):
            state.remove_credentials(self.config, "my-app")

    def test_free_space_is_measured_on_the_nearest_existing_ancestor(self):
        self.assertGreater(
            state.free_space_mib(os.path.join(self.config.vms_dir, "not", "there")), 0
        )


class ControlKeyIntegrationTests(LifecycleTestCase):
    def test_create_bakes_the_control_key_into_the_build_input(self):
        # Undo the module-level stub so the real build_input path runs.
        with mock.patch("sandcastle.build.build_runner", side_effect=build.build_runner):
            with mock.patch("sandcastle.build._run") as run:
                run.side_effect = [
                    "/nix/store/33333333333333333333333333333333-sandbox-spec.json\n",
                    RUNNER + "\n",
                ]
                self.create("my-app")

        document = build.build_input(self.config, self.store.load("my-app"))
        self.assertEqual(document["authorizedKeys"], [CONTROL_KEY])
        self.assertEqual(ssh_module.ensure_control_key(self.config), CONTROL_KEY)


if __name__ == "__main__":
    unittest.main()
