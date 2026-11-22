"""Read the index's plugin descriptors into typed models.

A descriptor in ``plugins/`` is JSON in the form CUBE's admin upload accepts.
This module validates each file against ``schema/plugin.schema.json`` and
turns the ones that pass into ``Plugin`` models, so every other check works on
typed values and never on raw JSON. A file that fails is reported as a
``Finding`` and left out of the models.

Key components:
    - Finding: one thing wrong with the index, with the file it is in.
    - Parameter: one parameter of a plugin.
    - Plugin: one plugin descriptor.
    - PluginsLoaded: the plugins that passed the schema, and the findings.
    - document_validate: judge one parsed document against a JSON schema.
    - plugin_build: turn one validated descriptor into a ``Plugin``.
    - plugins_load: read and validate every descriptor under a root.

Typical usage:
    loaded = plugins_load(Path("."))
    for finding in loaded.findings:
        print(finding.report)

Dependencies:
    ``jsonschema`` for validation. The root is a checkout of the index: it
    holds ``plugins/`` and ``schema/plugin.schema.json``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator

PLUGINS_DIRECTORY: str = "plugins"
PLUGIN_SCHEMA_PATH: str = "schema/plugin.schema.json"
DESCRIPTOR_SUFFIX: str = ".json"


@dataclass(frozen=True)
class Finding:
    """One thing wrong with the index.

    Attributes:
        path: File the finding is in, relative to the index root.
        reason: What is wrong, phrased for the person fixing it.

    Example:
        >>> Finding("plugins/pl-a.json", "name is 'pl-b'").report
        "plugins/pl-a.json: name is 'pl-b'"
    """

    path: str
    reason: str

    @property
    def report(self) -> str:
        """One line in the ``path: reason`` form."""
        return f"{self.path}: {self.reason}"


@dataclass(frozen=True)
class Parameter:
    """One parameter of a plugin, as its descriptor declares it.

    Attributes:
        name: The parameter's name.
        type: CUBE's upload type name: ``str``, ``int``, ``float``, ``bool``,
            ``path`` or ``unextpath``.
        default: The declared default, ``None`` when there is none.

    Example:
        >>> Parameter(name="prefix", type="str", default=None).name
        'prefix'
    """

    name: str
    type: str
    default: object


@dataclass(frozen=True)
class Plugin:
    """One plugin descriptor that passed the schema.

    Attributes:
        name: The plugin's name, as its descriptor spells it.
        version: The one version the index holds.
        path: The descriptor's file, relative to the index root.
        parameters: The plugin's parameters, in descriptor order.
        type: ``ds``, ``fs`` or ``ts``. A ``ts`` plugin joins several nodes
            of a pipeline, which changes what a pipeline may say of it.

    Example:
        >>> plugin = Plugin("pl-a", "1.0.0", "plugins/pl-a.json", ())
        >>> (plugin.version, plugin.type)
        ('1.0.0', 'ds')
    """

    name: str
    version: str
    path: str
    parameters: tuple[Parameter, ...]
    type: str = "ds"


@dataclass(frozen=True)
class PluginsLoaded:
    """What reading ``plugins/`` produced.

    Attributes:
        plugins: The descriptors that passed the schema, sorted by path.
        findings: One entry per fault in a file that did not pass.

    Example:
        >>> PluginsLoaded(plugins=(), findings=()).plugins
        ()
    """

    plugins: tuple[Plugin, ...]
    findings: tuple[Finding, ...]


def document_validate(
    document: object, validator: Draft202012Validator, path: str
) -> list[Finding]:
    """Judge one parsed document against a JSON schema.

    Args:
        document: The parsed JSON or YAML value.
        validator: A validator built from the schema to hold it to.
        path: The document's file, for the findings.

    Returns:
        One finding per schema error, each naming where in the document it
        is. Empty when the document is valid.

    Example:
        >>> validator = Draft202012Validator({"type": "object", "required": ["name"]})
        >>> [finding.report for finding in document_validate({}, validator, "a.json")]
        ["a.json: $: 'name' is a required property"]
    """
    faults = validator.iter_errors(document)  # type: ignore[arg-type]  # stub's JSON type is private
    errors = sorted(faults, key=lambda error: error.json_path)
    return [Finding(path, f"{error.json_path}: {error.message}") for error in errors]


def plugin_build(descriptor: Mapping[str, object], path: str) -> Plugin:
    """Turn one validated descriptor into a ``Plugin``.

    Args:
        descriptor: A descriptor that has passed the plugin schema.
        path: The descriptor's file, relative to the index root.

    Returns:
        The plugin, with its parameters in descriptor order.

    Example:
        >>> descriptor = {
        ...     "name": "pl-a",
        ...     "version": "1.0.0",
        ...     "type": "ds",
        ...     "parameters": [{"name": "prefix", "type": "str", "default": "x"}],
        ... }
        >>> plugin_build(descriptor, "plugins/pl-a.json").parameters
        (Parameter(name='prefix', type='str', default='x'),)
    """
    rawParameters = cast("list[Mapping[str, object]]", descriptor["parameters"])
    parameters: tuple[Parameter, ...] = tuple(
        Parameter(
            name=cast("str", raw["name"]),
            type=cast("str", raw["type"]),
            default=raw.get("default"),
        )
        for raw in rawParameters
    )
    return Plugin(
        name=cast("str", descriptor["name"]),
        version=cast("str", descriptor["version"]),
        path=path,
        parameters=parameters,
        type=cast("str", descriptor["type"]),
    )


def plugins_load(root: Path) -> PluginsLoaded:
    """Read and validate every descriptor under ``plugins/``.

    Args:
        root: The index root, holding ``plugins/`` and ``schema/``.

    Returns:
        The plugins that passed the schema, and a finding for every file that
        is not JSON, is not named ``*.json``, or breaks the schema.

    Example:
        >>> loaded = plugins_load(Path("."))  # doctest: +SKIP
        >>> len(loaded.plugins)  # doctest: +SKIP
        175
    """
    schema: object = json.loads((root / PLUGIN_SCHEMA_PATH).read_text(encoding="utf-8"))
    validator = Draft202012Validator(cast("Mapping[str, object]", schema))
    plugins: list[Plugin] = []
    findings: list[Finding] = []
    for file in sorted((root / PLUGINS_DIRECTORY).iterdir()):
        path: str = file.relative_to(root).as_posix()
        if file.suffix != DESCRIPTOR_SUFFIX:
            findings.append(Finding(path, f"not a {DESCRIPTOR_SUFFIX} file"))
            continue
        try:
            descriptor: object = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            findings.append(Finding(path, f"not JSON: {error}"))
            continue
        faults: list[Finding] = document_validate(descriptor, validator, path)
        findings.extend(faults)
        if not faults:
            plugins.append(plugin_build(cast("Mapping[str, object]", descriptor), path))
    return PluginsLoaded(plugins=tuple(plugins), findings=tuple(findings))
