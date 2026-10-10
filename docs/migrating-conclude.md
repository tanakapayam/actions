# Migrating conclude

[conclude](https://github.com/tanakapayam/conclude) is where these actions came from, so it is also the first consumer. Its three publish workflows each carry their own copy of the same ideas; this maps every copy to the action that replaces it, in the order that is safe to do it.

The conclude migration changes release plumbing, not the package, so it ships as plain commits with a dry run to prove each one. Pin commits only after this repository has a tagged release (`git ls-remote --tags https://github.com/tanakapayam/actions v0.1.3 'v0.1.3^{}' | tail -n1 | cut -f1`).

## Python (`python-publish.yml`)

| In conclude today | Replaced by | Notes |
| ----------------- | ----------- | ----- |
| "Check the release is ready" shell step | [`release/guard`](reference.md#releaseguard) | `tag-prefix: python-v`, `version` from a step that reads `__version__`. |
| `scripts/release.py rehearsal-version` | [`python/rehearsal-version`](reference.md#pythonrehearsal-version) | `file: python/src/conclude/__init__.py`. |
| `scripts/release.py integrity` / `check-integrity` | [`artifact/fingerprint`](reference.md#artifactfingerprint) / [`artifact/verify-fingerprint`](reference.md#artifactverify-fingerprint) | For a flat directory the digest is the same string, so a run that spans the change still verifies. |
| `scripts/release.py verify-install` and its embedded smoke test | [`python/verify-install`](reference.md#pythonverify-install) with a `smoke:` script | See below. |
| `scripts/release.py verify-published` | [`python/verify-published`](reference.md#pythonverify-published) | Same checks; the download now fetches each listed URL as well as asking `pip`. |

After the move, `python/scripts/release.py`, its unit tests and the workflow tests that pin its text can be deleted or rewritten to pin the `uses:` lines instead.

### The smoke test

conclude's own check used to live inside `release.py`. It becomes a script that the stage passes as `smoke:`, so it is conclude's, not the action's:

```python
# python/scripts/smoke.py
import shlex
import sys

import conclude
from conclude import App, opt

assert conclude.__version__ == sys.argv[3]
app = App(
    "smoke",
    {"cache": True, "debug": False, "verbose": opt(bool)},
    config_home_path=None,
    config_cwd_path=None,
)
parser = app.build_arg_parser(prog="smoke")


def parse(argv):
    namespace = parser.parse_args(argv)
    return {key: value for key, value in vars(namespace).items() if value is not None}


resolved = app.resolve(parse(["--no-cache", "--debug"]))
assert resolved["cache"] is False and resolved["debug"] is True, resolved
line = app.format_invocation(resolved, prog="smoke")
assert line == "smoke --no-cache --debug", line
assert app.resolve(parse(shlex.split(line)[1:])) == resolved, "an invocation does not read back"
```

### The stage and the read-back

```yaml
stage:
  # ...matrix and setup as today...
  steps:
    - name: Check these are exactly the distributions that were built
      uses: tanakapayam/actions/artifact/verify-fingerprint@<commit> # v0.1.3
      with:
        path: ${{ runner.temp }}/dist
        expected: ${{ needs.build.outputs.integrity }}
    - name: Install them into clean environments and smoke-test
      uses: tanakapayam/actions/python/verify-install@<commit> # v0.1.3
      with:
        dist: ${{ runner.temp }}/dist
        source-root: python
        expect-py-typed: "true"
        smoke: python/scripts/smoke.py
        python: uv run --no-project python
```

and in `publish-pypi`, after the upload:

```yaml
- name: Install the release back from PyPI and check it
  uses: tanakapayam/actions/python/verify-published@<commit> # v0.1.3
  with:
    dist: dist
    expect-provenance: "true"
    smoke: python/scripts/smoke.py
```

(the `smoke` path needs a checkout in that job, which the staged workflow already has).

## Node (`node-publish.yml`) and Bash (`bash-publish.yml`)

Only the generic pieces move now:

- The **release guard** step in both becomes `release/guard` (`tag-prefix: node-v` or `bash-v`, `version` from `package.json` or `CONCLUDE_VERSION`). Node's extra "must not be private" check stays as its own step.
- Bash's `.sha256` asset is a *published checksum of one file*, in `sha256sum` format. It must stay a raw `sha256sum`; the fingerprint here is an internal pipeline check and would not be the same string. Keep it.
- Node compares npm's own `integrity` value and stages on GitHub Packages. That has no equivalent here yet: the Node actions are on the [roadmap](roadmap.md), so leave `registry.mjs` where it is.

## Applying the prepared change

The Python, Node and Bash workflows, `python/scripts/smoke.py`, conclude's staged-pipeline tests and `python/RELEASING.md` come as one prepared change, with the actions pinned as `@COMMIT_SHA # vX.Y.Z` placeholders. Once `v0.1.3` of this repository is released:

```
# from the root of the conclude repository
unzip -o conclude-migration.zip
git rm python/scripts/release.py python/test/test_release_script.py
SHA=$(git ls-remote --tags https://github.com/tanakapayam/actions v0.1.3 'v0.1.3^{}' | tail -n1 | cut -f1)
test ${#SHA} -eq 40 && sed -i "s/@COMMIT_SHA # vX.Y.Z/@$SHA # v0.1.3/" .github/workflows/*.yml
```

(on macOS, `sed -i ''`). Until the placeholders are replaced, conclude's own pin test fails, on purpose: nothing unpinned can be merged. Then run the Python workflow as `dry-run`, then `testpypi`.

## Order of work

1. Release `v0.1.3` of this repository (see [RELEASING.md](../RELEASING.md)); note the commit.
2. In conclude, replace the Python guard and the fingerprint steps; run the workflow as `dry-run`.
3. Replace the stage with `python/verify-install`; `dry-run` again.
4. Replace the two read-backs, run as `testpypi` (rehearsal), then release for real.
5. Delete `python/scripts/release.py` and the tests that pinned it.
6. Replace the guard in the Node and Bash workflows.

Each step is a separate commit with a green dry run, so any one can be reverted alone.
