# Changelog

All notable changes to this repository are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the repository adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) with one allowance: until 1.0, a minor release may change an input or an output, and says so here.

A release is a Git tag `vMAJOR.MINOR.PATCH`. Consumers pin the commit, not the tag.

## [Unreleased]

## [0.1.0] - 2026-10-07

The first release: the release-pipeline pieces of [conclude](https://github.com/tanakapayam/conclude), generalized, for a pure-Python package published to PyPI.

### Added

- `release/guard`: the release tag is the prefix plus the declared version, and the changelog has an entry for it that is not Unreleased (optionally with a required ISO date).
- `artifact/fingerprint` and `artifact/verify-fingerprint`: one digest over the names and bytes of a directory of build outputs, and a check that never passes on an empty or malformed value.
- `python/rehearsal-version`: `1.1.0` becomes `1.1.0.dev<run × 100 + attempt>` for rehearsals.
- `python/verify-install`: the stage. The wheel and sdist hold every file of the package, and install and run from fresh environments (made the way `python -m venv` makes them, with a symlinked interpreter, so that relocatable Pythons such as uv's work on macOS), with an optional caller smoke test and `allow-extra` for generated files.
- `python/verify-published`: the read-back. The index lists the built hashes, serves the built bytes, resolves and installs the built wheel, and (optionally) has provenance for every file; not-yet answers (including an index that cannot be reached for a moment) are retried, wrong bytes are final.
- `templates/python-package/`: a complete publish workflow (build, fingerprint, stage on four Pythons, approval, upload, read-back, `dry-run` by default) and a Dependabot configuration.
- Every check says what it did on the run's summary page (`✅ Stage: ...`, or `❌ ... failed` with the reason), and every option of every script has `--help` text.
- Documentation: concepts, a guide, a generated reference, a catalogue of every message and what to do about it, examples, an FAQ, trusted publishing, migrating conclude, testing and a roadmap; and a support guide, a code of conduct and issue forms. Tests check that every example uses real inputs, and that every message in `lib/` is in the catalogue.
- Tests: unit tests of every script, integration tests that build, install and serve a real fixture package against a misbehaving local index, a runner that executes each `action.yml`, and policy tests for the actions, the workflows, the templates and the docs. CI also lints the workflows (`actionlint`, `zizmor`), runs ShellCheck on every action's scripts, and runs every action for real.
