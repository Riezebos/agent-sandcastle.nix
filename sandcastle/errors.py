"""Error types shared by every sandcastle module.

Every error the CLI raises deliberately carries an exit code so `cli.main`
can turn an exception into a predictable shell status without a table of
isinstance checks.
"""


class SandcastleError(Exception):
    """Base class for expected, operator-facing failures."""

    exit_code = 1


class ValidationError(SandcastleError):
    """A name, address, port, or other operator-supplied value is invalid."""

    exit_code = 2


class NotFoundError(SandcastleError):
    """A referenced sandbox, spec, or state path does not exist."""

    exit_code = 3


class ConflictError(SandcastleError):
    """A name or allocated resource is already taken, or a lock is held."""

    exit_code = 4


class ExhaustedError(SandcastleError):
    """An allocation pool (addresses, CIDs) has no free entries left."""

    exit_code = 5


class BuildError(SandcastleError):
    """Nix evaluation or realisation of a sandbox runner failed."""

    exit_code = 6


class StateError(SandcastleError):
    """On-disk state is missing, unreadable, or internally inconsistent."""

    exit_code = 7
