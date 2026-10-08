# Examples

Recipes for the usual variations. Every snippet here is checked by the tests against the `action.yml` files, so an input that does not exist, or a required one that is missing, fails CI. Replace `@<commit> # v0.1.0` with the pinned commit of a release ([how](guide.md#2-add-the-workflow)).

## Only the guard, for any ecosystem

The guard reads nothing from your code: a step of yours reads the version, so it works the same for Python, Node, Rust or a shell script.

```yaml
- name: Read the version
  id: version
  run: echo "version=$(jq -r .version package.json)" >> "$GITHUB_OUTPUT"
- name: Check the release is ready
  if: github.event_name == 'release'
  uses: tanakapayam/actions/release/guard@<commit> # v0.1.0
  with:
    tag-prefix: v
    version: ${{ steps.version.outputs.version }}
    require-date: "true"
```

## A fingerprint across jobs, for any build

Anything that is built in one job and published in another can be fingerprinted: a container archive, a crate, a tarball.

```yaml
jobs:
  build:
    runs-on: ubuntu-24.04
    outputs:
      fingerprint: ${{ steps.fingerprint.outputs.digest }}
    steps:
      - uses: actions/checkout@<commit> # v7.0.1
      - run: make dist
      - name: Fingerprint the build
        id: fingerprint
        uses: tanakapayam/actions/artifact/fingerprint@<commit> # v0.1.0
        with:
          path: dist
      - uses: actions/upload-artifact@<commit> # v7.0.1
        with:
          name: dist
          path: dist/
  publish:
    needs: build
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/download-artifact@<commit> # v8.0.1
        with:
          name: dist
          path: dist/
      - name: Check these are exactly the files that were built
        uses: tanakapayam/actions/artifact/verify-fingerprint@<commit> # v0.1.0
        with:
          path: dist
          expected: ${{ needs.build.outputs.fingerprint }}
```

Hidden files (names that begin with a dot) are not part of the fingerprint, because
`actions/upload-artifact` leaves them out by default and `uv build` leaves a `.gitignore` in its
output. If you do upload them (`include-hidden-files: true`), count them on both sides:

```yaml
- uses: tanakapayam/actions/artifact/fingerprint@<commit> # v0.1.0
  with:
    path: site
    include-hidden: "true"
```

## The stage with your own smoke test

The built-in check proves a package installs and imports. A script of yours proves it *works*:

```yaml
- name: Install the build and run my checks against it
  uses: tanakapayam/actions/python/verify-install@<commit> # v0.1.0
  with:
    dist: ${{ runner.temp }}/dist
    expect-py-typed: "true"
    smoke: scripts/smoke.py
```

```python
# scripts/smoke.py: argv is <distribution name> <import name> <version>
import importlib
import sys

module = importlib.import_module(sys.argv[2])
assert module.parse("a=1") == {"a": "1"}
```

## One stage job per Python version

```yaml
stage:
  runs-on: ubuntu-24.04
  strategy:
    matrix:
      python-version: ["3.11", "3.12", "3.13"]
  steps:
    - uses: actions/checkout@<commit> # v7.0.1
    - uses: astral-sh/setup-uv@<commit> # v10.2.0
      with:
        python-version: ${{ matrix.python-version }}
    - uses: actions/download-artifact@<commit> # v8.0.1
      with:
        name: dist
        path: ${{ runner.temp }}/dist
    - name: Install and smoke-test on this Python
      uses: tanakapayam/actions/python/verify-install@<commit> # v0.1.0
      with:
        dist: ${{ runner.temp }}/dist
        python: uv run --no-project python
```

## A version generated at build time

hatch-vcs and setuptools-scm write a `_version.py` that is in the build and not in the source tree. Say so, one glob per line:

```yaml
- uses: tanakapayam/actions/python/verify-install@<commit> # v0.1.0
  with:
    dist: ${{ runner.temp }}/dist
    allow-extra: |
      _version.py
```

## A flat layout, or an import name that differs

The package is looked for at `src/<import name>`, then `<import name>`. Otherwise say where:

```yaml
- uses: tanakapayam/actions/python/verify-install@<commit> # v0.1.0
  with:
    dist: ${{ runner.temp }}/dist
    package-dir: lib/my_package
    import-name: my_package
```

## A package in a subdirectory of a repository

The actions always run from the workspace root, even when your job sets `defaults.run.working-directory`, so give paths from the root and name each package in its tag:

```yaml
- name: Check the release is ready
  if: github.event_name == 'release'
  uses: tanakapayam/actions/release/guard@<commit> # v0.1.0
  with:
    tag-prefix: mypkg-v
    version: ${{ steps.version.outputs.version }}
    changelog: packages/mypkg/CHANGELOG.md
- name: Install the build and check it
  uses: tanakapayam/actions/python/verify-install@<commit> # v0.1.0
  with:
    dist: ${{ runner.temp }}/dist
    source-root: packages/mypkg
```

## A rehearsal version for a different file

For a version kept in `pyproject.toml`, say how to find it:

```yaml
- name: Give a rehearsal a version of its own
  id: rehearsal
  uses: tanakapayam/actions/python/rehearsal-version@<commit> # v0.1.0
  with:
    file: pyproject.toml
    pattern: '^version = "([^"]+)"$'
```

## A rehearsal on TestPyPI, read back

TestPyPI does not have your dependencies, so they are installed from PyPI (the default `dependency-index`):

```yaml
- name: Install the rehearsal back from TestPyPI and check it
  uses: tanakapayam/actions/python/verify-published@<commit> # v0.1.0
  with:
    dist: dist
    index: https://test.pypi.org
```

## Checking a release that already exists

The checks are plain scripts, so you can read back any release by hand. Put its wheel and sdist in a directory (`pip download conclude==1.1.0 --no-deps -d dist`, once with `--only-binary=:all:` and once with `--no-binary=:all:`), then:

```
python lib/pyrelease.py verify-published dist --expect-provenance
```
