# Reference

Every action, its inputs and outputs, and what a failure looks like. The tables are generated from the `action.yml` files (`scripts/render_reference.py`, checked by the tests); the prose around them is written by hand.

Conventions common to all of them:

- **Pin by commit.** `uses: tanakapayam/actions/<path>@<40-hex commit> # v0.1.0`.
- **Paths** are relative to the workspace (`$GITHUB_WORKSPACE`) unless absolute, such as `${{ runner.temp }}/dist` or `packages/foo/dist`. Every step of every action sets its own `working-directory` to the workspace root, so a job's `defaults.run.working-directory` (a monorepo's `python/`, say) never changes what a path means.
- **Booleans are the strings** `"true"` and `"false"`, because every input is a string.  Quote them in YAML (`expect-provenance: "true"`).
- **Failures** are a GitHub `::error::` annotation with a reason, and a failed step.
- **Runner**: `ubuntu-24.04` (or any runner with `bash` and `python3` 3.11 or newer). The actions run standard-library Python from this repository and use no other action.

## `release/guard`

Checks that a GitHub Release is ready to publish. It does not read your code: the step before it reads the version, which keeps the guard the same for every ecosystem.

It fails unless: there is a release tag; the version is not empty; the tag is exactly `<tag-prefix><version>`; the changelog has a `## [<version>]` heading; and that heading does not say *Unreleased*. With `require-date: "true"` the heading must be `## [1.2.3] - 2026-10-04`, with a real date. Run it only on release events (`if: github.event_name == 'release'`).

<!-- generated:release/guard -->
| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `tag-prefix` | yes | none | The tag prefix, such as `python-v` (a release tag is the prefix plus the version). |
| `version` | yes | none | The version the code declares, read by an earlier step of your own (a one-liner on `__version__`, `package.json`, ...). An empty value fails the guard. |
| `changelog` | no | `CHANGELOG.md` | Path to the changelog, relative to the workspace. |
| `tag` | no | `${{ github.event.release.tag_name }}` | The release tag to check. Defaults to the tag of the release that triggered the run. |
| `require-date` | no | `false` | `true` to require the heading to carry an ISO date, `## [1.2.3] - 2026-10-04`, rather than merely not say Unreleased. |
<!-- /generated -->

```yaml
- name: Read the version
  id: version
  run: echo "version=$(python -c 'import mypkg; print(mypkg.__version__)')" >> "$GITHUB_OUTPUT"
- name: Check the release is ready
  if: github.event_name == 'release'
  uses: tanakapayam/actions/release/guard@<commit> # v0.1.0
  with:
    tag-prefix: v
    version: ${{ steps.version.outputs.version }}
```

## `artifact/fingerprint`

Fingerprints a directory of build outputs. The fingerprint is `sha256-` followed by the SHA-256 of a manifest: one `<sha256>  <relative path>` line per file, sorted by path. It changes if any byte, any name, or the set of files changes. An empty directory, a missing path or a symbolic link is an error, not a fingerprint of nothing. Pass the output to the downstream jobs through `jobs.<id>.outputs`.

<!-- generated:artifact/fingerprint -->
| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `path` | yes | none | The directory (or single file) to fingerprint, relative to the workspace. |

| Output | Description |
| --- | --- |
| `digest` | The fingerprint, `sha256-` and 64 hex digits. Pass it to `artifact/verify-fingerprint`. |
<!-- /generated -->

## `artifact/verify-fingerprint`

Fails unless a directory is exactly what was fingerprinted. Run it right after every download of the artifact: in the staging job, and again in each publishing job. `expected` must look like a fingerprint, so an output that was never set (a skipped build, a renamed output) is an error and cannot make the check pass by being empty.

<!-- generated:artifact/verify-fingerprint -->
| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `path` | yes | none | The directory (or single file) to check, relative to the workspace. |
| `expected` | yes | none | The fingerprint from `artifact/fingerprint`, normally `needs.build.outputs.<name>`. An empty or malformed value fails, so a skipped or renamed output cannot pass the check by being missing. |
<!-- /generated -->

## `python/rehearsal-version`

Makes `1.1.0` into `1.1.0.dev<run-number × 100 + attempt>`, for builds that go to TestPyPI or only get staged. The result is below the real release (so it never stands in for it), and different for every run and every re-run, which matters because TestPyPI refuses a file name it has seen before, even after a deletion. With `write: "true"` (the default) it rewrites the version in `file`, so run it **before** building. The attempt must be 1 to 99.

