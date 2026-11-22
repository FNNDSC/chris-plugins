"""Check ``shelves.yml``, which says what each app is for.

A shelf groups apps by purpose: models, conversion, de-identification. The
descriptors cannot carry this, because their schema is CUBE's and closed, so
it is held in one file beside them. These checks keep that file true to the
index: every app a shelf names is a plugin in ``plugins/``, spelled as its
file is, and no two shelves share a name.

Key components:
    - Shelf: one shelf and the apps on it.
    - ShelvesLoaded: the shelves read, and the faults in the file.
    - shelves_load: read and validate ``shelves.yml``.
    - shelfNames_check: shelf names are unique ignoring case.
    - shelfApps_check: every app on a shelf is in the index.

Typical usage:
    loaded = shelves_load(root)
    findings = shelfNames_check(loaded.shelves)
    findings += shelfApps_check(loaded.shelves, plugins)

Dependencies:
    ``pyyaml`` and ``jsonschema``. ``shelves.yml`` is a list of ``shelf``,
    ``says``, ``apps`` entries, held to ``schema/shelves.schema.json``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml
from jsonschema import Draft202012Validator

from checks.model import Finding, Plugin, document_validate

SHELVES_PATH: str = "shelves.yml"
SHELVES_SCHEMA_PATH: str = "schema/shelves.schema.json"


@dataclass(frozen=True)
class Shelf:
    """One shelf and the apps that stand on it.

    Attributes:
        name: The shelf's name.
        says: One sentence that is true of everything on the shelf.
        apps: The names of the plugins on it, in file order.

    Example:
        >>> Shelf("Models", "Apps that run a trained model.", ("pl-lld",)).apps
        ('pl-lld',)
    """

    name: str
    says: str
    apps: tuple[str, ...]


@dataclass(frozen=True)
class ShelvesLoaded:
    """What reading ``shelves.yml`` produced.

    Attributes:
        shelves: The shelves, in file order. Empty if the file is invalid.
        findings: One entry per fault in the file.

    Example:
        >>> ShelvesLoaded(shelves=(), findings=()).shelves
        ()
    """

    shelves: tuple[Shelf, ...]
    findings: tuple[Finding, ...]


def shelves_load(root: Path) -> ShelvesLoaded:
    """Read and validate ``shelves.yml``.

    Args:
        root: The index root, holding the file and its schema.

    Returns:
        The shelves, and a finding per schema error. An invalid file yields
        no shelves.

    Example:
        >>> loaded = shelves_load(Path("."))  # doctest: +SKIP
        >>> loaded.shelves[0].name  # doctest: +SKIP
        'Models'
    """
    schema: object = json.loads((root / SHELVES_SCHEMA_PATH).read_text(encoding="utf-8"))
    validator = Draft202012Validator(cast("Mapping[str, object]", schema))
    document: object = yaml.safe_load((root / SHELVES_PATH).read_text(encoding="utf-8"))
    findings: list[Finding] = document_validate(document, validator, SHELVES_PATH)
    if findings:
        return ShelvesLoaded(shelves=(), findings=tuple(findings))
    entries = cast("list[Mapping[str, object]]", document)
    shelves: tuple[Shelf, ...] = tuple(
        Shelf(
            name=cast("str", entry["shelf"]),
            says=cast("str", entry["says"]),
            apps=tuple(cast("list[str]", entry["apps"])),
        )
        for entry in entries
    )
    return ShelvesLoaded(shelves=shelves, findings=())


def shelfNames_check(shelves: Iterable[Shelf]) -> list[Finding]:
    """Check that no two shelves share a name once case is ignored.

    Args:
        shelves: The shelves to judge.

    Returns:
        One finding per shelf whose name, lowercased, an earlier shelf holds.

    Example:
        >>> shelves = [Shelf("Models", "a", ()), Shelf("models", "b", ())]
        >>> [finding.report for finding in shelfNames_check(shelves)]
        ["shelves.yml: shelf 'models' is named twice"]
    """
    findings: list[Finding] = []
    seen: set[str] = set()
    for shelf in shelves:
        folded: str = shelf.name.lower()
        if folded in seen:
            findings.append(Finding(SHELVES_PATH, f"shelf {shelf.name!r} is named twice"))
        seen.add(folded)
    return findings


def shelfApps_check(shelves: Iterable[Shelf], plugins: Iterable[Plugin]) -> list[Finding]:
    """Check that every app on a shelf is a plugin in the index.

    Args:
        shelves: The shelves to judge.
        plugins: The plugins in ``plugins/``.

    Returns:
        One finding per app that is not a plugin's name, with the right
        spelling when only the case differs.

    Example:
        >>> plugin = Plugin("pl-tagSub", "1.0.0", "plugins/pl-tagSub.json", ())
        >>> shelf = Shelf("Tags", "Apps that edit tags.", ("pl-tagsub", "pl-gone"))
        >>> for finding in shelfApps_check([shelf], [plugin]):
        ...     print(finding.reason)
        shelf 'Tags': 'pl-tagsub' is spelled 'pl-tagSub' in plugins/
        shelf 'Tags': 'pl-gone' is not in plugins/
    """
    namesByFolded: dict[str, str] = {plugin.name.lower(): plugin.name for plugin in plugins}
    names: set[str] = set(namesByFolded.values())
    findings: list[Finding] = []
    for shelf in shelves:
        for app in shelf.apps:
            if app in names:
                continue
            spelling: str | None = namesByFolded.get(app.lower())
            fault: str = (
                f"is spelled {spelling!r} in plugins/" if spelling else "is not in plugins/"
            )
            findings.append(Finding(SHELVES_PATH, f"shelf {shelf.name!r}: {app!r} {fault}"))
    return findings
