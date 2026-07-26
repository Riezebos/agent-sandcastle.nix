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

RUNNER_PATH = "/nix/store/11111111111111111111111111111111-microvm-run"


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
                },
                handle,
            )

        self.config = config_module.load(self.config_path)
        state.ensure_directories(self.config)
        self.store = state.Store(self.config)

        # Nothing in these tests should reach systemd.
        patcher = mock.patch("sandcastle.systemd.is_active", return_value="inactive")
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
