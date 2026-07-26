"""The `sandcastle` command-line interface.

The inventory, lifecycle, and guest-access commands exist; packages, fork,
and route commands land in later milestones. Every command resolves its host
configuration first so a `--config` or `--state-dir` override behaves
identically everywhere.
"""

import argparse
import dataclasses
import json
import subprocess
import sys

from . import (
    __version__,
    build,
    config as config_module,
    lifecycle,
    spec as spec_module,
    ssh,
    state,
    systemd,
)
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

    status = subparsers.add_parser(
        "status",
        help="show one sandbox's runtime state without evaluating Nix",
    )
    status.add_argument("name")
    status.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    status.set_defaults(handler=cmd_status)

    creation = subparsers.add_parser("create", help="create a new sandbox")
    creation.add_argument("name")
    creation.add_argument(
        "--packages",
        nargs="+",
        default=[],
        metavar="ATTR",
        help=(
            "nixpkgs attribute paths, or one of the profiles "
            + ", ".join(sorted(spec_module.PROFILES))
        ),
    )
    creation.add_argument(
        "--agents",
        nargs="*",
        metavar="AGENT",
        help=(
            "coding-agent CLIs to install (default: "
            + " ".join(spec_module.KNOWN_AGENTS)
            + "); pass with no values for none"
        ),
    )
    creation.add_argument("--vcpu", type=int, help="virtual CPUs")
    creation.add_argument("--memory", type=int, metavar="MIB", help="guest RAM in MiB")
    creation.add_argument("--disk", type=int, metavar="MIB", help="/home/dev size in MiB")
    creation.add_argument("--start", action="store_true", help="start the sandbox once built")
    creation.set_defaults(handler=cmd_create)

    starter = subparsers.add_parser("start", help="start a sandbox")
    starter.add_argument("name")
    _add_wait_flag(starter)
    starter.set_defaults(handler=cmd_start)

    stopper = subparsers.add_parser("stop", help="shut a sandbox down")
    stopper.add_argument("name")
    stopper.set_defaults(handler=cmd_stop)

    restarter = subparsers.add_parser("restart", help="restart a sandbox")
    restarter.add_argument("name")
    _add_wait_flag(restarter)
    restarter.set_defaults(handler=cmd_restart)

    rebuilder = subparsers.add_parser(
        "rebuild",
        help="rebuild a sandbox's runner and activate it",
    )
    rebuilder.add_argument("name")
    activation = rebuilder.add_mutually_exclusive_group()
    activation.add_argument(
        "--restart",
        dest="restart_guest",
        action="store_true",
        default=None,
        help="restart the guest even if it was stopped",
    )
    activation.add_argument(
        "--no-restart",
        dest="restart_guest",
        action="store_false",
        default=None,
        help="install the new runner but leave the running guest alone",
    )
    _add_wait_flag(rebuilder)
    rebuilder.set_defaults(handler=cmd_rebuild)

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

    logs = subparsers.add_parser("logs", help="read a sandbox's logs")
    logs.add_argument("name")
    logs.add_argument("-f", "--follow", action="store_true", help="keep printing new lines")
    logs.add_argument(
        "-n",
        "--lines",
        type=int,
        default=200,
        metavar="N",
        help="how many lines of history to show (default: 200)",
    )
    logs.add_argument(
        "--guest",
        action="store_true",
        help="read the guest's own journal over VSOCK instead of the host's",
    )
    logs.set_defaults(handler=cmd_logs)

    secure_shell = subparsers.add_parser(
        "ssh",
        help="open a shell in a sandbox as the dev user, over VSOCK",
    )
    secure_shell.add_argument("name")
    secure_shell.add_argument(
        "-A",
        "--agent",
        action="store_true",
        help="forward the operator's SSH agent into the guest",
    )
    secure_shell.add_argument(
        "remote_command",
        nargs=argparse.REMAINDER,
        metavar="COMMAND",
        help="a command to run in the guest instead of an interactive shell",
    )
    secure_shell.set_defaults(handler=cmd_ssh)

    deletion = subparsers.add_parser("delete", help="delete a stopped sandbox")
    deletion.add_argument("name")
    deletion.add_argument("--yes", action="store_true", help="confirm the deletion")
    deletion.add_argument(
        "--delete-credentials",
        action="store_true",
        help="also delete the sandbox's agent and Git credentials",
    )
    deletion.set_defaults(handler=cmd_delete)

    return parser


def _add_wait_flag(subparser):
    subparser.add_argument(
        "--no-wait",
        dest="wait",
        action="store_false",
        default=True,
        help="return as soon as systemd accepts the request",
    )


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
    specs = store.load_all()
    # One systemctl call for the whole inventory, and no Nix evaluation: `list`
    # stays usable on a host with many sandboxes.
    states = systemd.active_states([spec.name for spec in specs])

    rows = [
        {
            "name": spec.name,
            "state": states.get(spec.name, systemd.UNKNOWN),
            "ipv4": spec.ipv4,
            "cid": spec.vsock_cid,
            "vcpu": spec.vcpu,
            "memoryMiB": spec.memory_mib,
            "packages": len(spec.packages),
            "runner": state.installed_runner(resolved, spec.name) or "",
        }
        for spec in specs
    ]

    if arguments.json:
        print(json.dumps(rows, indent=2, sort_keys=True), file=out)
        return 0

    if not rows:
        print("No sandboxes yet. Create one with: sandcastle create <name>", file=out)
        return 0

    _print_table(
        out,
        ("NAME", "STATE", "ADDRESS", "CID", "CPU", "MEM", "PKGS"),
        [
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
        ],
    )
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
    _print_fields(out, document)
    return 0


