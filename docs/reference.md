# Reference

Every action, its inputs and outputs, and what a failure looks like. The tables are generated from the `action.yml` files (`scripts/render_reference.py`, checked by the tests); the prose around them is written by hand.

Conventions common to all of them:

- **Pin by commit.** `uses: tanakapayam/actions/<path>@<40-hex commit> # v0.2.0`.
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
  uses: tanakapayam/actions/release/guard@<commit> # v0.2.0
  with:
    tag-prefix: v
    version: ${{ steps.version.outputs.version }}
```

## `artifact/fingerprint`

Fingerprints a directory of build outputs. The fingerprint is `sha256-` followed by the SHA-256 of a manifest: one `<sha256>  <relative path>` line per file, sorted by path. It changes if any byte, any name, or the set of files changes. **Hidden files are not counted** (names that begin with a dot, at any depth) unless `include-hidden` is `"true"`: `actions/upload-artifact` leaves them out of an artifact by default, and `uv build` leaves a `.gitignore` in its output directory, so a fingerprint that counted them would never survive the trip from the job that builds to the job that checks. The log and the job summary list the files that were counted, so two jobs' views can be compared. An empty directory, a missing path or a symbolic link is an error, not a fingerprint of nothing. Pass the output to the downstream jobs through `jobs.<id>.outputs`.

<!-- generated:artifact/fingerprint -->
| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `path` | yes | none | The directory (or single file) to fingerprint, relative to the workspace. |
| `include-hidden` | no | `false` | `true` to also count files and directories whose names begin with a dot. By default they are not counted, because `actions/upload-artifact` leaves them out unless told otherwise, and some builders leave one behind (`uv build` writes a `.gitignore` into its output directory), so counting them would make a fingerprint that never survives an upload and a download. Set it the same on both actions, and set `include-hidden-files: true` on the upload. |

| Output | Description |
| --- | --- |
| `digest` | The fingerprint, `sha256-` and 64 hex digits. Pass it to `artifact/verify-fingerprint`. |
<!-- /generated -->

## `artifact/verify-fingerprint`

Fails unless a directory is exactly what was fingerprinted, counting hidden files the same way the fingerprint did (`include-hidden` must match). On a mismatch it prints the files it counted and the hidden files it left out, to compare with the list the fingerprint step printed. Run it right after every download of the artifact: in the staging job, and again in each publishing job. `expected` must look like a fingerprint, so an output that was never set (a skipped build, a renamed output) is an error and cannot make the check pass by being empty.

<!-- generated:artifact/verify-fingerprint -->
| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `path` | yes | none | The directory (or single file) to check, relative to the workspace. |
| `expected` | yes | none | The fingerprint from `artifact/fingerprint`, normally `needs.build.outputs.<name>`. An empty or malformed value fails, so a skipped or renamed output cannot pass the check by being missing. |
| `include-hidden` | no | `false` | `true` to also count files and directories whose names begin with a dot. By default they are not counted, because `actions/upload-artifact` leaves them out unless told otherwise, and some builders leave one behind (`uv build` writes a `.gitignore` into its output directory), so counting them would make a fingerprint that never survives an upload and a download. Set it the same on both actions, and set `include-hidden-files: true` on the upload. |
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
| `expect-provenance` | no | `false` | `true` to require a provenance record for every file (PyPI and TestPyPI trusted publishing). |
| `attempts` | no | `20` | How many times to look before giving up; a fresh upload takes a while to appear. |
| `delay` | no | `15` | Seconds between attempts. |
| `import-name` | no | empty | What the package is imported as. Default is the distribution name with `_`. |
| `expect-py-typed` | no | `false` | `true` to require `py.typed` in the install. |
| `smoke` | no | empty | A Python script to run inside the install; see `python/verify-install`. |
| `dependency-index` | no | `https://pypi.org/simple/` | Where dependencies are installed from (a rehearsal's dependencies are on PyPI). |
| `python` | no | `python3` | The command that runs Python 3.11 or newer. |
<!-- /generated -->

Run it **after** the upload step, and understand what a failure means: the upload is done and cannot be undone, so do not re-run it, look at the release (see the guide).

## `ci/all-green`

The one check to require on a branch. It reads `toJSON(needs)` of the calling job and fails unless every job in it has the result `success`. A job that was skipped, cancelled or failed fails the check; a skip is acceptable only for a job named in `allow-skipped`, and a name there that is not one of the jobs waited for is an error, so a typo cannot allow nothing quietly. An empty `needs` is an error too: a gate that waits for nothing checks nothing. The calling job must list the jobs under `needs:` and have `if: always()`.

