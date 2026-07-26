import dataclasses
import os
import shutil
import tempfile
import unittest
from unittest import mock

from sandcastle import config as config_module
from sandcastle import spec as spec_module
from sandcastle import ssh
from sandcastle import state
from sandcastle.errors import LifecycleError, StateError

PROXY = "/nix/store/aaa-systemd/lib/systemd/systemd-ssh-proxy"


def make_spec(name="my-app", vsock_cid=100):
    return spec_module.Spec(
        name=name,
        ipv4="10.88.0.16",
        mac="02:00:aa:bb:cc:dd",
        vsock_cid=vsock_cid,
        machine_id="9f2c" * 8,
    )


class SshTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="sandcastle-test-")
        self.addCleanup(directory.cleanup)
        self.config = dataclasses.replace(
            config_module.Config(),
            state_dir=os.path.join(directory.name, "state"),
            ssh_proxy=PROXY,
        )
        state.ensure_directories(self.config)

    def write_control_key(self):
        state.atomic_write_text(self.config.control_key_path, "PRIVATE\n")
        state.atomic_write_text(ssh.public_key_path(self.config), "ssh-ed25519 AAAA test\n")

    def options(self, command):
        """Return the `-o key=value` settings as a mapping."""
        settings = {}
        for index, token in enumerate(command):
            if token == "-o":
                key, _, value = command[index + 1].partition("=")
                settings[key] = value
        return settings


class ControlKeyTests(SshTestCase):
    def test_an_existing_pair_is_reused_without_calling_ssh_keygen(self):
        self.write_control_key()
        with mock.patch("sandcastle.ssh.subprocess.run") as run:
            self.assertEqual(ssh.ensure_control_key(self.config), "ssh-ed25519 AAAA test")
        run.assert_not_called()

    @unittest.skipIf(shutil.which("ssh-keygen") is None, "ssh-keygen is not installed")
    def test_a_real_pair_is_generated_once_and_is_not_group_readable(self):
        first = ssh.ensure_control_key(self.config)
        self.assertTrue(first.startswith("ssh-ed25519 "))
        self.assertEqual(os.stat(self.config.control_key_path).st_mode & 0o777, 0o600)

        # A second call must not rotate the key: every guest closure has the
        # first one baked in.
        self.assertEqual(ssh.ensure_control_key(self.config), first)

    def test_a_half_written_pair_is_replaced_rather_than_refused(self):
        os.makedirs(self.config.ssh_dir, mode=0o700, exist_ok=True)
        state.atomic_write_text(self.config.control_key_path, "leftover\n")

        def fake_run(command, **_kwargs):
            # ssh-keygen refuses to overwrite, so the leftover must be gone.
            self.assertFalse(os.path.exists(self.config.control_key_path))
            state.atomic_write_text(self.config.control_key_path, "PRIVATE\n")
            state.atomic_write_text(ssh.public_key_path(self.config), "ssh-ed25519 BBBB new\n")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("sandcastle.ssh.shutil.which", return_value="/usr/bin/ssh-keygen"):
            with mock.patch("sandcastle.ssh.subprocess.run", side_effect=fake_run):
                self.assertEqual(ssh.ensure_control_key(self.config), "ssh-ed25519 BBBB new")

    def test_a_multi_line_public_key_file_is_rejected(self):
        state.atomic_write_text(self.config.control_key_path, "PRIVATE\n")
        state.atomic_write_text(ssh.public_key_path(self.config), "one\ntwo\n")
        with self.assertRaises(StateError):
            ssh.read_public_key(self.config)


