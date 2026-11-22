"""Check the rules the plugin schema cannot express.

The schema judges one descriptor at a time. These checks judge the set: a
descriptor's file is named for its plugin, no two plugins share a name once
case is ignored, and a plugin listed in ``excluded.yml`` is not also in
``plugins/``.

Key components:
    - fileNames_check: every descriptor's file is ``<name>.json``.
    - nameCases_check: names are unique ignoring case.
    - excludedNames_load: read the names in ``excluded.yml``.
    - excluded_check: no plugin is both indexed and excluded.

Typical usage:
    loaded = plugins_load(root)
    findings = fileNames_check(loaded.plugins) + nameCases_check(loaded.plugins)

Dependencies:
    ``pyyaml`` to read ``excluded.yml``, a list of mappings each with a
    ``name`` key.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

from checks.model import DESCRIPTOR_SUFFIX, PLUGINS_DIRECTORY, Finding, Plugin

EXCLUDED_PATH: str = "excluded.yml"


def fileNames_check(plugins: Iterable[Plugin]) -> list[Finding]:
    """Check that every descriptor's file is named for its plugin.

    Args:
        plugins: The plugins to judge.

    Returns:
        One finding per descriptor whose file is not ``plugins/<name>.json``.

    Example:
        >>> plugin = Plugin("pl-b", "1.0.0", "plugins/pl-a.json", ())
        >>> [finding.report for finding in fileNames_check([plugin])]
        ["plugins/pl-a.json: name is 'pl-b'; the file must be plugins/pl-b.json"]
    """
    findings: list[Finding] = []
    for plugin in plugins:
        expected: str = f"{PLUGINS_DIRECTORY}/{plugin.name}{DESCRIPTOR_SUFFIX}"
        if plugin.path != expected:
            findings.append(
                Finding(plugin.path, f"name is {plugin.name!r}; the file must be {expected}")
            )
    return findings


def nameCases_check(plugins: Iterable[Plugin]) -> list[Finding]:
    """Check that no two plugins share a name once case is ignored.

    Args:
        plugins: The plugins to judge.

    Returns:
        One finding per plugin whose name, lowercased, an earlier plugin
        already holds.

    Example:
        >>> first = Plugin("pl-tagSub", "1.0.0", "plugins/pl-tagSub.json", ())
        >>> second = Plugin("pl-tagsub", "1.0.0", "plugins/pl-tagsub.json", ())
        >>> [finding.report for finding in nameCases_check([first, second])]
        ["plugins/pl-tagsub.json: name differs only by case from 'pl-tagSub'"]
    """
    findings: list[Finding] = []
    seen: dict[str, str] = {}
    for plugin in plugins:
        folded: str = plugin.name.lower()
        if folded in seen:
            findings.append(
                Finding(plugin.path, f"name differs only by case from {seen[folded]!r}")
            )
        else:
            seen[folded] = plugin.name
    return findings


def excludedNames_load(root: Path) -> list[str]:
    """Read the names of the plugins ``excluded.yml`` lists.

    Args:
        root: The index root, holding ``excluded.yml``.

    Returns:
        The excluded names, in file order. Entries without a ``name`` are
        skipped.

    Example:
        >>> excludedNames_load(Path("."))[:2]  # doctest: +SKIP
        ['pl-antsreg', 'pl-dicomtag']
    """
    entries: object = yaml.safe_load((root / EXCLUDED_PATH).read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        return []
    return [
        entry["name"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    ]


def excluded_check(plugins: Iterable[Plugin], excludedNames: Iterable[str]) -> list[Finding]:
    """Check that no plugin is both indexed and excluded.

    Args:
        plugins: The plugins in ``plugins/``.
        excludedNames: The names ``excluded.yml`` lists.

    Returns:
        One finding per excluded name that, ignoring case, is also a plugin.

    Example:
        >>> plugin = Plugin("pl-a", "1.0.0", "plugins/pl-a.json", ())
        >>> [finding.report for finding in excluded_check([plugin], ["pl-A"])]
        ["excluded.yml: 'pl-A' is excluded and also in plugins/pl-a.json"]
    """
    pathsByName: dict[str, str] = {plugin.name.lower(): plugin.path for plugin in plugins}
    return [
        Finding(EXCLUDED_PATH, f"{name!r} is excluded and also in {pathsByName[name.lower()]}")
        for name in excludedNames
        if name.lower() in pathsByName
    ]
