"""Check the pipelines against the plugins they are made of.

A pipeline in ``pipelines/`` is a tree of plugins, each named with a version
and a set of parameter values. CUBE checks a pipeline only against what one
CUBE happens to hold, and ignores a value set on a parameter the plugin does
not have. These checks hold every pipeline to the index itself: each node
names a plugin in ``plugins/`` at the version held there, sets only
parameters that plugin has, with values of their declared type, and leaves
no parameter without a value that CUBE would refuse to register.

A value a pipeline cannot know (a credential, a host, a PACS name) is never
written. The parameter holds the sentinel ``__SUPPLY__`` and the file's
``needs`` block names it; the two are held together here.

Key components:
    - Node: one plugin in a pipeline's tree.
    - Need: one value whoever runs the pipeline must supply.
    - Pipeline: one pipeline file that passed the schema.
    - PipelinesLoaded: the pipelines read, and the faults in the files.
    - pipelines_load: read and validate every file under ``pipelines/``.
    - pipelineNames_check: plain file names, and names unique ignoring case.
    - tree_check: titles, the root, and that every node hangs off it.
    - nodePlugins_check: every node names an indexed plugin and version.
    - nodeParameters_check: every value fits a parameter the plugin has.
    - joins_check: a ``ts`` node names the nodes it joins.
    - needs_check: every sentinel is declared and every declaration is one.
    - nodeCredentials_check: no credential is written into a pipeline.
    - excludedSources_check: nothing is both excluded and held.
    - pipelines_check: all of the above, over every pipeline.

Typical usage:
    loaded = pipelines_load(root)
    findings = pipelines_check(loaded.pipelines, plugins, exceptions)

Dependencies:
    ``pyyaml`` and ``jsonschema``. A pipeline file is YAML in the form CUBE's
    pipeline source upload takes, held to ``schema/pipeline.schema.json``.
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml
from jsonschema import Draft202012Validator

from checks.credentials import CredentialException, name_checkIsCredential
from checks.model import Finding, Parameter, Plugin, document_validate

PIPELINES_DIRECTORY: str = "pipelines"
PIPELINE_SCHEMA_PATH: str = "schema/pipeline.schema.json"
PIPELINE_SUFFIX: str = ".yml"
EXCLUDED_PATH: str = "pipelines-excluded.yml"
EXCLUDED_SCHEMA_PATH: str = "schema/pipelines-excluded.schema.json"
SENTINEL: str = "__SUPPLY__"
JOIN_TYPE: str = "ts"
JOIN_PARAMETER: str = "plugininstances"
VALUE_LENGTH_LIMIT: int = 600
FILE_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class Node:
    """One plugin in a pipeline's tree.

    Attributes:
        title: The node's title, unique within its pipeline.
        pluginName: The plugin's name, as the pipeline spells it.
        pluginVersion: The version the pipeline names.
        previous: The title of the node this one follows, ``None`` for the
            root.
        values: The parameter values the node sets, by parameter name.

    Example:
        >>> Node("root", "pl-a", "1.0.0", None, {"prefix": "x"}).values
        {'prefix': 'x'}
    """

    title: str
    pluginName: str
    pluginVersion: str
    previous: str | None
    values: Mapping[str, object]


@dataclass(frozen=True)
class Need:
    """One value whoever runs the pipeline must supply.

    Attributes:
        node: The title of the node that takes the value.
        parameter: The parameter that takes it.
        kind: ``secret`` for a credential, ``site`` for a value that belongs
            to one site.

    Example:
        >>> Need("push", "password", "secret").kind
        'secret'
    """

    node: str
    parameter: str
    kind: str


@dataclass(frozen=True)
class Pipeline:
    """One pipeline file that passed the schema.

    Attributes:
        name: The pipeline's name.
        path: The pipeline's file, relative to the index root.
        nodes: The tree's nodes, in file order.
        needs: What must be supplied to run it.

    Example:
        >>> root = Node("root", "pl-a", "1.0.0", None, {})
        >>> Pipeline("Demo", "pipelines/Demo.yml", (root,), ()).nodes[0].title
        'root'
    """

    name: str
    path: str
    nodes: tuple[Node, ...]
    needs: tuple[Need, ...]


@dataclass(frozen=True)
class PipelinesLoaded:
    """What reading ``pipelines/`` produced.

    Attributes:
        pipelines: The files that passed the schema, sorted by path.
        findings: One entry per fault in a file that did not pass.

    Example:
        >>> PipelinesLoaded(pipelines=(), findings=()).pipelines
        ()
    """

    pipelines: tuple[Pipeline, ...]
    findings: tuple[Finding, ...]


def node_build(raw: Mapping[str, object]) -> Node:
    """Turn one validated tree node into a ``Node``.

    The plugin string is split as CUBE splits it: the name is the first word
    and the version is the last, without its leading ``v``.

    Args:
        raw: A node that has passed the pipeline schema.

    Returns:
        The node, with an empty mapping when it sets no values.

    Example:
        >>> node = node_build({"title": "root", "plugin": "pl-a v1.0.0", "previous": None})
        >>> (node.pluginName, node.pluginVersion, node.previous)
        ('pl-a', '1.0.0', None)
    """
    words: list[str] = cast("str", raw["plugin"]).split(" ")
    values = cast("Mapping[str, object]", raw.get("plugin_parameter_defaults", {}))
    return Node(
        title=cast("str", raw["title"]),
        pluginName=words[0],
        pluginVersion=words[-1][1:],
        previous=cast("str | None", raw["previous"]),
        values=dict(values),
    )


def pipeline_build(document: Mapping[str, object], path: str) -> Pipeline:
    """Turn one validated pipeline document into a ``Pipeline``.

    Args:
        document: A pipeline that has passed the schema.
        path: The pipeline's file, relative to the index root.

    Returns:
        The pipeline, with no needs when the file declares none.

    Example:
        >>> document = {
        ...     "name": "Demo",
        ...     "plugin_tree": [{"title": "root", "plugin": "pl-a v1.0.0", "previous": None}],
        ...     "needs": [{"node": "root", "parameter": "password", "kind": "secret"}],
        ... }
        >>> pipeline_build(document, "pipelines/Demo.yml").needs
        (Need(node='root', parameter='password', kind='secret'),)
    """
    rawNodes = cast("list[Mapping[str, object]]", document["plugin_tree"])
    rawNeeds = cast("list[Mapping[str, str]]", document.get("needs", []))
    return Pipeline(
        name=cast("str", document["name"]),
        path=path,
        nodes=tuple(node_build(raw) for raw in rawNodes),
        needs=tuple(Need(raw["node"], raw["parameter"], raw["kind"]) for raw in rawNeeds),
    )


def dates_render(value: object) -> object:
    """Render the dates YAML parsed back into the text that was written.

    YAML reads an unquoted ``2026-11-22`` as a date. The schema describes the
    file as text, so dates are put back before it is applied.

    Args:
        value: A parsed YAML value of any shape.

    Returns:
        The same value, with every date replaced by its ISO text.

    Example:
        >>> dates_render({"run": {"date": datetime.date(2026, 11, 22)}})
        {'run': {'date': '2026-11-22'}}
    """
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: dates_render(item) for key, item in value.items()}
    if isinstance(value, list):
        return [dates_render(item) for item in value]
    return value


def pipelines_load(root: Path) -> PipelinesLoaded:
    """Read and validate every file under ``pipelines/``.

    Args:
        root: The index root, holding ``pipelines/`` and ``schema/``.

    Returns:
        The pipelines that passed the schema, and a finding for every file
        that is not YAML, is not named ``*.yml``, or breaks the schema.
        Nothing at all when there is no ``pipelines/``.

    Example:
        >>> loaded = pipelines_load(Path("."))  # doctest: +SKIP
        >>> loaded.findings  # doctest: +SKIP
        ()
    """
    directory: Path = root / PIPELINES_DIRECTORY
    if not directory.is_dir():
        return PipelinesLoaded(pipelines=(), findings=())
    schema: object = json.loads((root / PIPELINE_SCHEMA_PATH).read_text(encoding="utf-8"))
    validator = Draft202012Validator(cast("Mapping[str, object]", schema))
    pipelines: list[Pipeline] = []
    findings: list[Finding] = []
    for file in sorted(directory.iterdir()):
        path: str = file.relative_to(root).as_posix()
        if file.suffix != PIPELINE_SUFFIX:
            findings.append(Finding(path, f"not a {PIPELINE_SUFFIX} file"))
            continue
        try:
            document: object = dates_render(yaml.safe_load(file.read_text(encoding="utf-8")))
        except yaml.YAMLError as error:
            findings.append(Finding(path, f"not YAML: {error}"))
            continue
        faults: list[Finding] = document_validate(document, validator, path)
        findings.extend(faults)
        if not faults:
            pipelines.append(pipeline_build(cast("Mapping[str, object]", document), path))
    return PipelinesLoaded(pipelines=tuple(pipelines), findings=tuple(findings))


def pipelineNames_check(pipelines: Iterable[Pipeline]) -> list[Finding]:
    """Check that file names are plain and that names are unique.

    A pipeline's name is free text for a reader ("NIfTI --> FreeSurfer"),
    and some of what it holds cannot be in a file name on every system. So a
    file is not named for its pipeline, as a plugin's is: it has a plain
    name of its own, and both are unique ignoring case.

    Args:
        pipelines: The pipelines to judge.

    Returns:
        One finding per file whose name holds anything but letters, digits,
        ``.``, ``_`` and ``-``, one per file name that differs from an
        earlier one only by case, and one per pipeline name that does.

    Example:
        >>> root = Node("root", "pl-a", "1.0.0", None, {})
        >>> pipelines = [
        ...     Pipeline("Demo v1", "pipelines/demo.yml", (root,), ()),
        ...     Pipeline("demo V1", "pipelines/Demo.yml", (root,), ()),
        ...     Pipeline("Other", "pipelines/an other.yml", (root,), ()),
        ... ]
        >>> for finding in pipelineNames_check(pipelines):
        ...     print(finding.report)
        pipelines/Demo.yml: file name differs only by case from pipelines/demo.yml
        pipelines/Demo.yml: name 'demo V1' differs only by case from 'Demo v1'
        pipelines/an other.yml: a file name holds only letters, digits, '.', '_' and '-'
    """
    findings: list[Finding] = []
    seenPaths: dict[str, str] = {}
    seenNames: dict[str, str] = {}
    for pipeline in pipelines:
        if not FILE_NAME_PATTERN.match(Path(pipeline.path).name):
            findings.append(
                Finding(pipeline.path, "a file name holds only letters, digits, '.', '_' and '-'")
            )
        foldedPath: str = pipeline.path.lower()
        if foldedPath in seenPaths:
            findings.append(
                Finding(
                    pipeline.path, f"file name differs only by case from {seenPaths[foldedPath]}"
                )
            )
        seenPaths.setdefault(foldedPath, pipeline.path)
        foldedName: str = pipeline.name.lower()
        if foldedName in seenNames:
            findings.append(
                Finding(
                    pipeline.path,
                    f"name {pipeline.name!r} differs only by case from {seenNames[foldedName]!r}",
                )
            )
        seenNames.setdefault(foldedName, pipeline.name)
    return findings


def tree_check(pipeline: Pipeline) -> list[Finding]:
    """Check a pipeline's tree: titles, the root, and what hangs off it.

    Args:
        pipeline: The pipeline to judge.

    Returns:
        A finding for each repeated title, each ``previous`` that names no
        node, a tree without exactly one root, and each node that cannot be
        reached from the root (which is what a cycle leaves behind).

    Example:
        >>> nodes = (
        ...     Node("root", "pl-a", "1.0.0", None, {}),
        ...     Node("left", "pl-a", "1.0.0", "rooot", {}),
        ... )
        >>> [finding.reason for finding in tree_check(Pipeline("Demo", "p.yml", nodes, ()))]
        ["node 'left': previous 'rooot' is not a node's title"]
    """
    findings: list[Finding] = []
    titles: list[str] = [node.title for node in pipeline.nodes]
    for title in sorted({title for title in titles if titles.count(title) > 1}):
        findings.append(Finding(pipeline.path, f"title {title!r} is used more than once"))
    roots: list[str] = [node.title for node in pipeline.nodes if node.previous is None]
    if len(roots) != 1:
        findings.append(
            Finding(pipeline.path, f"a tree has one root; this has {len(roots)}: {roots}")
        )
    for node in pipeline.nodes:
        if node.previous is not None and node.previous not in titles:
            findings.append(
                Finding(
                    pipeline.path,
                    f"node {node.title!r}: previous {node.previous!r} is not a node's title",
                )
            )
    if not findings:
        reached: set[str] = titlesFromRoot_collect(pipeline)
        for title in titles:
            if title not in reached:
                findings.append(
                    Finding(pipeline.path, f"node {title!r} cannot be reached from the root")
                )
    return findings


def titlesFromRoot_collect(pipeline: Pipeline) -> set[str]:
    """Collect the titles of the nodes that hang off the root.

    Args:
        pipeline: A pipeline with exactly one root and unique titles.

    Returns:
        The root's title and that of every node that follows it, directly or
        through others.

    Example:
        >>> nodes = (
        ...     Node("root", "pl-a", "1.0.0", None, {}),
        ...     Node("leaf", "pl-a", "1.0.0", "root", {}),
        ...     Node("loop", "pl-a", "1.0.0", "loop", {}),
        ... )
        >>> sorted(titlesFromRoot_collect(Pipeline("Demo", "p.yml", nodes, ())))
        ['leaf', 'root']
    """
    reached: set[str] = {node.title for node in pipeline.nodes if node.previous is None}
    grew: bool = True
    while grew:
        grew = False
        for node in pipeline.nodes:
            if node.title not in reached and node.previous in reached:
                reached.add(node.title)
                grew = True
    return reached


def nodePlugins_check(pipeline: Pipeline, plugins: Mapping[str, Plugin]) -> list[Finding]:
    """Check that every node names an indexed plugin at the indexed version.

    Args:
        pipeline: The pipeline to judge.
        plugins: The plugins in ``plugins/``, by name.

    Returns:
        A finding for each node whose plugin is not in the index, is spelled
        in another case, or is named at another version.

    Example:
        >>> plugins = {"pl-tagSub": Plugin("pl-tagSub", "3.3.5", "plugins/pl-tagSub.json", ())}
        >>> nodes = (
        ...     Node("root", "pl-tagSub", "3.2.4", None, {}),
        ...     Node("leaf", "pl-tagsub", "3.3.5", "root", {}),
        ... )
        >>> for finding in nodePlugins_check(Pipeline("Demo", "p.yml", nodes, ()), plugins):
        ...     print(finding.reason)
        node 'root': pl-tagSub is at v3.3.5 in plugins/, not v3.2.4
        node 'leaf': 'pl-tagsub' is spelled 'pl-tagSub' in plugins/
    """
    namesByFolded: dict[str, str] = {name.lower(): name for name in plugins}
    findings: list[Finding] = []
    for node in pipeline.nodes:
        plugin: Plugin | None = plugins.get(node.pluginName)
        spelling: str | None = namesByFolded.get(node.pluginName.lower())
        if plugin is not None:
            if plugin.version == node.pluginVersion:
                continue
            fault: str = (
                f"{plugin.name} is at v{plugin.version} in plugins/, not v{node.pluginVersion}"
            )
        elif spelling is not None:
            fault = f"{node.pluginName!r} is spelled {spelling!r} in plugins/"
        else:
            fault = f"{node.pluginName!r} is not in plugins/"
        findings.append(Finding(pipeline.path, f"node {node.title!r}: {fault}"))
    return findings


def value_checkFitsType(value: object, typeName: str) -> bool:
    """Say whether a value is of a parameter's declared type.

    Args:
        value: The value a node sets.
        typeName: CUBE's upload type name for the parameter.

    Returns:
        ``True`` for a boolean on ``bool``, a whole number on ``int``, any
        number on ``float``, and text on ``str``, ``path`` and ``unextpath``.
        A boolean is not a number, and a quoted number is text.

    Example:
        >>> [value_checkFitsType(value, "int") for value in (2, "2", True)]
        [True, False, False]
        >>> value_checkFitsType("2", "str")
        True
    """
    match typeName:
        case "bool":
            return isinstance(value, bool)
        case "int":
            return isinstance(value, int) and not isinstance(value, bool)
        case "float":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        case _:
            return isinstance(value, str)


def nodeParameters_check(pipeline: Pipeline, plugins: Mapping[str, Plugin]) -> list[Finding]:
    """Check every value a node sets, and every value it must set.

    CUBE drops a value set on a parameter the plugin does not have, so a
    pipeline can lose a setting without anyone being told; here that is a
    finding. CUBE refuses a pipeline that leaves a parameter with no default
    unset, so that is a finding too.

    Args:
        pipeline: The pipeline to judge.
        plugins: The plugins in ``plugins/``, by name.

    Returns:
        A finding for each value set on a parameter the plugin lacks, each
        value of the wrong type or longer than CUBE stores, and each
        parameter without a default that the node does not set. Nodes whose
        plugin is not in the index are skipped; ``nodePlugins_check`` reports
        them.

    Example:
        >>> parameters = (Parameter("threads", "int", 1), Parameter("exec", "str", None))
        >>> plugins = {"pl-a": Plugin("pl-a", "1.0.0", "plugins/pl-a.json", parameters)}
        >>> node = Node("root", "pl-a", "1.0.0", None, {"threads": "2", "gone": "x"})
        >>> for finding in nodeParameters_check(Pipeline("Demo", "p.yml", (node,), ()), plugins):
        ...     print(finding.reason)
        node 'root': 'threads' is of type int; '2' is not
        node 'root': pl-a has no parameter 'gone'
        node 'root': 'exec' has no default in pl-a, so the node must set it
    """
    findings: list[Finding] = []
    for node in pipeline.nodes:
        plugin: Plugin | None = plugins.get(node.pluginName)
        if plugin is None:
            continue
        parameters: dict[str, Parameter] = {
            parameter.name: parameter for parameter in plugin.parameters
        }
        faults: list[str] = []
        for name, value in node.values.items():
            if name not in parameters:
                faults.append(f"{plugin.name} has no parameter {name!r}")
            elif not value_checkFitsType(value, parameters[name].type):
                faults.append(f"{name!r} is of type {parameters[name].type}; {value!r} is not")
            elif isinstance(value, str) and len(value) > VALUE_LENGTH_LIMIT:
                faults.append(f"{name!r} is longer than {VALUE_LENGTH_LIMIT} characters")
        for parameter in plugin.parameters:
            if parameter.default is None and parameter.name not in node.values:
                faults.append(
                    f"{parameter.name!r} has no default in {plugin.name}, so the node must set it"
                )
        findings.extend(Finding(pipeline.path, f"node {node.title!r}: {fault}") for fault in faults)
    return findings


def joins_check(pipeline: Pipeline, plugins: Mapping[str, Plugin]) -> list[Finding]:
    """Check that every ``ts`` node names the nodes it joins.

    A ``ts`` plugin takes the titles of the nodes it joins, separated by
    commas, in ``plugininstances``. CUBE requires that list to hold existing
    titles, no title twice, and the node's own ``previous``.

    Args:
        pipeline: The pipeline to judge.
        plugins: The plugins in ``plugins/``, by name.

    Returns:
        A finding for each ``ts`` node whose list is missing, repeats a
        title, names a title the tree does not have, or leaves out its
        ``previous``.

    Example:
        >>> plugins = {"pl-join": Plugin("pl-join", "1.0.0", "p.json", (), type="ts")}
        >>> nodes = (
        ...     Node("root", "pl-a", "1.0.0", None, {}),
        ...     Node("join", "pl-join", "1.0.0", "root", {"plugininstances": "leaf"}),
        ... )
        >>> for finding in joins_check(Pipeline("Demo", "p.yml", nodes, ()), plugins):
        ...     print(finding.reason)
        node 'join': plugininstances names 'leaf', which is not a node's title
        node 'join': plugininstances must include its previous, 'root'
    """
    titles: set[str] = {node.title for node in pipeline.nodes}
    findings: list[Finding] = []
    for node in pipeline.nodes:
        plugin: Plugin | None = plugins.get(node.pluginName)
        if plugin is None or plugin.type != JOIN_TYPE or node.previous is None:
            continue
        value: object = node.values.get(JOIN_PARAMETER, "")
        joined: list[str] = value.split(",") if isinstance(value, str) and value else []
        faults: list[str] = []
        if len(joined) > len(set(joined)):
            faults.append(f"{JOIN_PARAMETER} names a title twice")
        faults.extend(
            f"{JOIN_PARAMETER} names {title!r}, which is not a node's title"
            for title in joined
            if title not in titles
        )
        if node.previous not in joined:
            faults.append(f"{JOIN_PARAMETER} must include its previous, {node.previous!r}")
        findings.extend(Finding(pipeline.path, f"node {node.title!r}: {fault}") for fault in faults)
    return findings


def needs_check(pipeline: Pipeline) -> list[Finding]:
    """Check that sentinels and the ``needs`` block say the same thing.

    Args:
        pipeline: The pipeline to judge.

    Returns:
        A finding for each parameter set to ``__SUPPLY__`` that ``needs``
        does not name, each ``needs`` entry that points at no such
        parameter, and each entry given twice.

    Example:
        >>> node = Node("push", "pl-a", "1.0.0", None, {"password": "__SUPPLY__", "url": "x"})
        >>> needs = (Need("push", "url", "site"),)
        >>> for finding in needs_check(Pipeline("Demo", "p.yml", (node,), needs)):
        ...     print(finding.reason)
        node 'push': 'password' is __SUPPLY__ but needs does not name it
        needs: 'url' on node 'push' is not set to __SUPPLY__
    """
    supplied: set[tuple[str, str]] = {
        (node.title, name)
        for node in pipeline.nodes
        for name, value in node.values.items()
        if value == SENTINEL
    }
    declared: list[tuple[str, str]] = [(need.node, need.parameter) for need in pipeline.needs]
    findings: list[Finding] = [
        Finding(pipeline.path, f"node {title!r}: {name!r} is {SENTINEL} but needs does not name it")
        for title, name in sorted(supplied - set(declared))
    ]
    for title, name in sorted(set(declared)):
        if (title, name) not in supplied:
            findings.append(
                Finding(
                    pipeline.path, f"needs: {name!r} on node {title!r} is not set to {SENTINEL}"
                )
            )
        if declared.count((title, name)) > 1:
            findings.append(
                Finding(pipeline.path, f"needs: {name!r} on node {title!r} is named twice")
            )
    return findings


def nodeCredentials_check(
    pipeline: Pipeline, exceptions: Iterable[CredentialException]
) -> list[Finding]:
    """Check that no credential is written into a pipeline.

    Args:
        pipeline: The pipeline to judge.
        exceptions: The parameters whose name reads as a credential but
            whose value is not one.

    Returns:
        A finding for each parameter whose name reads as a credential and
        whose value is anything but ``__SUPPLY__``. The finding does not
        repeat the value.

    Example:
        >>> node = Node("push", "pl-a", "1.0.0", None, {"password": "hunter2"})
        >>> pipeline = Pipeline("Demo", "p.yml", (node,), ())
        >>> [finding.reason for finding in nodeCredentials_check(pipeline, [])]
        ["node 'push': 'password' reads as a credential; set it to __SUPPLY__ and name it in needs"]
    """
    excused: set[tuple[str, str]] = {(entry.plugin, entry.parameter) for entry in exceptions}
    findings: list[Finding] = []
    for node in pipeline.nodes:
        for name, value in node.values.items():
            if (node.pluginName, name) in excused or not name_checkIsCredential(name):
                continue
            if value != SENTINEL:
                findings.append(
                    Finding(
                        pipeline.path,
                        f"node {node.title!r}: {name!r} reads as a credential; "
                        f"set it to {SENTINEL} and name it in needs",
                    )
                )
    return findings


def excludedSources_check(root: Path) -> list[Finding]:
    """Check ``pipelines-excluded.yml`` against its schema and ``pipelines/``.

    Args:
        root: The index root, holding the file and its schema.

    Returns:
        A finding per schema error, and one per excluded file whose name,
        ignoring case, is also a file in ``pipelines/``. Nothing when the
        file does not exist.

    Example:
        >>> excludedSources_check(Path("."))  # doctest: +SKIP
        []
    """
    file: Path = root / EXCLUDED_PATH
    if not file.is_file():
        return []
    schema: object = json.loads((root / EXCLUDED_SCHEMA_PATH).read_text(encoding="utf-8"))
    validator = Draft202012Validator(cast("Mapping[str, object]", schema))
    document: object = yaml.safe_load(file.read_text(encoding="utf-8"))
    findings: list[Finding] = document_validate(document, validator, EXCLUDED_PATH)
    if findings:
        return findings
    directory: Path = root / PIPELINES_DIRECTORY
    held: set[str] = (
        {held.name.lower() for held in directory.iterdir()} if directory.is_dir() else set()
    )
    return [
        Finding(
            EXCLUDED_PATH, f"{entry['source']!r} is excluded and also in {PIPELINES_DIRECTORY}/"
        )
        for entry in cast("list[Mapping[str, str]]", document)
        if entry["source"].lower() in held
    ]


def pipelines_check(
    pipelines: Iterable[Pipeline],
    plugins: Iterable[Plugin],
    exceptions: Iterable[CredentialException],
) -> list[Finding]:
    """Run every pipeline check over every pipeline.

    Args:
        pipelines: The pipelines that passed the schema.
        plugins: The plugins in ``plugins/``.
        exceptions: The credential exceptions.

    Returns:
        Every finding, the checks of names first and then pipeline by
        pipeline.

    Example:
        >>> node = Node("root", "pl-gone", "1.0.0", None, {})
        >>> pipeline = Pipeline("Demo", "pipelines/Demo.yml", (node,), ())
        >>> [finding.reason for finding in pipelines_check([pipeline], [], [])]
        ["node 'root': 'pl-gone' is not in plugins/"]
    """
    held: tuple[Pipeline, ...] = tuple(pipelines)
    pluginsByName: dict[str, Plugin] = {plugin.name: plugin for plugin in plugins}
    excused: tuple[CredentialException, ...] = tuple(exceptions)
    findings: list[Finding] = pipelineNames_check(held)
    for pipeline in held:
        findings.extend(tree_check(pipeline))
        findings.extend(nodePlugins_check(pipeline, pluginsByName))
        findings.extend(nodeParameters_check(pipeline, pluginsByName))
        findings.extend(joins_check(pipeline, pluginsByName))
        findings.extend(needs_check(pipeline))
        findings.extend(nodeCredentials_check(pipeline, excused))
    return findings
