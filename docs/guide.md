# Guide: releasing a Python package

This takes a pure-Python package from "I build it by hand" to a pipeline that builds once, stages the exact files, waits for your approval, uploads with trusted publishing and reads the release back. It assumes a repository on GitHub and a package that builds with `uv build` (or any PEP 517 backend: hatchling, setuptools, flit).

Read [Concepts](concepts.md) first if you want the reasoning; this is the procedure.

## 0. What your project needs

- A **version in one place the workflow can read**, such as `__version__ = "1.2.3"` in `src/mypkg/__init__.py`. (Dynamic versions that need git history, such as setuptools-scm, work if the build finds the history, but the guard needs the version *before* the build, so read it from wherever your tooling can print it.)
- A **changelog** with Keep-a-Changelog headings: `## [1.2.3] - 2026-10-04`. An entry that says `- Unreleased` blocks a release, on purpose.
- A **release convention**: a GitHub Release whose tag is a prefix plus the version (`v1.2.3`, or `python-v1.2.3` when one repository holds several packages).
- **Pure Python, one wheel.** Packages with compiled extensions need a different install check.

## 1. Register trusted publishers

Do this once per index, following [Trusted publishing](trusted-publishing.md): a publisher on PyPI for your repository, the workflow file name you are about to create, and environment `pypi`; the same on TestPyPI with environment `testpypi` if you want rehearsal uploads.

In the repository settings, create the environments `pypi` (add **required reviewers**: this is the approval gate) and `testpypi`.

## 2. Add the workflow

Copy [`templates/python-package/python-publish.yml`](../templates/python-package/python-publish.yml) to `.github/workflows/python-publish.yml` (the name you registered), and [`dependabot.yml`](../templates/python-package/dependabot.yml) to `.github/dependabot.yml`.

Search the workflow for `EDIT` and change each: the file that holds the version, the Python versions you support, the package name in the environment URLs, the tag prefix.

Then pin the actions. Each `tanakapayam/actions/...@COMMIT_SHA # vX.Y.Z` line needs the commit of a release of this repository:

```
git ls-remote --tags https://github.com/tanakapayam/actions v0.1.0 'v0.1.0^{}' | tail -n1 | cut -f1
```

