import unittest
from unittest import mock

from sandcastle import systemd
from sandcastle.errors import LifecycleError


def completed(stdout="", returncode=0, stderr=""):
    return mock.Mock(stdout=stdout, stderr=stderr, returncode=returncode)


class UnitNameTests(unittest.TestCase):
    def test_units_are_built_from_a_validated_name(self):
        self.assertEqual(systemd.unit_name("my-app"), "microvm@my-app.service")
        with self.assertRaises(Exception):
            systemd.unit_name("my app")
        with self.assertRaises(Exception):
            systemd.unit_name("../escape")

    def test_the_companion_units_are_included_for_logs(self):
        units = systemd.unit_names("my-app")
        self.assertEqual(units[0], "microvm@my-app.service")
        self.assertIn("microvm-tap-interfaces@my-app.service", units)
        self.assertIn("microvm-virtiofsd@my-app.service", units)


class ActiveStateTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(systemd, "available", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_many_sandboxes_are_queried_in_one_call(self):
        with mock.patch.object(
            systemd, "_run", return_value=completed("active\ninactive\nfailed\n", returncode=3)
        ) as run:
            states = systemd.active_states(["a", "b", "c"])

        run.assert_called_once()
        self.assertEqual(states, {"a": "active", "b": "inactive", "c": "failed"})

    def test_a_short_reply_leaves_the_rest_unknown_rather_than_misaligned(self):
        with mock.patch.object(systemd, "_run", return_value=completed("active\n")):
            self.assertEqual(
                systemd.active_states(["a", "b"]), {"a": "active", "b": systemd.UNKNOWN}
            )

    def test_no_sandboxes_means_no_subprocess(self):
        with mock.patch.object(systemd, "_run") as run:
            self.assertEqual(systemd.active_states([]), {})
        run.assert_not_called()

    def test_running_names_picks_out_the_active_ones(self):
        with mock.patch.object(systemd, "_run", return_value=completed("active\ninactive\n")):
            self.assertEqual(systemd.running_names(["a", "b"]), {"a"})

    def test_a_host_without_systemd_reports_unknown_instead_of_failing(self):
        with mock.patch.object(systemd, "available", return_value=False):
            self.assertEqual(systemd.active_states(["a"]), {"a": systemd.UNKNOWN})


class ActionTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(systemd, "available", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_failed_verb_points_at_the_logs(self):
        with mock.patch.object(
            systemd, "_run", return_value=completed(returncode=1, stderr="Unit not found.")
        ):
            with self.assertRaises(LifecycleError) as raised:
                systemd.start("my-app")

        message = str(raised.exception)
        self.assertIn("Unit not found.", message)
        self.assertIn("sandcastle logs my-app", message)

    def test_without_systemd_the_verb_says_where_it_expects_to_run(self):
        with mock.patch.object(systemd, "available", return_value=False):
            with self.assertRaises(LifecycleError) as raised:
                systemd.stop("my-app")
        self.assertIn("sandbox host", str(raised.exception))


class ConfirmRunningTests(unittest.TestCase):
    """`microvm@.service` is Type=simple with Restart=always under qemu.

    `systemctl start` therefore succeeds for a guest that cannot boot, so the
    readiness check is the only thing standing between a bad rebuild and a
    silent restart loop.
    """

    def setUp(self):
        patcher = mock.patch.object(systemd, "available", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def confirm(self, samples, **kwargs):
        with mock.patch.object(systemd, "properties", side_effect=samples):
            return systemd.confirm_running(
                "my-app", sleep=self.sleep, clock=self.clock, **kwargs
            )

    @staticmethod
    def running(invocation="aaa"):
        return {"ActiveState": "active", "SubState": "running", "InvocationID": invocation}

    def test_a_guest_that_stays_up_for_the_settle_window_is_accepted(self):
        result = self.confirm([self.running()] * 40, settle=2.0, timeout=30.0)
        self.assertEqual(result["ActiveState"], "active")

    def test_a_guest_that_dies_and_restarts_is_a_failure(self):
        samples = [self.running("aaa"), self.running("aaa"), self.running("bbb")]
        with self.assertRaises(LifecycleError) as raised:
            self.confirm(samples, settle=10.0, timeout=30.0)
        self.assertIn("not booting", str(raised.exception))

    def test_an_auto_restarting_unit_fails_immediately(self):
        samples = [{"ActiveState": "activating", "SubState": "auto-restart"}]
        with self.assertRaises(LifecycleError):
            self.confirm(samples, settle=1.0, timeout=30.0)

    def test_a_failed_unit_reports_its_result(self):
        samples = [{"ActiveState": "failed", "SubState": "failed", "Result": "exit-code"}]
        with self.assertRaises(LifecycleError) as raised:
            self.confirm(samples, settle=1.0, timeout=30.0)
        self.assertIn("exit-code", str(raised.exception))

    def test_a_unit_that_never_reaches_running_times_out(self):
        samples = [{"ActiveState": "activating", "SubState": "start"}] * 200
        with self.assertRaises(LifecycleError) as raised:
            self.confirm(samples, settle=1.0, timeout=5.0)
        self.assertIn("did not hold a running state", str(raised.exception))

    def test_a_flap_back_into_running_restarts_the_settle_window(self):
        samples = (
            [self.running()]
            + [{"ActiveState": "deactivating", "SubState": "stop"}]
            + [self.running()] * 40
        )
        # Accepted only because it then stayed up; the earlier sample alone was
        # not enough.
        self.assertTrue(self.confirm(samples, settle=2.0, timeout=30.0))

    def test_without_systemd_the_check_is_skipped(self):
        with mock.patch.object(systemd, "available", return_value=False):
            self.assertEqual(systemd.confirm_running("my-app"), {})


class JournalCommandTests(unittest.TestCase):
    def test_the_command_covers_every_unit_and_validates_its_arguments(self):
        command = systemd.journal_command("my-app", lines=50, follow=True)
        self.assertEqual(command.count("--unit"), len(systemd.unit_names("my-app")))
        self.assertIn("--follow", command)
        self.assertEqual(command[command.index("--lines") + 1], "50")

        with self.assertRaises(Exception):
            systemd.journal_command("my-app", lines="; rm -rf /")


if __name__ == "__main__":
    unittest.main()
