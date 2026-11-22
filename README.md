# chris-plugins

The index of [ChRIS](https://chrisproject.org) plugins, and of the pipelines made of them: one descriptor per plugin, at its latest version, in the form a CUBE's admin API accepts, and one file per pipeline, naming those versions. Any CUBE can be filled from it: the public store at `cube.chrisproject.org`, a development stack, miniChRIS, an institutional deployment.

## Why this exists

The list of ChRIS plugins used to live only inside a running store. When the store at `cube.chrisproject.org` went down in October 2026, the list went with it, and every tool that registers plugins by name (chrisomatic, miniChRIS, `plugin add` in mise) stopped working on a fresh CUBE. This repository keeps the list where no single server owns it. A store is a published view of this index, and rebuilding one is routine.

Background and plan: [HARBOR-Medical-AI/HARBOR-planning#183](https://github.com/HARBOR-Medical-AI/HARBOR-planning/issues/183).

## Layout

```
plugins/<name>.json         one file per plugin: its full descriptor, latest version
excluded.yml                plugins deliberately left out, with the reason
pipelines/<file>.yml        one file per pipeline, made of the plugins above
pipelines-excluded.yml      pipelines deliberately left out, with the reason
shelves.yml                 which apps stand on which shelf: models, conversion, ...
credential-exceptions.yml   parameters named like a credential that are not one
schema/                     what each of these files may contain
checks/                     the checks every pull request must pass
docs/                       notes on decisions and their consequences
```

## A descriptor

A file in `plugins/` is exactly what CUBE's admin upload takes as its `fname` file, and what a plugin's own `chris_plugin_info` prints, with no wrapper.

- **The file name is the plugin name**, so the index holds one version per plugin: the newest with a published image, whether or not it works ([why, and what is known broken](docs/latest-versions.md)). Bumping a plugin is a one-file change: the version, the image tag and any parameter changes show in the diff.
- **Names are unique ignoring case**, and spelled as the plugin's GitHub repository spells them. Some plugins were registered under more than one casing over the years (`pl-pfdicom_tagextract` and `pl-pfdicom_tagExtract`); CUBE treats those as different plugins, and two such files cannot coexist on a case-insensitive filesystem.
- **Required:** `name`, `version`, `dock_image`, `type`, `execshell`, `selfpath`, `selfexec`, `parameters`.
- **`dock_image` must be publicly pullable.** A plugin whose image lives only in a private registry does not belong here.
- **Parameter types are CUBE's upload names:** `str`, `int`, `float`, `bool`, `path`, `unextpath`. A CUBE's read API shows them as `string`, `integer` and `boolean`; the upload rejects those.
- **Resource limits are written as in Kubernetes:** CPU as `1000m`, memory as `512Mi` or `2Gi`. A limit equal to CUBE's default is left out.
- **No credential is held here.** A parameter whose name contains `password`, `token`, `secret` or `key` has an empty default, even where the plugin's own `chris_plugin_info` prints one: the index is public, and a default is registered with every CUBE filled from it. Whoever runs the plugin supplies the value. A parameter so named that is not a credential (`splitToken`, a delimiter) is listed in `credential-exceptions.yml` with the reason.

## A pipeline

A file in `pipelines/` is YAML in the form CUBE's pipeline source upload takes, with two keys CUBE does not know, `run` and `needs`.

```yaml
name: "Varus Valgus Full Workflow v20251009"
authors: ...
category: Imaging
description: ...
locked: false
run: never
needs:
  - node: DICOM-to-PACS-9
    parameter: host
    kind: site
plugin_tree:
  - title: root-0
    plugin: pl-simpledsapp v2.1.5
    previous: ~
  - title: DICOM-to-PACS-9
    plugin: pl-dicom_dirsend v1.2.1
    previous: image-to-DICOM-8
    plugin_parameter_defaults:
      host: __SUPPLY__
```

- **Every node names a plugin in `plugins/`, at the version held there,** spelled as its file is. A pipeline moves with the index: a pull request that bumps a plugin leaves each pipeline that uses it valid, or fixes it in the same change.
- **Every value a node sets is for a parameter that plugin has,** and of its declared type: a number for `int` and `float`, `true` or `false` for `bool`, quoted text for the rest. CUBE silently drops a value for a parameter it does not find; the check here does not.
- **Every parameter the plugin gives no default is set by the node.** CUBE refuses a pipeline that leaves one open.
- **A value the pipeline cannot know is declared, never written.** A credential, a host, a PACS name or a storage path belongs to whoever runs the pipeline. The parameter holds `__SUPPLY__`, and `needs` names it, with `kind: secret` for a credential and `kind: site` for the rest. Every `__SUPPLY__` has its entry in `needs` and every entry its `__SUPPLY__`.
- **No credential is ever written.** A parameter whose name reads as one must hold `__SUPPLY__`.
- **`run` says whether the pipeline has been run at the versions it names.** `run: never` means it passed the checks and nothing more: bringing a pipeline to the index's versions rewrites it, and a rewritten pipeline is untested until someone runs it. After a run it reads `run: {cube: <where>, date: <YYYY-MM-DD>}`, and a change to any plugin version it names sets it back to `never`.
- **The file name is plain** (letters, digits, `.`, `_`, `-`) and unique ignoring case, as is the pipeline's `name`. The two differ because a name is written for a reader (`NIfTI --> FreeSurfer`) and may hold what a file name cannot.

A reader that lists pipelines beside apps takes `name`, `description`, `authors` and `category`, and from each node its `title`, its `previous` and the first word of `plugin`, which is the name of a file in `plugins/`.

## Shelves

`shelves.yml` says what the apps are for. A descriptor cannot: its form is CUBE's, and `category` is free text that most plugins leave empty.

```yaml
- shelf: Models
  says: Apps that run a trained model.
  apps:
    - pl-lld_inference
    - pl-monai_spleenseg
```

An app may stand on several shelves or on none, and the list of shelves is flat. Every name under `apps` is a file in `plugins/`. `says` is one sentence that is true of everything on the shelf; an app it is not true of belongs elsewhere.

## Filling a CUBE

The intended path is mise: `plugin add --json <file, directory or URL>`, which compares the CUBE with the index, shows what it will add, and does nothing on a replay. It is being built (HARBOR-planning#183).

Until then, CUBE's admin API takes a descriptor directly. As a CUBE administrator:

```bash
curl -u chris:<password> \
  -F fname=@plugins/pl-dcm2niix.json \
  -F compute_names=<compute resource> \
  https://<cube>/chris-admin/api/v1/
```

### Pipelines

A consumer of a pipeline file does three things before upload:

1. reads `needs`, and either asks for each value, shows it as something the runner supplies, or refuses; it does not register a pipeline with `__SUPPLY__` still in it without saying so;
2. removes `run` and `needs`;
3. registers the plugins the nodes name, since CUBE resolves each by name and version.

Then, as any CUBE user:

```bash
curl -u <user>:<password> \
  -F fname=@<the file, without run and needs> \
  -F type=yaml \
  https://<cube>/api/v1/pipelines/sourcefiles/
```

## Changing the index

Every change is a pull request.

- **Add or bump a plugin:** add or replace `plugins/<name>.json`. Say in the commit message where the descriptor came from: the plugin's own `chris_plugin_info`, a CUBE, or written by hand.
- **Remove a plugin:** move it to `excluded.yml` with its last version and the reason. Nothing leaves the index silently.
- **Add or change a pipeline:** add or replace its file in `pipelines/`. Say in the commit message where it came from and name each parameter changed on the way in. A pipeline not run at the versions it names carries `run: never`.
- **Leave a pipeline out:** name it in `pipelines-excluded.yml` with the reason.

## Checks

Every pull request runs the checks, and so can you:

```bash
pip install jsonschema pyyaml
python -m checks.index
```

They hold that each descriptor fits `schema/plugin.schema.json`, that its file is named for its plugin, that no two names differ only by case, that nothing is both in `plugins/` and in `excluded.yml`, that no credential-named parameter carries a default, and that every app on a shelf is in `plugins/`. They hold each pipeline to `schema/pipeline.schema.json` and to the rules under [A pipeline](#a-pipeline). A clean run prints nothing.

## License

MIT. Each plugin is under its own license, named in its descriptor.
