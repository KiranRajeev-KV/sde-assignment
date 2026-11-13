"""Errors the CLI turns into exit codes."""


class DataError(Exception):
    """The input data or database state is unusable; the run is refused (exit 1)."""
