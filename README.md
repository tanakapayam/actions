# actions

[![CI](https://github.com/tanakapayam/actions/actions/workflows/ci.yml/badge.svg)](https://github.com/tanakapayam/actions/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Small, tested GitHub Actions for **releasing packages carefully**: build once, check those exact files, ask a person, upload, and then read the release back from the registry to see that what users get is what you built.

They were extracted from the release pipelines of [conclude](https://github.com/tanakapayam/conclude), where each piece earned its place by catching, or by being the answer to, a real mistake.

```yaml
- name: Check the release is ready
  if: github.event_name == 'release'
  uses: tanakapayam/actions/release/guard@<commit> # v0.1.3
  with:
    tag-prefix: v
    version: ${{ steps.version.outputs.version }}
```

## Who is this for

Anyone who publishes a package from GitHub Actions and would like "it shipped" to mean "what users get is what I built and tested". These are the mistakes it catches before and after the upload, each of which has happened:

- the build **leaves out a file** that is new in the source, and the package imports from a checkout but not for anyone else;
- the thing uploaded is **not the thing that was tested**, because a job rebuilt, or a re-run picked up other files;
- the **tag, the version and the changelog disagree**;
- the upload succeeded and **nobody looked** at what the registry now serves.

## Quick start

**Just the guard, in two minutes.** It works for any ecosystem; a step of yours reads the version.

```yaml
- name: Check the release is ready
  if: github.event_name == 'release'
  uses: tanakapayam/actions/release/guard@<commit> # v0.1.3
  with:
    tag-prefix: v
    version: ${{ steps.version.outputs.version }}
```

**The whole pipeline for a Python package, in about twenty minutes.** Copy [`templates/python-package/python-publish.yml`](templates/python-package/python-publish.yml), fill in the `EDIT` lines, pin the actions, and run it as a `dry-run`: it builds, fingerprints and stages your package on every Python you list, and uploads nothing. The [guide](docs/guide.md) takes it from there to the first release.

## What is in it

| Action | What it does |
| --- | --- |
| [`release/guard`](docs/reference.md#releaseguard) | The release tag is the version the code declares, and the changelog has a real entry for it. |
| [`artifact/fingerprint`](docs/reference.md#artifactfingerprint) | One digest for a directory of build outputs: any byte, name or file that changes changes it. |
| [`artifact/verify-fingerprint`](docs/reference.md#artifactverify-fingerprint) | Fails unless the files are exactly what was fingerprinted. Never passes on an empty value. |
| [`python/rehearsal-version`](docs/reference.md#pythonrehearsal-version) | `1.1.0` becomes `1.1.0.dev10101` for rehearsals, new on every run and re-run. |
| [`python/verify-install`](docs/reference.md#pythonverify-install) | The stage: wheel and sdist hold the whole package, and install and run in clean environments. |
| [`python/verify-published`](docs/reference.md#pythonverify-published) | After the upload: the index lists, serves and installs the very files you built, with provenance. |

They are independent: use one or all. They check and verify; they never publish. The upload stays in your workflow ([why](docs/trusted-publishing.md)).

## Requirements

- **Runner:** `ubuntu-24.04` (developed and tested there), with `bash` and `python3` 3.11 or newer, which GitHub-hosted Ubuntu runners have. macOS and Windows runners are not exercised in CI.
- **Packages:** pure Python, one wheel and optionally an sdist, from any build tool. Extension modules and per-platform wheels are out of scope for now.
- **Registry:** PyPI and TestPyPI. Others work if they implement the PyPI JSON API; none has been tried.
- **Permissions:** the actions need none and take no secrets. Your own publish job needs `id-token: write` for trusted publishing.
- **Cost:** the stage is one short job per Python version you list; the read-back waits for the index, a few minutes at most.

## Why composite actions, and why these

Publishing to PyPI with trusted publishing is matched to the workflow *file* that runs the upload. Reports differ on exactly how reusable workflows interact with that, so these are composite actions, which run inside your job and leave the upload, its permissions and its approval gate in your own workflow. Everything *around* the upload is here. [Concepts](docs/concepts.md) explains the design; [Trusted publishing](docs/trusted-publishing.md) the constraint.

Each action is a few lines of `bash` around a standard-library Python script in [`lib/`](lib), uses no other action, and passes every input to its script through an environment variable, never as text in a shell command. Those rules are enforced by the tests, not by good intentions.

## Documentation

| | |
| --- | --- |
| [Concepts](docs/concepts.md) | The ideas: build once, fingerprint, stage, approve, read back, rehearse, fail closed. |
| [Guide](docs/guide.md) | Adopt it for a Python package, step by step, from registering PyPI to the first release. |
| [Examples](docs/examples.md) | Recipes: another ecosystem, a monorepo, a generated version, your own smoke test, a flat layout. |
| [Reference](docs/reference.md) | Every action's inputs, outputs and behavior. |
| [What a failure looks like](docs/failures.md) | Every message the actions print, what it means and what to do. |
| [FAQ](docs/faq.md) | Does it publish? Which tools, runners, registries? What does it cost? Is it safe? |
| [Trusted publishing](docs/trusted-publishing.md) | Registering publishers, and why the upload stays in your workflow. |
| [Migrating conclude](docs/migrating-conclude.md) | Moving an existing pipeline onto these actions, piece by piece. |
| [Testing](docs/testing.md) | How the actions are tested without running them on GitHub, and what that cannot cover. |
| [Roadmap](docs/roadmap.md) | What is planned (npm, Bash) and what is deliberately not. |

## Using a release

Pin the **commit**, with the tag as a comment, as for any third-party action:

```yaml
- uses: tanakapayam/actions/python/verify-install@<40-hex commit of the release> # v0.1.3
  with:
    dist: dist
```

Each release's workflow run prints the line to paste. Dependabot (`github-actions` ecosystem) keeps the pins current; read the [changelog](CHANGELOG.md) before merging one. Tags are never moved.

## Status

Version 0.1.0 covers a pure-Python package published to PyPI. Until 1.0, a minor release may change an input or an output; the changelog says so when it does.

## Getting help

Start with [what a failure looks like](docs/failures.md) and the [FAQ](docs/faq.md). Then see [SUPPORT.md](SUPPORT.md) for how to report a bug or ask for something, and [SECURITY.md](SECURITY.md) for a vulnerability. Everyone taking part is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).

## Development

```
uv sync --locked
uv run pytest            # everything, including builds and installs of a fixture package
uv run pytest -m "not integration"   # the fast part, no installs
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [RELEASING.md](RELEASING.md).

## License

[MIT](LICENSE).