<!-- generated:ci/all-green -->
| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `needs` | yes | none | The jobs to check: the `toJSON` of the calling job's `needs` context, passed as it is. The calling job must list the jobs in `needs:` and have `if: always()`, or it is skipped when one of them fails, and a skipped required check passes. |
| `allow-skipped` | no | empty | Jobs whose `skipped` result is acceptable, such as one that only runs on some events, separated by commas or new lines. |
<!-- /generated -->

```yaml
all-green:
  needs: [test, lint]
  if: always()
  runs-on: ubuntu-24.04
  timeout-minutes: 5
  steps:
    - uses: actions/checkout@<commit> # v7.0.1
      with:
        persist-credentials: false
```

The step prints a line per job and appends a table of results to the job summary.

## `python/supported-versions`

Reads the `Programming Language :: Python :: 3.x` classifiers of a `pyproject.toml` and prints the versions as a matrix, oldest first. With `check-requires-python: "true"` (the default) it also fails if a classifier is outside `requires-python`, or if `requires-python` admits a version no classifier lists, since users could install where nothing was tested. Only simple specifiers (`>=3.11`, optionally with `<3.15` or `!=`) are compared; others give a `::warning::` and the classifiers are used as they are. There must be at least one classifier.

<!-- generated:python/supported-versions -->
| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `pyproject` | no | `pyproject.toml` | The `pyproject.toml` to read, relative to the workspace. |
| `check-requires-python` | no | `true` | `true` to fail when a classifier is outside `requires-python`, or when `requires-python` admits a version that no classifier lists. A specifier that is not simple is not checked. |

| Output | Description |
| --- | --- |
| `matrix` | The versions as a compact JSON list, oldest first, such as `["3.11","3.12","3.13"]`. Feed it to a matrix with `fromJSON` on this job's output. |
| `oldest` | The oldest version claimed, such as `3.11`, a good one for lint and type checks. |
| `latest` | The newest version claimed, such as `3.14`. |
<!-- /generated -->

Give the step an `id` and read its outputs, or expose them as job outputs for a matrix in another job (see the [examples](examples.md#a-test-matrix-that-cannot-drift-from-the-classifiers)).

## `workflow/policy`

Checks workflow files against rules that keep a release pipeline trustworthy. Every finding is an annotation on its line, titled with the rule; any finding fails the step. The rules:

- `pinned-actions`: every `uses:` is a 40-hex commit with a `# v1.2.3` comment; a local `./` action is fine; a container image needs a digest.
- `pinned-runners`: no runner label with `latest` in it (a `${{ matrix.<key> }}` label is resolved through the matrix).
- `read-only-token`: top-level `permissions` is `contents: read`.
- `job-timeouts`: every job has `timeout-minutes`.
- `checkout-credentials`: every `actions/checkout` has `persist-credentials: false`.
- `no-stored-secrets`: only the secrets in `allow-secrets` are used, and `secrets: inherit` is refused.
- `oidc-jobs`: `id-token: write` only on the jobs in `id-token-jobs`, never at the top level.
- `concurrency`: the workflow has a `concurrency` group. Off by default.

The checker reads YAML with its own small reader, which refuses anything it would have to guess at (anchors, aliases, tags, merge keys, duplicate keys, multi-line quoted or flow scalars, tabs, a second document) as a finding with the rule `parse`. A file that is not a workflow, an empty directory and an unknown rule are errors as well. [Why](faq.md#why-does-the-policy-checker-carry-its-own-yaml-reader).

<!-- generated:workflow/policy -->
| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `path` | no | `.github/workflows` | The workflows to check: a directory of them or one file, relative to the workspace. |
| `rules` | no | `pinned-actions,pinned-runners,read-only-token,job-timeouts,checkout-credentials,no-stored-secrets,oidc-jobs` | The rules to enforce, separated by commas or new lines: `pinned-actions`, `pinned-runners`, `read-only-token`, `job-timeouts`, `checkout-credentials`, `no-stored-secrets`, `oidc-jobs` and `concurrency`. The default is every rule except `concurrency`. |
| `id-token-jobs` | no | empty | The jobs allowed `id-token: write` (the ones that publish with trusted publishing), separated by commas or new lines. With none, no job may have it. |
| `allow-secrets` | no | `GITHUB_TOKEN` | The secrets a workflow may use, separated by commas or new lines. Only used by the `no-stored-secrets` rule. |
<!-- /generated -->
