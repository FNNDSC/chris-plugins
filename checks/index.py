"""Run every check on the index and report what fails.

This is what a pull request runs. It reads ``plugins/``, holds each
descriptor to its schema, then runs the checks that judge the set, the
check that keeps credentials out, and the checks of each pipeline against
the plugins it is made of.

Key components:
    - findings_collect: run every check against one index root.
    - main: command-line entry point.

Typical usage:
    python -m checks.index
    python -m checks.index --root /path/to/chris-plugins

Dependencies:
    ``jsonschema`` and ``pyyaml``. Exits 0 when the index is clean, 1
    otherwise, with one finding per line on standard error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from checks.credentials import ExceptionsLoaded, defaults_check, exceptions_check, exceptions_load
from checks.model import Finding, PluginsLoaded, plugins_load
from checks.pipelines import (
    PipelinesLoaded,
    excludedSources_check,
    pipelines_check,
    pipelines_load,
)
from checks.plugins import excluded_check, excludedNames_load, fileNames_check, nameCases_check

EXIT_CLEAN: int = 0
EXIT_FINDINGS: int = 1
DESCRIPTION: str = "Check the ChRIS plugin index: plugins, pipelines and credentials."


def findings_collect(root: Path) -> list[Finding]:
    """Run every check against one index root.

    Args:
        root: The index root, holding ``plugins/`` and ``schema/``.

    Returns:
        Every finding, schema faults first. Empty when the index is clean.

    Example:
        >>> findings_collect(Path("."))  # doctest: +SKIP
        []
    """
    loaded: PluginsLoaded = plugins_load(root)
    excused: ExceptionsLoaded = exceptions_load(root)
    piped: PipelinesLoaded = pipelines_load(root)
    return [
        *loaded.findings,
        *fileNames_check(loaded.plugins),
        *nameCases_check(loaded.plugins),
        *excluded_check(loaded.plugins, excludedNames_load(root)),
        *excused.findings,
        *defaults_check(loaded.plugins, excused.exceptions),
        *exceptions_check(loaded.plugins, excused.exceptions),
        *piped.findings,
        *pipelines_check(piped.pipelines, loaded.plugins, excused.exceptions),
        *excludedSources_check(root),
    ]


def main() -> int:
    """Check the index named on the command line.

    Returns:
        ``EXIT_CLEAN`` when there are no findings, ``EXIT_FINDINGS``
        otherwise.

    Example:
        >>> sys.argv = ["checks.index"]  # doctest: +SKIP
        >>> main()  # doctest: +SKIP
        0
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="checks.index", description=DESCRIPTION
    )
    parser.add_argument("--root", type=Path, default=Path("."), help="the index root")
    arguments: argparse.Namespace = parser.parse_args()
    findings: list[Finding] = findings_collect(arguments.root)
    for finding in findings:
        print(finding.report, file=sys.stderr)
    if findings:
        print(f"{len(findings)} finding(s)", file=sys.stderr)
    return EXIT_FINDINGS if findings else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
