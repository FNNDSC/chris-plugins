# The index holds the latest published version, working or not

On 2026-11-22 every plugin in the index was compared with its image registries, and each one found behind was moved to its newest published version. The pipelines were moved with them. This note records what was done, what is known to be broken as a result, and how to repeat the comparison.

## The rule

A descriptor names the newest version of its plugin that has a publicly pullable image. Whether that version runs is a separate question, and the index does not answer it: a version that is published and broken is still the version held here.

The reason is that the index describes what exists. A CUBE filled from it should offer what the registries offer. Holding a plugin back at an older version because the newer one fails would hide the failure from the people who can fix it, and would leave the index recording a judgement nobody wrote down. The failures are written down here instead.

The same holds for pipelines: each names the versions the index holds, and carries `run: never` until someone runs it at those versions.

## What "version" means here

`dock_image` carries the registry tag. `version` is what the image itself reports, from `chris_plugin_info` or `<selfexec> --json`. They usually agree. For these they do not, and the descriptor keeps the image's own number, because that is what CUBE is told:

| plugin | image tag | image reports |
|---|---|---|
| `pl-fshack` | 1.5.3 | 1.5.2 |
| `pl-coneme` | 1.0.2 | 1.0.0 |
| `pl-mpcs` | 1.0.12 | 1.0.10 |
| `pl-spleendata` | 1.0.10 | 1.0.8 |
| `pl-mri10yr06mo01da_normal` | 1.1.5 | 1.1.4 |

So a `version` lower than the tag in `dock_image` is not a plugin left behind.

## What moved

| plugin | from | to | what changed |
|---|---|---|---|
| `pl-dicom_headeredit` | 1.1.8 | 1.2.0 | adds `removePrivateTags` |
| `pl-reg_chxr` | 1.2.1 | 1.3.1 | adds `pipelineName` |
| `pl-gpu_test` | 0.2.2 | 1.0.1 | new command (`gpu_test`), new title and category, minimum memory 32000Mi, GPU limits now 0 |
| `pl-fshack` | 1.5.0 | 1.5.2 (tag 1.5.3) | nothing but the version; image now on Docker Hub only |
| `pl-pfdo_med2img` | 1.2.2 | 1.2.3 | parameters unchanged |
| `pl-mgz2LUT_report` | 1.3.1 | 1.3.2 | parameters unchanged |
| `pl-mri_sag_anon_192` | 1.0.2 | 1.0.3 | parameters unchanged |

Each new descriptor is the image's own output, in the index's form, with two exceptions named below. `pl-reg_chxr` 1.3.1 declares a password default again; it is emptied, as the index requires.

Ten of the twenty pipelines name one of these plugins and were moved: the five FreeSurfer pipelines (`pl-fshack`), `DICOM_anonymization_simple.yml` and `DICOM_anonymization_full.yml` (`pl-dicom_headeredit`), and the four that convert with `pl-pfdo_med2img`. No parameter a pipeline sets was added, removed or retyped by these versions, so only the version in each `plugin:` line changed.

## Known fallout

**`pl-dicom_headeredit` 1.2.0 does not start.** The image `ghcr.io/fnndsc/pl-dicom_headeredit:1.2.0` fails on import:

```
ImportError: cannot import name 'pftree' from 'pftree'
```

It ships `pftree` 4.1.1, and the `pfdicom` it ships needs `pftree` below 4. Every run of this version fails, and so does every run of a pipeline that uses it: two when this was written, seven since the second batch of pipelines came in (`grep -l 'pl-dicom_headeredit' pipelines/*.yml`). It needs a rebuild with `pftree<4`.

Because the image cannot print its own descriptor, the one here was read by installing `pftree<4` in a throwaway container of that image and running `chris_plugin_info` there. It is the parameter list of the code the image ships, not of a program that runs.

The version this replaces, 1.1.8, ships `pydicom` 3.0.1, which removed `read_file()`; a user reports it cannot read files. The last version reported to work is 1.1.6, which removes all private tags unconditionally. So no published version both works and keeps private tags, and 1.2.0 is the one that would if rebuilt.

**`pl-fshack` 1.5.3 was not run.** Its descriptor was not read from the image, which is the whole of FreeSurfer and was not pulled. The source differs between tags 1.5.0 and 1.5.3 in one line of `fshack.py`, the version string, which reads 1.5.2. The descriptor is the 1.5.0 one with that version and the new tag. Tags 1.5.4 and 1.5.5 exist in the repository with no published image, so the index cannot hold them.

**`pl-gpu_test` 1.0.1 asks for no GPU.** Its limits went from one GPU to none, and its `documentation` field points at another plugin's repository. Both are the image's own statement and are held as given.

**Nothing was run on a CUBE.** The seven new versions were checked for what they declare, not for what they do.

## What was not judged

- 35 plugins point at `:latest` and have no version tags in either registry. There is nothing newer to compare them with, and nothing fixes which build `:latest` is.
- `pl-dircopy`, `pl-topologicalcopy` and `pl-tsdircopy` are built into CUBE and point at a placeholder image.
- A plugin with newer source and no published image looks current. Only registry tags were compared, on `ghcr.io` and Docker Hub.

## Repeating the comparison

For each descriptor, list the tags of its image on `ghcr.io` and on Docker Hub, take the highest that reads as a version, and compare it with the tag in `dock_image`, not with `version`. Where a newer tag exists, run that image's `chris_plugin_info --dock-image <image>` (or `<selfexec> --json` for older plugins), write the result in the index's form, and run `python -m checks.index`: it will name every pipeline node left at the old version and every parameter the new version no longer has.

This is not automated yet. It should be: a scheduled job that opens a pull request per plugin behind.