(It prints the commit the tag points at, whether the tag is annotated or not. The release's workflow run also prints the line to paste.) To fill every placeholder in one go:

```
SHA=$(git ls-remote --tags https://github.com/tanakapayam/actions v0.1.0 'v0.1.0^{}' | tail -n1 | cut -f1)
test ${#SHA} -eq 40 && sed -i "s/@COMMIT_SHA # vX.Y.Z/@$SHA # v0.1.0/" .github/workflows/python-publish.yml
```

(On macOS, `sed -i ''`. The test of 40 characters is there so that an empty lookup cannot write an empty pin.)

Not every pin has to come from this repository: the template's own pins of other actions are Dependabot's to update, and yours to read. The third-party actions in the template (`actions/checkout`, `astral-sh/setup-uv`, the artifact actions, `pypa/gh-action-pypi-publish`) are already pinned to commits; Dependabot keeps all of them current.

## 3. Dry run

Actions, *Publish to PyPI*, **Run workflow**, target `dry-run` (the default). It builds under a rehearsal version, fingerprints the files, and stages them on every Python you listed. Nothing is uploaded. In the run you will see:

- **build**: the rehearsal version in the summary (`1.2.3.dev4201`) and the fingerprint;
- **stage**: one job per Python. `contents: the wheel and the sdist hold all of src/mypkg`, then `wheel:` and `sdist:` lines with the installed version and where it was imported from.

Each job also leaves a short summary on the run's page (open the run and scroll down): a `✅` for every thing it checked, or a `❌` with the reason in full.

If a stage job is red, the message says which file is missing from which archive, or which smoke test failed. This is the whole point: fix it before there is a version number to burn.

## 4. Rehearse on TestPyPI (optional)

Run it again with target `testpypi`. After the stage, the build uploads to TestPyPI and then **reads it back**: it waits for the index, compares hashes, downloads the files, installs them into a fresh environment and smoke-tests that. You can try it yourself:

```
pip install -i https://test.pypi.org/simple/ "mypkg==1.2.3.dev4201"
```

If your package has dependencies, TestPyPI will not have them: the read-back installs them from PyPI (`dependency-index`, the default), but your own `pip install` needs `--extra-index-url https://pypi.org/simple/`.

## 5. Release

1. Bump the version, and give the changelog entry its date.
2. Merge.
3. Create a GitHub Release from a new tag, prefix plus version, on the merged commit.
4. The workflow runs: the **guard** (tag, version, changelog), **build**, **stage**. Then `publish-pypi` waits for a reviewer to approve the `pypi` deployment. Approve when the stage is green and you are ready.
5. After the upload, the **read-back** runs and, when it is green, the release is verified.

### If the read-back is red

Do **not** re-run the job: the upload is finished and cannot be undone. Open the project on PyPI.

- *Listing*, *download* or *install* red a few minutes after the upload, with a "not yet" or "cannot reach" message: the index and its CDN were slow, or briefly out of reach. The check already retried for about five minutes; look at the project page and `pip install` it yourself.
- A **hash or bytes mismatch** is real: PyPI has something other than what was built. Yank the release (Manage, Options, Yank) and publish a fixed version.
- *Provenance* red: the files were uploaded without attestations, or the index has not published them. Check that the workflow uploaded with trusted publishing.

## 6. Customizing

All of these are inputs, [documented in the reference](reference.md).

**Your own smoke test.** The built-in check proves the package installs and imports. To prove it *works*, add a script and pass `smoke: scripts/smoke.py` to `python/verify-install` (and `python/verify-published`). It runs inside each fresh install with `<distribution name> <import name> <version>` as arguments; a non-zero exit fails the stage:

```python
import importlib, sys

module = importlib.import_module(sys.argv[2])
assert module.parse("a=1") == {"a": "1"}
```

**Files a build adds on purpose.** `python/verify-install` insists the build holds exactly the files in the source tree. A generated `_version.py` (hatch-vcs, setuptools-scm) is not in the source, so say so: `allow-extra: "_version.py"` (one glob per line, relative to the package directory).

**Layouts.** The package is found at `src/<import name>`, then `<import name>`. For anything else, `package-dir: lib/mypkg`. If the import name differs from the distribution name with underscores, `import-name: my_actual_module`.

**`py.typed`.** `expect-py-typed: "true"` requires it in the installed package.

**A package in a subdirectory (a monorepo).** The actions always run from the workspace root, even if your job has `defaults.run.working-directory: packages/mypkg`, so give paths from the root: `source-root: packages/mypkg`, `changelog: packages/mypkg/CHANGELOG.md`, a `VERSION_FILE` of `packages/mypkg/src/mypkg/__init__.py`, and a tag prefix that names the package (`mypkg-v`), so one repository can release several.

**Only some of the actions.** Nothing requires the whole pipeline. The guard alone is a fine first step for any release workflow; the fingerprint pair is useful for any build-then-publish flow.

## 7. Upgrading these actions

Dependabot opens a pull request when a new release exists and changes the commit in every `uses:` line. Read the [changelog](../CHANGELOG.md): before 1.0, a minor release may change an input. The dry run is the safe way to try one.

## Troubleshooting

Every message the actions print is explained, with what to do, in [What a failure looks like](failures.md); common ones are below. For other setups (a monorepo, a generated version, another build tool), see [Examples](examples.md); for "why" and "what about", the [FAQ](faq.md).

| You see | It means |
| ------- | -------- |
| `There is no release tag` | The guard ran on a manual run. Give its step `if: github.event_name == 'release'`. |
| `The release tag v1.2.3 does not match the package version (v1.2.4)` | The tag and the code disagree. Fix whichever is wrong; a tag cannot be moved after publishing a release. |
| `has no entry for 1.2.3` / `still marks 1.2.3 as Unreleased` | The changelog heading is missing or undated. |
| `'' is not a fingerprint ... was the step that produces it skipped?` | `needs.build.outputs.<name>` is empty: the output name does not match, or the build job did not run its fingerprint step. |
| `The files are not the ones that were fingerprinted` | The artifact changed between build and now. The log lists the files counted: compare it with the fingerprint step's list. A hidden file (a build's `.gitignore`) is not counted by default, on purpose; if you upload hidden files, see `include-hidden`. Otherwise never "fix" this by re-running only the failed job; rebuild. |
| `the wheel is missing mypkg/foo.py` | The build left a source file out: a packaging include/exclude rule, or `.gitignore` caught it. |
| `the wheel has mypkg/_version.py, which is not in the source tree` | A generated file; add it to `allow-extra`. |
| `cannot find the package ... tried src/mypkg, mypkg` | Set `package-dir`. |
| `No module named ...` in the smoke test | `import-name` is not the import name. |
| `invalid-publisher` from the upload | The trusted publisher does not match: check the file name and environment. See [Trusted publishing](trusted-publishing.md). |