<!-- generated:python/rehearsal-version -->
| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `file` | yes | none | The file that holds the version, relative to the workspace (`src/pkg/__init__.py`). |
| `pattern` | no | `^__version__ = "([^"]+)"$` | A regular expression, matched per line, with one group around the version. The default matches `__version__ = "1.2.3"`; for `pyproject.toml` use `^version = "([^"]+)"$`. |
| `run-number` | no | `${{ github.run_number }}` | The run number. Defaults to this run's. |
| `run-attempt` | no | `${{ github.run_attempt }}` | The attempt number, 1 to 99. Defaults to this run's. |
| `write` | no | `true` | `true` to also rewrite the version in `file` (do this before building). |

| Output | Description |
| --- | --- |
| `version` | The rehearsal version. |
<!-- /generated -->

## `python/verify-install`

The stage. Given the directory a build left, it:

1. checks the wheel and the sdist against the source tree: every file under the package directory must be in both, and neither may hold a file the source does not have (unless `allow-extra` names it). A module that is new in the source and missing from the build is the failure this exists to catch: it imports from a checkout and breaks for everyone else;
2. installs the wheel, and the sdist, each into a fresh virtual environment, from the file itself;
3. runs a built-in smoke test in each, isolated (`python -I`): the installed version equals the built one, the package imports from `site-packages`, and `py.typed` is there if you said so;
4. runs your own `smoke` script, if any, in each, with `<distribution name> <import name> <version>`
   as arguments.

The distribution must be pure Python with one wheel (and an optional sdist). The `python` input is
the command that runs Python, so a matrix job can test each version:
`python: uv run --no-project python` after `setup-uv` with that version.

<!-- generated:python/verify-install -->
| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `dist` | yes | none | The directory the build left, holding exactly one wheel and at most one sdist. |
| `source-root` | no | `.` | The project root (where `pyproject.toml` is), relative to the workspace. |
| `package-dir` | no | empty | The package directory relative to `source-root`. Default `src/<name>`, then `<name>`. |
| `import-name` | no | empty | What the package is imported as. Default is the distribution name with `_`. |
| `allow-extra` | no | empty | Newline-separated globs, relative to the package directory, for files a build adds on purpose and the source tree does not have (a generated `_version.py`). |
| `expect-py-typed` | no | `false` | `true` to require `py.typed` in the install. |
| `smoke` | no | empty | A Python script to run inside each install, after the built-in checks, with the arguments `<distribution name> <import name> <version>`. A non-zero exit fails the stage. |
| `dependency-index` | no | `https://pypi.org/simple/` | Where dependencies (and an sdist's build backend) are installed from. |
| `python` | no | `python3` | The command that runs Python 3.11 or newer; set it to test on a particular version, such as `uv run --no-project python` after setting up uv with that version. |
<!-- /generated -->

## `python/verify-published`

After an upload, reads the release back from the index:

1. **listing**: waits for the index to list the version, and each built file with the hash that was built (a different hash is final, not retried);
2. **download**: fetches every listed URL and compares the bytes with what was built, and asks `pip download` to resolve the exact version and compares that wheel too;
3. **install**: installs the wheel that was just fetched into a fresh environment and runs the smoke tests of `python/verify-install`;
4. **provenance** (with `expect-provenance: "true"`): every file has a non-empty attestation record, from `<index>/integrity/...`.

Not-yet-there answers (the index and its CDN lag behind an upload) are retried: `attempts` times, `delay` seconds apart (by default about five minutes in all). Anything that proves the files are wrong is final.

<!-- generated:python/verify-published -->
| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `dist` | yes | none | The directory that was uploaded, holding exactly one wheel and at most one sdist. |
| `index` | no | `https://pypi.org` | The index's root, without a trailing slash. `https://test.pypi.org` for TestPyPI. |
| `expect-provenance` | no | `false` | `true` to require a provenance record for every file (PyPI trusted publishing). |
| `attempts` | no | `20` | How many times to look before giving up; a fresh upload takes a while to appear. |
| `delay` | no | `15` | Seconds between attempts. |
| `import-name` | no | empty | What the package is imported as. Default is the distribution name with `_`. |
| `expect-py-typed` | no | `false` | `true` to require `py.typed` in the install. |
| `smoke` | no | empty | A Python script to run inside the install; see `python/verify-install`. |
| `dependency-index` | no | `https://pypi.org/simple/` | Where dependencies are installed from (a rehearsal's dependencies are on PyPI). |
| `python` | no | `python3` | The command that runs Python 3.11 or newer. |
<!-- /generated -->

Run it **after** the upload step, and understand what a failure means: the upload is done and cannot be undone, so do not re-run it, look at the release (see the guide).
