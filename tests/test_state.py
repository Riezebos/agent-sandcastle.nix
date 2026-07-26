import dataclasses
import os
import tempfile
import unittest
from unittest import mock

from sandcastle import config as config_module
from sandcastle import spec as spec_module
from sandcastle import state
from sandcastle.errors import ConflictError, ExhaustedError, NotFoundError, StateError


class StateTestCase(unittest.TestCase):
    """Base case with a throwaway state tree."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="sandcastle-test-")
        self.addCleanup(self.directory.cleanup)
        self.config = dataclasses.replace(
            config_module.Config(),
            state_dir=os.path.join(self.directory.name, "state"),
            gc_root_dir=os.path.join(self.directory.name, "gcroots"),
        )
        state.ensure_directories(self.config)
        self.store = state.Store(self.config)

    def allocate(self, name, **overrides):
        with state.allocation_lock(self.config):
            allocated = state.allocate(self.config, self.store, name)
            if overrides:
                allocated = dataclasses.replace(allocated, **overrides)
            self.store.save(allocated)
        return allocated


class PathTests(StateTestCase):
    def test_paths_all_derive_from_the_state_root(self):
        root = self.config.state_dir
        self.assertEqual(self.config.specs_dir, os.path.join(root, "specs"))
        self.assertEqual(self.config.spec_path("my-app"), os.path.join(root, "specs/my-app.json"))
        self.assertEqual(self.config.vm_dir("my-app"), os.path.join(root, "vms/my-app"))
        self.assertEqual(
            self.config.home_image_path("my-app"), os.path.join(root, "vms/my-app/home.img")
        )

    def test_relocating_the_state_root_moves_every_directory(self):
        moved = dataclasses.replace(self.config, state_dir="/srv/sandcastle")
        for path in (
            moved.specs_dir,
            moved.vms_dir,
            moved.credentials_dir,
            moved.caddy_dir,
            moved.locks_dir,
            moved.known_hosts_dir,
        ):
            self.assertTrue(path.startswith("/srv/sandcastle/"), path)

    def test_a_traversing_name_cannot_reach_outside_the_specs_directory(self):
        with self.assertRaises(Exception):
            self.store.load("../../etc/passwd")

    def test_ensure_directories_is_idempotent(self):
        state.ensure_directories(self.config)
        state.ensure_directories(self.config)
        self.assertTrue(os.path.isdir(self.config.locks_dir))


class AtomicWriteTests(StateTestCase):
    def test_write_replaces_content_atomically(self):
        path = os.path.join(self.directory.name, "value")
        state.atomic_write_text(path, "first\n")
        state.atomic_write_text(path, "second\n")
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "second\n")

    def test_a_failed_write_leaves_the_old_content_and_no_temporary_file(self):
        path = os.path.join(self.directory.name, "value")
        state.atomic_write_text(path, "original\n")

        with mock.patch("sandcastle.state.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                state.atomic_write_text(path, "replacement\n")

        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "original\n")
        leftovers = [entry for entry in os.listdir(self.directory.name) if entry.startswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_symlink_swap_is_atomic_and_cleans_up_on_failure(self):
        link = os.path.join(self.directory.name, "current")
        state.atomic_symlink(link, "/nix/store/first")
        state.atomic_symlink(link, "/nix/store/second")
        self.assertEqual(os.readlink(link), "/nix/store/second")

        with mock.patch("sandcastle.state.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                state.atomic_symlink(link, "/nix/store/third")

        self.assertEqual(os.readlink(link), "/nix/store/second")
        leftovers = [entry for entry in os.listdir(self.directory.name) if entry.startswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_spec_files_are_not_world_readable(self):
        allocated = self.allocate("my-app")
        mode = os.stat(self.config.spec_path(allocated.name)).st_mode & 0o777
        self.assertEqual(mode, state.SPEC_MODE)


class LockTests(StateTestCase):
    def test_a_held_lock_blocks_a_non_blocking_acquirer(self):
        with state.file_lock(self.config, "my-app"):
            forked = os.fork()
            if forked == 0:  # pragma: no cover - child process
                code = 0
                try:
                    with state.file_lock(self.config, "my-app", blocking=False):
                        code = 1
                except ConflictError:
                    code = 0
                os._exit(code)
            _, status = os.waitpid(forked, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)

    def test_the_same_process_can_reacquire_after_release(self):
        with state.file_lock(self.config, "my-app", blocking=False):
            pass
        with state.file_lock(self.config, "my-app", blocking=False):
            pass

    def test_lock_names_are_validated(self):
        with self.assertRaises(Exception):
            with state.file_lock(self.config, "../escape"):
                pass


class AllocationTests(StateTestCase):
    def test_allocation_assigns_distinct_identities(self):
        first = self.allocate("first")
        second = self.allocate("second")

        self.assertNotEqual(first.ipv4, second.ipv4)
        self.assertNotEqual(first.vsock_cid, second.vsock_cid)
        self.assertNotEqual(first.mac, second.mac)
        self.assertNotEqual(first.machine_id, second.machine_id)

    def test_allocation_starts_at_the_configured_bounds(self):
        first = self.allocate("first")
        self.assertEqual(first.ipv4, self.config.allocation_start)
        self.assertEqual(first.vsock_cid, self.config.vsock_cid_start)

    def test_a_duplicate_name_is_a_conflict(self):
        self.allocate("my-app")
        with self.assertRaises(ConflictError):
            self.allocate("my-app")

    def test_gaps_left_by_deletion_are_reused(self):
        first = self.allocate("first")
        self.allocate("second")
        self.store.remove("first")
        third = self.allocate("third")
        self.assertEqual(third.ipv4, first.ipv4)
        self.assertEqual(third.vsock_cid, first.vsock_cid)

    def test_addresses_never_include_the_host_address(self):
        narrow = dataclasses.replace(
            self.config, allocation_start="10.88.0.1", allocation_end="10.88.0.2"
        )
        self.assertEqual(list(narrow.allocation_range()), ["10.88.0.2"])

    def test_an_exhausted_address_pool_is_reported(self):
        narrow = dataclasses.replace(
            self.config, allocation_start="10.88.0.16", allocation_end="10.88.0.16"
        )
        store = state.Store(narrow)
        with state.allocation_lock(narrow):
            store.save(state.allocate(narrow, store, "first"))
            with self.assertRaises(ExhaustedError):
                state.allocate(narrow, store, "second")

    def test_an_exhausted_cid_pool_is_reported(self):
        narrow = dataclasses.replace(self.config, vsock_cid_start=100, vsock_cid_end=100)
        store = state.Store(narrow)
        with state.allocation_lock(narrow):
            store.save(state.allocate(narrow, store, "first"))
            with self.assertRaises(ExhaustedError):
                state.allocate(narrow, store, "second")

    def test_a_colliding_mac_is_resalted_rather_than_reused(self):
        first = self.allocate("first")
        # Force the natural derivation for "second" to collide with "first".
        colliding = dataclasses.replace(first)
        with mock.patch(
            "sandcastle.state.derive_mac",
            side_effect=lambda name, salt=0: colliding.mac if salt == 0 else "02:00:00:00:00:99",
        ):
            second = self.allocate("second")
        self.assertNotEqual(second.mac, first.mac)

    def test_tap_names_match_the_guest_module_derivation(self):
        # Pins the cross-language agreement with nix/guest-module.nix; the
        # same value appears in the flake's example runner.
        self.assertEqual(state.tap_name("cli-example"), "sc-97908fc0042")
        self.assertLessEqual(len(state.tap_name("a" * 32)), 15)

    def test_derived_macs_are_stable_and_valid(self):
        self.assertEqual(state.derive_mac("my-app"), state.derive_mac("my-app"))
        self.assertNotEqual(state.derive_mac("my-app"), state.derive_mac("my-app", salt=1))
        self.assertTrue(state.derive_mac("my-app").startswith("02:"))

    def test_a_parent_is_recorded_for_forks(self):
        self.allocate("parent")
        with state.allocation_lock(self.config):
            child = state.allocate(self.config, self.store, "child", parent="parent")
        self.assertEqual(child.parent, "parent")


class StoreTests(StateTestCase):
    def test_missing_sandbox_reports_not_found(self):
        with self.assertRaises(NotFoundError):
            self.store.load("absent")
        with self.assertRaises(NotFoundError):
            self.store.remove("absent")

    def test_names_ignores_unrelated_files(self):
        self.allocate("my-app")
        open(os.path.join(self.config.specs_dir, "notes.txt"), "w", encoding="utf-8").close()
        open(os.path.join(self.config.specs_dir, ".hidden.json"), "w", encoding="utf-8").close()
        self.assertEqual(self.store.names(), ["my-app"])

    def test_a_renamed_spec_file_is_rejected(self):
        allocated = self.allocate("my-app")
        os.rename(
            self.config.spec_path(allocated.name),
            self.config.spec_path("other"),
        )
        with self.assertRaises(StateError):
            self.store.load("other")

    def test_a_corrupt_spec_is_an_error_rather_than_a_skipped_row(self):
        self.allocate("my-app")
        state.atomic_write_text(self.config.spec_path("my-app"), "{ not json")
        with self.assertRaises(StateError):
            self.store.load_all()


class GcRootTests(StateTestCase):
    STORE_PATH = "/nix/store/00000000000000000000000000000000-microvm-run"
    OTHER_PATH = "/nix/store/11111111111111111111111111111111-microvm-run"

    def test_roots_are_installed_read_and_removed(self):
        state.install_gc_root(self.config, "my-app", "current", self.STORE_PATH)
        self.assertEqual(state.read_gc_root(self.config, "my-app"), self.STORE_PATH)

        state.install_gc_root(self.config, "my-app", "current", self.OTHER_PATH)
        self.assertEqual(state.read_gc_root(self.config, "my-app"), self.OTHER_PATH)

        state.remove_gc_root(self.config, "my-app")
        self.assertIsNone(state.read_gc_root(self.config, "my-app"))

    def test_only_known_slots_are_accepted(self):
        with self.assertRaises(StateError):
            state.install_gc_root(self.config, "my-app", "scratch", self.STORE_PATH)

    def test_only_store_paths_are_accepted(self):
        with self.assertRaises(Exception):
            state.install_gc_root(self.config, "my-app", "current", "/tmp/runner")

    def test_reading_an_absent_root_returns_none(self):
        self.assertIsNone(state.read_gc_root(self.config, "absent"))
        self.assertIsNone(state.installed_runner(self.config, "absent"))
        self.assertIsNone(state.booted_runner(self.config, "absent"))


if __name__ == "__main__":
    unittest.main()