def cmd_status(arguments, resolved, out):
    document = lifecycle.status(resolved, state.Store(resolved), arguments.name)
    if arguments.json:
        print(json.dumps(document, indent=2, sort_keys=True), file=out)
        return 0
    _print_fields(out, document)
    if document["stale"]:
        print(
            "\nThis sandbox is running an older runner than the one installed.\n"
            f"Restart it to pick the new one up: sandcastle restart {arguments.name}",
            file=out,
        )
    return 0


def cmd_create(arguments, resolved, out):
    store = state.Store(resolved)
    report = _reporter(out)
    spec = lifecycle.create(
        resolved,
        store,
        arguments.name,
        packages=arguments.packages,
        agents=arguments.agents,
        vcpu=arguments.vcpu,
        memory_mib=arguments.memory,
        home_disk_mib=arguments.disk,
        report=report,
    )

    if arguments.start:
        lifecycle.start(resolved, store, spec.name, report=report)
    else:
        report(f"created {spec.name}; start it with: sandcastle start {spec.name}")
    return 0


def cmd_start(arguments, resolved, out):
    lifecycle.start(
        resolved, state.Store(resolved), arguments.name, wait=arguments.wait, report=_reporter(out)
    )
    return 0


def cmd_stop(arguments, resolved, out):
    lifecycle.stop(resolved, state.Store(resolved), arguments.name, report=_reporter(out))
    return 0


def cmd_restart(arguments, resolved, out):
    lifecycle.restart(
        resolved, state.Store(resolved), arguments.name, wait=arguments.wait, report=_reporter(out)
    )
    return 0


def cmd_rebuild(arguments, resolved, out):
    runner, changed = lifecycle.rebuild(
        resolved,
        state.Store(resolved),
        arguments.name,
        restart_guest=arguments.restart_guest,
        wait=arguments.wait,
        report=_reporter(out),
    )
    if not changed:
        print(f"{arguments.name} is already up to date", file=out)
    print(runner, file=out)
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


def cmd_logs(arguments, resolved, out):
    store = state.Store(resolved)
    spec = store.load(arguments.name)

    if arguments.guest:
        remote = ["journalctl", "--lines", str(arguments.lines)]
        if arguments.follow:
            remote.append("--follow")
        command = ssh.ssh_command(resolved, spec, remote_command=remote)
        return ssh.exec_ssh(command)

    return _run_interactive(
        systemd.journal_command(spec.name, lines=arguments.lines, follow=arguments.follow)
    )


def cmd_ssh(arguments, resolved, out):
    spec = state.Store(resolved).load(arguments.name)
    remote_command = list(arguments.remote_command)
    if remote_command and remote_command[0].startswith("-"):
        print(
            f"sandcastle: {remote_command[0]!r} would be sent to the guest as a "
            "command, not to ssh.\n"
            f"Put ssh options after --, as in: sandcastle ssh {arguments.name} "
            f"-- {remote_command[0]}",
            file=sys.stderr,
        )
        return 2

    command = ssh.ssh_command(
        resolved,
        spec,
        agent_forwarding=arguments.agent,
        ssh_options=arguments.passthrough,
        remote_command=remote_command,
    )
    return ssh.exec_ssh(command)


def cmd_delete(arguments, resolved, out):
    if not arguments.yes:
        print(
            f"sandcastle: refusing to delete {arguments.name!r} without --yes.\n"
            f"This removes its specification and its /home/dev disk.",
            file=sys.stderr,
        )
        return 1

    lifecycle.delete(
        resolved,
        state.Store(resolved),
        arguments.name,
        delete_credentials=arguments.delete_credentials,
        report=_reporter(out),
    )
    return 0


def split_passthrough(argv):
    """Split the command line at the first `--`.

    Everything after it belongs to the tool sandcastle execs rather than to
    sandcastle, so `sandcastle ssh app -- -A -L 8080:localhost:8080` reaches
    ssh as options while `sandcastle ssh app tmux attach` runs a command in
    the guest. argparse consumes the marker itself, so the split happens
    before parsing.
    """
    argv = list(argv)
    if "--" not in argv:
        return argv, []
    index = argv.index("--")
    return argv[:index], argv[index + 1 :]


def _reporter(out):
    def report(message):
        print(message, file=out)

    return report


def _print_fields(out, document):
    for key in sorted(document):
        value = document[key]
        if isinstance(value, list):
            value = ", ".join(str(entry) for entry in value) or "(none)"
        print(f"{key}: {value}", file=out)


def _print_table(out, headers, rows):
    table = [tuple(headers)] + [tuple(row) for row in rows]
    widths = [max(len(cell) for cell in column) for column in zip(*table)]
    for line in table:
        print("  ".join(cell.ljust(width) for cell, width in zip(line, widths)).rstrip(), file=out)


def _run_interactive(command):
    """Run a command with the operator's terminal attached."""
    try:
        return subprocess.call(command)
    except FileNotFoundError:
        print(f"sandcastle: {command[0]} is not on PATH", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def main(argv=None, out=None):
    argv, passthrough = split_passthrough(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    arguments = parser.parse_args(argv)
    arguments.passthrough = passthrough
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
