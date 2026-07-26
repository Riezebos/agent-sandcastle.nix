import unittest

from sandcastle import validate
from sandcastle.errors import ValidationError


class NameTests(unittest.TestCase):
    def test_accepts_ordinary_names(self):
        for name in ("a", "my-app", "app2", "a" * 32):
            self.assertEqual(validate.validate_name(name), name)

    def test_rejects_shapes_that_break_units_or_paths(self):
        for name in (
            "",
            "-leading",
            "trailing-",
            "Upper",
            "with_underscore",
            "with.dot",
            "a" * 33,
            "../escape",
            "with space",
            "sandbox@instance",
        ):
            with self.assertRaises(ValidationError, msg=name):
                validate.validate_name(name)

    def test_rejects_reserved_names(self):
        for name in sorted(validate.RESERVED_NAMES):
            with self.assertRaises(ValidationError, msg=name):
                validate.validate_name(name)


class PackageTests(unittest.TestCase):
    def test_accepts_attribute_paths(self):
        for attr in ("nodejs", "python3", "nodePackages.pnpm", "_7zz", "pkg-config"):
            self.assertEqual(validate.validate_package_attr(attr), attr)

    def test_rejects_nix_injection_shapes(self):
        for attr in (
            "",
            '"; malicious',
            "with space",
            "${pkgs.hello}",
            "a.b.c.d.e",
            "../../etc",
            "pkgs.'quoted'",
            "x" * 100,
        ):
            with self.assertRaises(ValidationError, msg=attr):
                validate.validate_package_attr(attr)

    def test_packages_are_sorted_and_deduplicated(self):
        self.assertEqual(
            validate.validate_packages(["uv", "nodejs", "uv"]),
            ["nodejs", "uv"],
        )

    def test_package_count_is_capped(self):
        with self.assertRaises(ValidationError):
            validate.validate_packages([f"pkg{index}" for index in range(validate.MAX_PACKAGES + 1)])


class AddressTests(unittest.TestCase):
    def test_subnet_membership_is_enforced(self):
        self.assertEqual(validate.validate_ipv4("10.88.0.5", subnet="10.88.0.0/24"), "10.88.0.5")
        with self.assertRaises(ValidationError):
            validate.validate_ipv4("10.89.0.5", subnet="10.88.0.0/24")

    def test_network_and_broadcast_are_rejected(self):
        for address in ("10.88.0.0", "10.88.0.255"):
            with self.assertRaises(ValidationError, msg=address):
                validate.validate_ipv4(address, subnet="10.88.0.0/24")

    def test_forbidden_addresses_are_rejected(self):
        with self.assertRaises(ValidationError):
            validate.validate_ipv4("10.88.0.1", subnet="10.88.0.0/24", forbidden=["10.88.0.1"])

    def test_mac_must_be_locally_administered_unicast(self):
        self.assertEqual(validate.validate_mac("02:00:AB:CD:EF:01"), "02:00:ab:cd:ef:01")
        with self.assertRaises(ValidationError):
            validate.validate_mac("01:00:00:00:00:01")  # multicast
        with self.assertRaises(ValidationError):
            validate.validate_mac("00:11:22:33:44:55")  # globally administered
        with self.assertRaises(ValidationError):
            validate.validate_mac("nonsense")

    def test_vsock_reserved_cids_are_rejected(self):
        for cid in (0, 1, 2, -1):
            with self.assertRaises(ValidationError, msg=str(cid)):
                validate.validate_vsock_cid(cid)
        self.assertEqual(validate.validate_vsock_cid(3), 3)


class HostnameTests(unittest.TestCase):
    def test_zone_membership(self):
        self.assertEqual(
            validate.validate_hostname("My-App.Example.com", zone="example.com"),
            "my-app.example.com",
        )
        with self.assertRaises(ValidationError):
            validate.validate_hostname("my-app.elsewhere.com", zone="example.com")

    def test_zone_apex_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate.validate_hostname("example.com", zone="example.com")

    def test_malformed_labels_are_rejected(self):
        for hostname in ("", "a..b", "-lead.example.com", "under_score.example.com"):
            with self.assertRaises(ValidationError, msg=hostname):
                validate.validate_hostname(hostname)


class StorePathTests(unittest.TestCase):
    def test_accepts_a_real_store_path_shape(self):
        path = "/nix/store/00000000000000000000000000000000-sandbox-spec.json"
        self.assertEqual(validate.validate_store_path(path), path)

    def test_rejects_anything_else(self):
        for path in (
            "/tmp/spec.json",
            "/nix/store/short-name",
            "/nix/store/00000000000000000000000000000000-name; rm -rf /",
            "",
        ):
            with self.assertRaises(ValidationError, msg=path):
                validate.validate_store_path(path)


class BoundsTests(unittest.TestCase):
    def test_resource_bounds(self):
        self.assertEqual(validate.validate_vcpu(4), 4)
        self.assertEqual(validate.validate_memory_mib("2048"), 2048)
        with self.assertRaises(ValidationError):
            validate.validate_vcpu(0)
        with self.assertRaises(ValidationError):
            validate.validate_memory_mib(64)
        with self.assertRaises(ValidationError):
            validate.validate_disk_mib(10)
        with self.assertRaises(ValidationError):
            validate.validate_vcpu(True)


if __name__ == "__main__":
    unittest.main()
