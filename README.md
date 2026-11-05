# chris-plugins

The index of [ChRIS](https://chrisproject.org) plugins: one descriptor per plugin, at its latest version, in the form a CUBE's admin API accepts. Any CUBE can be filled from it: the public store at `cube.chrisproject.org`, a development stack, miniChRIS, an institutional deployment.

## Why this exists

The list of ChRIS plugins used to live only inside a running store. When the store at `cube.chrisproject.org` went down in October 2026, the list went with it, and every tool that registers plugins by name (chrisomatic, miniChRIS, `plugin add` in mise) stopped working on a fresh CUBE. This repository keeps the list where no single server owns it. A store is a published view of this index, and rebuilding one is routine.

Background and plan: [HARBOR-Medical-AI/HARBOR-planning#183](https://github.com/HARBOR-Medical-AI/HARBOR-planning/issues/183).

## Layout

```
plugins/<name>.json         one file per plugin: its full descriptor, latest version
excluded.yml                plugins deliberately left out, with the reason
schema/plugin.schema.json   what a descriptor may contain
```

## A descriptor

A file in `plugins/` is exactly what CUBE's admin upload takes as its `fname` file, and what a plugin's own `chris_plugin_info` prints, with no wrapper.

- **The file name is the plugin name**, so the index holds one version per plugin. Bumping a plugin is a one-file change: the version, the image tag and any parameter changes show in the diff.
- **Required:** `name`, `version`, `dock_image`, `type`, `execshell`, `selfpath`, `selfexec`, `parameters`.
- **`dock_image` must be publicly pullable.** A plugin whose image lives only in a private registry does not belong here.
- **Parameter types are CUBE's upload names:** `str`, `int`, `float`, `bool`, `path`, `unextpath`. A CUBE's read API shows them as `string`, `integer` and `boolean`; the upload rejects those.
- **Resource limits are written as in Kubernetes:** CPU as `1000m`, memory as `512Mi` or `2Gi`. A limit equal to CUBE's default is left out.

## Filling a CUBE

The intended path is mise: `plugin add --json <file, directory or URL>`, which compares the CUBE with the index, shows what it will add, and does nothing on a replay. It is being built (HARBOR-planning#183).

Until then, CUBE's admin API takes a descriptor directly. As a CUBE administrator:

```bash
curl -u chris:<password> \
  -F fname=@plugins/pl-dcm2niix.json \
  -F compute_names=<compute resource> \
  https://<cube>/chris-admin/api/v1/
```

## Changing the index

Every change is a pull request.

- **Add or bump a plugin:** add or replace `plugins/<name>.json`. Say in the commit message where the descriptor came from: the plugin's own `chris_plugin_info`, a CUBE, or written by hand.
- **Remove a plugin:** move it to `excluded.yml` with its last version and the reason. Nothing leaves the index silently.

## License

MIT. Each plugin is under its own license, named in its descriptor.
