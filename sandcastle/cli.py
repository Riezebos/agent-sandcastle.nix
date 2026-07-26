"""The `sandcastle` command-line interface.

Only the inventory and build primitives exist so far; the lifecycle,
package, fork, and route commands land in later milestones. Every command
resolves its host configuration first so a `--config` or `--state-dir`
override behaves identically everywhere.
"""

import argparse
import dataclasses
import json
import sys

from . import __version__, build, config as config_module, state, systemd
from .errors import SandcastleError


def build_parser():
    parser = argparse.ArgumentParser(
        prog="sandcastle",
        description="Manage isolated development MicroVMs on this host.",
    )
    parser.add_argument("--version", action="version", version=f"sandcastle {__version__}")
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="host configuration file (default: /etc/sandcastle/config.json)",
    )
    parser.add_argument(
        "--state-dir",
        metavar="PATH",
        help="override the sandcastle state directory",
    )
    parser.add_argument(
        "--flake",
        metavar="REF",
        help="override the flake reference sandbox runners are built from",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    listing = subparsers.add_parser("list", help="list every sandbox")
    listing.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    listing.set_defaults(handler=cmd_list)

    show = subparsers.add_parser("show", help="show one sandbox's specification")
    show.add_argument("name")
    show.add_argument("--json", action="store_true", help="emit the raw specification")
    show.set_defaults(handler=cmd_show)

    builder = subparsers.add_parser(
        "build",
        help="build a sandbox runner from its stored specification",
    )
    builder.add_argument("name")
    builder.add_argument(
        "--install",
        action="store_true",
        help="move the sandbox's current runner symlink and GC root to the result",
    )
    builder.set_defaults(handler=cmd_build)

    return parser


def resolve_config(arguments):
    resolved = config_module.load(arguments.config)
    overrides = {}
    if arguments.state_dir:
        overrides["state_dir"] = arguments.state_dir
    if arguments.flake:
        overrides["flake_ref"] = arguments.flake
    if overrides:
        resolved = dataclasses.replace(resolved, **overrides)
    return resolved


def cmd_list(arguments, resolved, out):
    store = state.Store(resolved)
    rows = []
    for spec in store.load_all():
        rows.append(
            {
                "name": spec.name,
                "state": systemd.is_active(spec.name),
                "ipv4": spec.ipv4,
                "cid": spec.vsock_cid,
                "vcpu": spec.vcpu,
                "memoryMiB": spec.memory_mib,
                "packages": len(spec.packages),
                "runner": state.installed_runner(resolved, spec.name) or "",
            }
        )

    if arguments.json:
        print(json.dumps(rows, indent=2, sort_keys=True), file=out)
        return 0

    if not rows:
        print("No sandboxes yet. Create one with: sandcastle create <name>", file=out)
        return 0

    headers = ("NAME", "STATE", "ADDRESS", "CID", "CPU", "MEM", "PKGS")
    table = [headers] + [
        (
            row["name"],
            row["state"],
            row["ipv4"],
            str(row["cid"]),
            str(row["vcpu"]),
            f"{row['memoryMiB']}M",
            str(row["packages"]),
        )
        for row in rows
    ]
    widths = [max(len(cell) for cell in column) for column in zip(*table)]
    for line in table:
        print("  ".join(cell.ljust(width) for cell, width in zip(line, widths)).rstrip(), file=out)
    return 0


def cmd_show(arguments, resolved, out):
    spec = state.Store(resolved).load(arguments.name)
    if arguments.json:
        print(json.dumps(spec.to_dict(), indent=2, sort_keys=True), file=out)
        return 0

    document = spec.to_dict()
    document["state"] = systemd.is_active(spec.name)
    document["runner"] = state.installed_runner(resolved, spec.name) or "(not installed)"
    document["homeImage"] = resolved.home_image_path(spec.name)
    document["tapDevice"] = state.tap_name(spec.name)
    for key in sorted(document):
        value = document[key]
        if isinstance(value, list):
            value = ", ".join(str(entry) for entry in value) or "(none)"
        print(f"{key}: {value}", file=out)
    return 0


def cmd_build(arguments, resolved, out):
    store = state.Store(resolved)
    spec = store.load(arguments.name)
    runner = build.build_runner(resolved, spec)

    if arguments.install:
        with state.file_lock(resolved, spec.name):
            previous = build.install_runner(resolved, spec.name, runner)
        if previous and previous != runner:
            print(f"previous runner retained as a GC root: {previous}", file=out)

    print(runner, file=out)
    return 0


def main(argv=None, out=None):
    parser = build_parser()
    arguments = parser.parse_args(argv)
    out = out or sys.stdout
    try:
        resolved = resolve_config(arguments)
        return arguments.handler(arguments, resolved, out)
    except SandcastleError as error:
        print(f"sandcastle: {error}", file=sys.stderr)
        return error.exit_code
    except KeyboardInterrupt:
        print("sandcastle: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
