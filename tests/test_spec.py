import json
import unittest

from sandcastle import config as config_module
from sandcastle import spec as spec_module
from sandcastle.errors import StateError, ValidationError

VALID = {
    "schemaVersion": 1,
    "name": "my-app",
    "vcpu": 2,
    "memoryMiB": 2304,
    "homeDiskMiB": 16384,
    "packages": ["nodejs", "uv"],
    "agents": ["claude-code"],
    "ipv4": "10.88.0.16",
    "mac": "02:00:aa:bb:cc:dd",
    "vsockCid": 100,
    "machineId": "0123456789abcdef0123456789abcdef",
    "repoUrl": "",
    "repoBranch": "",
    "createdAt": "2026-07-25T00:00:00Z",
    "parent": "",
}


class RoundTripTests(unittest.TestCase):
    def test_document_round_trips_unchanged(self):
        parsed = spec_module.from_dict(VALID)
        self.assertEqual(parsed.to_dict(), VALID)

    def test_json_round_trip(self):
        parsed = spec_module.from_json(json.dumps(VALID))
        self.assertEqual(spec_module.from_json(parsed.to_json()), parsed)

    def test_defaults_fill_in_optional_fields(self):
        minimal = {
            "schemaVersion": 1,
            "name": "minimal",
            "ipv4": "10.88.0.17",
            "mac": "02:00:aa:bb:cc:de",
            "vsockCid": 101,
            "machineId": "f" * 32,
        }
        parsed = spec_module.from_dict(minimal)
        self.assertEqual(parsed.vcpu, spec_module.DEFAULT_VCPU)
        self.assertEqual(parsed.packages, [])
        self.assertEqual(parsed.agents, sorted(spec_module.KNOWN_AGENTS))


class MigrationTests(unittest.TestCase):
    def test_current_version_passes_through(self):
        self.assertEqual(spec_module.migrate(dict(VALID))["schemaVersion"], 1)

    def test_missing_version_is_rejected(self):
        document = dict(VALID)
        del document["schemaVersion"]
        with self.assertRaises(StateError):
            spec_module.migrate(document)

    def test_non_integer_version_is_rejected(self):
        for version in ("1", 1.0, True, None):
            with self.assertRaises(StateError, msg=repr(version)):
                spec_module.migrate({**VALID, "schemaVersion": version})

    def test_newer_version_is_refused_rather_than_guessed_at(self):
        with self.assertRaises(StateError) as caught:
            spec_module.migrate({**VALID, "schemaVersion": spec_module.CURRENT_SCHEMA_VERSION + 1})
        self.assertIn("newer sandcastle", str(caught.exception))

    def test_older_version_without_a_migration_is_an_error(self):
        with self.assertRaises(StateError):
            spec_module.migrate({**VALID, "schemaVersion": 0})

    def test_registered_migration_is_applied_in_order(self):
        # Exercises the migration engine itself by pretending the current
        # schema was preceded by one that spelled packages differently.
        original = spec_module.CURRENT_SCHEMA_VERSION
        try:
            spec_module.CURRENT_SCHEMA_VERSION = original + 1
            spec_module._MIGRATIONS[original] = lambda document: {
                **{key: value for key, value in document.items() if key != "pkgs"},
                "packages": document["pkgs"],
            }
            legacy = {**VALID, "schemaVersion": original, "pkgs": ["nodejs"]}
            del legacy["packages"]
            migrated = spec_module.migrate(legacy)
            self.assertEqual(migrated["packages"], ["nodejs"])
            self.assertEqual(migrated["schemaVersion"], original + 1)
        finally:
            spec_module.CURRENT_SCHEMA_VERSION = original
            spec_module._MIGRATIONS.pop(original, None)


class ValidationTests(unittest.TestCase):
    def test_unknown_keys_are_rejected(self):
        with self.assertRaises(StateError):
            spec_module.from_dict({**VALID, "surprise": 1})

    def test_missing_identity_keys_are_reported_together(self):
        with self.assertRaises(StateError) as caught:
            spec_module.from_dict({"schemaVersion": 1, "name": "my-app"})
        message = str(caught.exception)
        for key in ("ipv4", "mac", "vsockCid", "machineId"):
            self.assertIn(key, message)

    def test_address_is_checked_against_the_configured_subnet(self):
        resolved = config_module.Config(subnet="10.88.0.0/24")
        with self.assertRaises(ValidationError):
            spec_module.from_dict({**VALID, "ipv4": "192.168.1.5"}, config=resolved)

    def test_unknown_agent_is_rejected(self):
        with self.assertRaises(ValidationError):
            spec_module.from_dict({**VALID, "agents": ["happy-coder"]})

    def test_invalid_package_attribute_is_rejected(self):
        with self.assertRaises(ValidationError):
            spec_module.from_dict({**VALID, "packages": ['"; evil']})


class ProfileTests(unittest.TestCase):
    def test_profiles_expand_and_merge(self):
        self.assertEqual(
            spec_module.expand_packages(["node", "python", "ripgrep"]),
            sorted(set(["nodejs", "pnpm", "python3", "uv", "ripgrep"])),
        )

    def test_unknown_names_pass_through_as_attributes(self):
        self.assertEqual(spec_module.expand_packages(["gcc"]), ["gcc"])

    def test_expansion_still_validates(self):
        with self.assertRaises(ValidationError):
            spec_module.expand_packages(["not a package"])


if __name__ == "__main__":
    unittest.main()
