"""Keep credentials out of the index.

The index is public, and a descriptor's parameter defaults are registered
with every CUBE filled from it. A parameter whose name reads as a credential
(``password``, ``token``, ``secret``, ``key``) may therefore hold no value
here: its default is absent or empty, and whoever runs the plugin supplies
the value.

A name can read as a credential without being one (``splitToken`` is a
delimiter). Those are listed one by one in ``credential-exceptions.yml``,
each with its reason, and an entry that no longer matches anything is itself
a finding, so the list cannot go stale.

Key components:
    - CredentialException: one parameter allowed to keep its value.
    - name_checkIsCredential: whether a parameter name reads as a credential.
    - value_checkIsEmpty: whether a value holds nothing a credential could be.
    - exceptions_load: read and validate ``credential-exceptions.yml``.
    - defaults_check: no credential-named parameter carries a default.
    - exceptions_check: every exception still points at such a parameter.

Typical usage:
    loaded = exceptions_load(root)
    findings = defaults_check(plugins, loaded.exceptions)
    findings += exceptions_check(plugins, loaded.exceptions)

Dependencies:
    ``pyyaml`` and ``jsonschema``. ``credential-exceptions.yml`` is a list of
    ``plugin``, ``parameter``, ``reason`` entries, held to
    ``schema/credential-exceptions.schema.json``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml
from jsonschema import Draft202012Validator

from checks.model import Finding, Plugin, document_validate

EXCEPTIONS_PATH: str = "credential-exceptions.yml"
EXCEPTIONS_SCHEMA_PATH: str = "schema/credential-exceptions.schema.json"
CREDENTIAL_PATTERN: re.Pattern[str] = re.compile(
    r"pass(?:word|wd|phrase)|token|secret|key", re.IGNORECASE
)


@dataclass(frozen=True)
class CredentialException:
    """One parameter allowed to keep a value despite its name.

    Attributes:
        plugin: The plugin's name, as its file in ``plugins/`` spells it.
        parameter: The parameter's name.
        reason: Why the value is not a credential.

    Example:
        >>> CredentialException("pl-a", "splitToken", "a delimiter").parameter
        'splitToken'
    """

    plugin: str
    parameter: str
    reason: str


@dataclass(frozen=True)
class ExceptionsLoaded:
    """What reading ``credential-exceptions.yml`` produced.

    Attributes:
        exceptions: The entries, in file order. Empty if the file is invalid.
        findings: One entry per fault in the file.

    Example:
        >>> ExceptionsLoaded(exceptions=(), findings=()).exceptions
        ()
    """

    exceptions: tuple[CredentialException, ...]
    findings: tuple[Finding, ...]


def name_checkIsCredential(name: str) -> bool:
    """Say whether a parameter name reads as a credential.

    The match is on a substring, ignoring case, because plugins run words
    together (``awssecretkey``, ``orthancpassword``). It errs towards yes; a
    wrong yes costs one line in ``credential-exceptions.yml``.

    Args:
        name: The parameter's name.

    Returns:
        ``True`` if the name contains ``password``, ``passwd``,
        ``passphrase``, ``token``, ``secret`` or ``key``.

    Example:
        >>> name_checkIsCredential("orthancpassword")
        True
        >>> name_checkIsCredential("orthancUsername")
        False
    """
    return CREDENTIAL_PATTERN.search(name) is not None


def value_checkIsEmpty(value: object) -> bool:
    """Say whether a value holds nothing a credential could be.

    Args:
        value: A parameter's default, or the value a pipeline sets.

    Returns:
        ``True`` for ``None``, a string that is empty or only whitespace, and
        a boolean (a flag such as ``--useToken`` carries no credential).

    Example:
        >>> [value_checkIsEmpty(value) for value in (None, "", False, "chris1234")]
        [True, True, True, False]
    """
    if value is None or isinstance(value, bool):
        return True
    return isinstance(value, str) and not value.strip()


def exceptions_load(root: Path) -> ExceptionsLoaded:
    """Read and validate ``credential-exceptions.yml``.

    Args:
        root: The index root, holding the file and its schema.

    Returns:
        The exceptions, and a finding per schema error. An invalid file
        yields no exceptions, so every parameter it meant to excuse is
        reported as well.

    Example:
        >>> loaded = exceptions_load(Path("."))  # doctest: +SKIP
        >>> loaded.exceptions[0].plugin  # doctest: +SKIP
        'pl-dicom_headeredit'
    """
    schema: object = json.loads((root / EXCEPTIONS_SCHEMA_PATH).read_text(encoding="utf-8"))
    validator = Draft202012Validator(cast("Mapping[str, object]", schema))
    document: object = yaml.safe_load((root / EXCEPTIONS_PATH).read_text(encoding="utf-8"))
    findings: list[Finding] = document_validate(document, validator, EXCEPTIONS_PATH)
    if findings:
        return ExceptionsLoaded(exceptions=(), findings=tuple(findings))
    entries = cast("list[Mapping[str, str]]", document)
    exceptions: tuple[CredentialException, ...] = tuple(
        CredentialException(entry["plugin"], entry["parameter"], entry["reason"])
        for entry in entries
    )
    return ExceptionsLoaded(exceptions=exceptions, findings=())


def defaults_check(
    plugins: Iterable[Plugin], exceptions: Iterable[CredentialException]
) -> list[Finding]:
    """Check that no credential-named parameter carries a default.

    Args:
        plugins: The plugins to judge.
        exceptions: The parameters allowed to keep their value.

    Returns:
        One finding per parameter whose name reads as a credential, whose
        default is not empty, and which no exception names. The finding does
        not repeat the value.

    Example:
        >>> from checks.model import Parameter
        >>> parameters = (
        ...     Parameter("password", "str", "hunter2"),
        ...     Parameter("splitToken", "str", "++"),
        ...     Parameter("apiToken", "str", ""),
        ... )
        >>> plugin = Plugin("pl-a", "1.0.0", "plugins/pl-a.json", parameters)
        >>> excused = [CredentialException("pl-a", "splitToken", "a delimiter")]
        >>> [finding.reason for finding in defaults_check([plugin], excused)]
        ["parameter 'password' reads as a credential and has a default; leave it empty"]
    """
    excused: set[tuple[str, str]] = {(entry.plugin, entry.parameter) for entry in exceptions}
    findings: list[Finding] = []
    for plugin in plugins:
        for parameter in plugin.parameters:
            if (plugin.name, parameter.name) in excused:
                continue
            if name_checkIsCredential(parameter.name) and not value_checkIsEmpty(parameter.default):
                findings.append(
                    Finding(
                        plugin.path,
                        f"parameter {parameter.name!r} reads as a credential and has a "
                        "default; leave it empty",
                    )
                )
    return findings


def exceptions_check(
    plugins: Iterable[Plugin], exceptions: Iterable[CredentialException]
) -> list[Finding]:
    """Check that every exception still points at a parameter that needs it.

    Args:
        plugins: The plugins in the index.
        exceptions: The entries of ``credential-exceptions.yml``.

    Returns:
        One finding per entry that names a plugin or parameter the index does
        not hold, or a parameter whose name does not read as a credential.

    Example:
        >>> plugin = Plugin("pl-a", "1.0.0", "plugins/pl-a.json", ())
        >>> stale = [CredentialException("pl-a", "splitToken", "a delimiter")]
        >>> [finding.report for finding in exceptions_check([plugin], stale)]
        ["credential-exceptions.yml: pl-a has no parameter 'splitToken'"]
    """
    parametersByPlugin: dict[str, set[str]] = {
        plugin.name: {parameter.name for parameter in plugin.parameters} for plugin in plugins
    }
    findings: list[Finding] = []
    for entry in exceptions:
        if entry.plugin not in parametersByPlugin:
            reason: str = f"no plugin named {entry.plugin!r}"
        elif entry.parameter not in parametersByPlugin[entry.plugin]:
            reason = f"{entry.plugin} has no parameter {entry.parameter!r}"
        elif not name_checkIsCredential(entry.parameter):
            reason = f"{entry.plugin} {entry.parameter!r} does not read as a credential"
        else:
            continue
        findings.append(Finding(EXCEPTIONS_PATH, reason))
    return findings
