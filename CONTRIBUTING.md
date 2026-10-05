# Contributing

Thank you for looking. This repository holds a few small actions that publish software, so it is held to a higher bar of tests than its size suggests, and a change is welcome when it keeps that bar.

## Setup

```
git clone https://github.com/tanakapayam/actions && cd actions
uv sync --locked                       # Python 3.11+ and the development tools
uv run pytest -m "not integration"     # the fast part
uv run pytest                          # everything (builds and installs a fixture package)
uv run ruff check . && uv run ruff format --check . && uv run mypy
uvx --from actionlint-py==1.7.12.25 actionlint && uvx zizmor==1.30.1 --offline .   # needs shellcheck on PATH to lint scripts
```

Python is only the test and script language here; the actions themselves need `bash` and `python3` 3.11+ on the runner and nothing else.

## What an action may be

These are enforced by `tests/test_manifests.py`; the reasons are in [Concepts](docs/concepts.md).

- Composite, with only `run` steps and `shell: bash`. No `uses:`, no `if:` (a condition belongs on the calling step).
- A `${{ }}` expression appears in `env:` (or an output or input default), never inside a script.  An input reaches the script as an environment variable, quoted.
- Every input is used, and every input and output has a description. Defaults are strings.
- The logic is a standard-library script in `lib/`. It prints `::error::<reason>` and returns 1 on failure, and never passes when something that should exist is missing.

## Adding or changing an action

Follow the checklist in [Testing](docs/testing.md#adding-an-action-the-checklist). In short: the action, the script, its tests, the reference (`uv run python scripts/render_reference.py`), the README, the CHANGELOG, a `dogfood` step, and the template if it belongs there. `tests/test_repo.py` fails until the docs, the template and the CI agree with the code.

A change to an input or an output of a released action is a changelog entry that says so, even before 1.0.

## Pull requests

- Keep a change to one thing. Say what failed or what was missing, and how the test would have caught it.
- CI must be green: `all-green` is the one required check.
- Pins (`uses: owner/repo@<40-hex> # vX.Y.Z`) are updated by Dependabot; do not edit one by hand except to follow it.
- Workflows follow `.github/zizmor.yml`; a new finding is fixed, not silenced, unless the reason is written next to it.

## Security

See [SECURITY.md](SECURITY.md). Please do not open a public issue for a vulnerability.

## Releasing

Maintainers: [RELEASING.md](RELEASING.md).