class KnownHostsTests(SshTestCase):
    def test_a_per_sandbox_file_is_created_and_forgotten(self):
        path = ssh.ensure_known_hosts(self.config, "my-app")
        self.assertEqual(path, self.config.known_hosts_path("my-app"))
        self.assertTrue(os.path.exists(path))

        self.assertTrue(ssh.forget_known_hosts(self.config, "my-app"))
        self.assertFalse(os.path.exists(path))
        self.assertFalse(ssh.forget_known_hosts(self.config, "my-app"))

    def test_existing_pins_are_never_truncated(self):
        path = ssh.ensure_known_hosts(self.config, "my-app")
        state.atomic_write_text(path, "vsock/100 ssh-ed25519 AAAA\n")
        ssh.ensure_known_hosts(self.config, "my-app")
        with open(path, encoding="utf-8") as handle:
            self.assertIn("ssh-ed25519", handle.read())

    def test_names_are_validated_before_touching_the_filesystem(self):
        with self.assertRaises(Exception):
            ssh.ensure_known_hosts(self.config, "../escape")


class SshCommandTests(SshTestCase):
    def setUp(self):
        super().setUp()
        self.write_control_key()

    def test_the_destination_is_the_sandbox_vsock_cid(self):
        command = ssh.ssh_command(self.config, make_spec(vsock_cid=137))
        self.assertEqual(command[-1], "vsock/137")

    def test_host_key_checking_overrides_the_system_vsock_defaults(self):
        # /etc/ssh/ssh_config disables host-key checking for vsock/* targets,
        # so these have to be on the command line where ssh sees them first.
        settings = self.options(ssh.ssh_command(self.config, make_spec()))
        self.assertEqual(settings["StrictHostKeyChecking"], "accept-new")
        self.assertEqual(settings["UserKnownHostsFile"], self.config.known_hosts_path("my-app"))

    def test_the_session_logs_in_as_dev_with_only_the_control_key(self):
        settings = self.options(ssh.ssh_command(self.config, make_spec()))
        self.assertEqual(settings["User"], "dev")
        self.assertEqual(settings["IdentityFile"], self.config.control_key_path)
        self.assertEqual(settings["IdentitiesOnly"], "yes")
        self.assertEqual(settings["PasswordAuthentication"], "no")

    def test_the_configured_proxy_turns_the_destination_into_a_vsock_connection(self):
        settings = self.options(ssh.ssh_command(self.config, make_spec()))
        self.assertEqual(settings["ProxyCommand"], f"{PROXY} %h %p")
        self.assertEqual(settings["ProxyUseFdpass"], "yes")

    def test_without_a_configured_proxy_the_system_ssh_config_is_relied_on(self):
        resolved = dataclasses.replace(self.config, ssh_proxy="")
        settings = self.options(ssh.ssh_command(resolved, make_spec()))
        self.assertNotIn("ProxyCommand", settings)

    def test_the_agent_stays_out_of_the_guest_unless_it_is_asked_for(self):
        settings = self.options(ssh.ssh_command(self.config, make_spec()))
        self.assertEqual(settings["IdentityAgent"], "none")
        self.assertEqual(settings["ForwardAgent"], "no")

    def test_agent_forwarding_is_opt_in_and_needs_an_agent(self):
        with mock.patch.dict(os.environ, {"SSH_AUTH_SOCK": "/run/agent.sock"}):
            command = ssh.ssh_command(self.config, make_spec(), agent_forwarding=True)
        self.assertIn("-A", command)
        self.assertNotIn("IdentityAgent", self.options(command))

        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LifecycleError):
                ssh.ssh_command(self.config, make_spec(), agent_forwarding=True)

    def test_pass_through_options_precede_the_destination(self):
        command = ssh.ssh_command(
            self.config,
            make_spec(),
            ssh_options=["-L", "8080:localhost:8080"],
            remote_command=["tmux", "attach"],
        )
        self.assertEqual(command[-3:], ["vsock/100", "tmux", "attach"])
        self.assertLess(command.index("-L"), command.index("vsock/100"))

    def test_a_missing_control_key_is_an_error_rather_than_a_password_prompt(self):
        os.unlink(self.config.control_key_path)
        with self.assertRaises(StateError):
            ssh.ssh_command(self.config, make_spec())


if __name__ == "__main__":
    unittest.main()
