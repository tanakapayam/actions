# Testing

An action that publishes software has to be trusted before its first real run, and a composite action cannot be run on a laptop. So the strategy is layers, each catching what the one below cannot, and an honest list of what none of them can.

| Layer | Where | What it proves |
| ----- | ----- | -------------- |
| **Script unit tests** | `tests/test_guard.py`, `test_fingerprint.py`, `test_pyrelease.py` | The logic: every way a check passes or refuses, with no network and no packages. |
| **Integration tests** | `tests/test_pyrelease_integration.py` | A real package is built, installed into fresh environments, and read back from a package index running on localhost that can misbehave on purpose. |
| **Action tests** | `tests/test_actions.py` | Each `action.yml` end to end through a small runner: inputs, defaults, outputs, wiring, and what a failure looks like. |
| **Policy tests** | `tests/test_manifests.py`, `tests/test_repo.py` | The rules every action and workflow must follow, the docs, the templates and the pins. |
| **Usability tests** | `tests/test_usability.py` | What a person sees: every option has help text, messages read like sentences, an index that is out of reach is waited for and not a traceback, and a pass or a failure is on the run's summary page. |
| **Documentation tests** | `tests/test_docs.py` | Every YAML example uses real inputs, the catalogue in `docs/failures.md` lists every message in `lib/`, and the pieces a newcomer looks for (quick start, requirements, support, issue forms) exist. |
| **Linters** | `ci.yml`, job `workflows`; `tests/test_shell.py` | `actionlint` (which runs ShellCheck on workflow scripts) and `zizmor` on the workflows and the actions, and ShellCheck on the scripts inside each `action.yml`, which `actionlint` does not read. |
| **Dogfood** | `ci.yml`, job `dogfood` | Every action runs for real, on GitHub, against a fixture package and a local index, including a real upload and download of the artifact (with a hidden file in the build) to check that a fingerprint survives the trip between jobs. |

## The action runner (`tests/actionrun.py`)

GitHub offers no way to run a composite action locally, and a misspelled environment variable would otherwise only show up in CI. `actionrun.run_action(dir, inputs, github={...}, cwd=...)` runs an action's steps the way the runner does: `bash -eo pipefail`, the step's `env:` evaluated from the inputs and contexts, `$GITHUB_OUTPUT` and `$GITHUB_STEP_SUMMARY` files, and action outputs from step outputs.

It is **deliberately stricter than GitHub**. It understands only `inputs.*`, `github.*`, `runner.*` and `steps.<id>.outputs.*`, only `run` steps with `shell: bash`, and it refuses anything else (`uses:`, `if:`, a function call, an expression inside a script). That strictness is the repository's policy turned into a test (see `tests/test_manifests.py`), and it keeps the runner's own behavior small enough to test (`tests/test_actionrun.py`).

## The fake index (`tests/fakeindex.py`)

`python/verify-published` is about what happens after an upload, which cannot be tested against the real PyPI without publishing. `FakeIndex` serves a directory the way PyPI does (the JSON API, the simple index, the files, provenance) and can: not list the release yet (`lag=N`), list a wrong hash, serve other bytes than it lists, leave a file unlisted, and omit or empty the provenance. `pip` talks to it like to any index. In CI the `dogfood` job runs `python tests/fakeindex.py` as a real background server and points the real action at it.

## What is not tested

- **The real PyPI and npm.** Their behavior (and their lag) is modeled, not exercised. The first real read-back is the first real read-back; it was run by hand against a published release while building this.
- **GitHub-side semantics** beyond what `dogfood` runs: expression functions, `defaults.run`, a composite action's behavior on runners other than `ubuntu-24.04`, and trusted publishing itself.
- **Platform wheels and extension modules.** Out of scope for 0.x.
- **A malicious build job.** See [Concepts](concepts.md#what-this-does-not-do).

## Running the tests

```
uv sync --locked
uv run pytest                          # everything
uv run pytest -m "not integration"     # no installs, no builds: seconds
uv run pytest tests/test_actions.py -k guard
```

The integration tests build the fixture package offline (`hatchling` and `build` are development dependencies) and install it into fresh virtual environments. The one thing they need the network for is the **sdist install**, which must fetch a build backend; in CI that is PyPI, and with no network those two checks fail rather than skip, deliberately.

## Adding an action: the checklist

1. `<group>/<name>/action.yml`: composite, `run` steps only, inputs through `env:`, every input used, every input and output described.
2. The logic in `lib/`, standard library only, importable, with a `main()` that prints `::error::` and returns 1 on failure.
3. Unit tests for the script, and `tests/test_actions.py` tests for the action.
4. The docs: its messages in `docs/failures.md` (a test fails until every message in `lib/` is listed), an example in `docs/examples.md`, a section and a generated table in `docs/reference.md` (`uv run python scripts/render_reference.py`), a line in the README, and an entry in the CHANGELOG.
5. A step in the `dogfood` job that runs it for real.
6. If it belongs in the publish workflow, in the template too.

`tests/test_manifests.py` and `tests/test_repo.py` fail until each of those is true.
