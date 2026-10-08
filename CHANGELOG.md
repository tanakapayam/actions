# Changelog

All notable changes to this repository are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the repository adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) with one allowance: until 1.0, a minor release may change an input or an output, and says so here.

A release is a Git tag `vMAJOR.MINOR.PATCH`. Consumers pin the commit, not the tag.

## [Unreleased]

## [0.1.1] - 2026-10-08

### Fixed

- **`artifact/fingerprint` and `artifact/verify-fingerprint` failed in a real pipeline when the build left a hidden file behind.** `uv build` writes a `.gitignore` into its output directory, and `actions/upload-artifact` leaves hidden files out by default, so the build job's fingerprint counted a file that the next job never received and the check failed with `The files are not the ones that were fingerprinted`. Hidden files (names beginning with a dot, at any depth) are no longer counted by default. This was found by the first dry run of a real consumer; the `dogfood` job now fingerprints across a real upload and download, with a hidden file in the build.

### Added

- `include-hidden` on both actions, to count hidden files when you do upload them (`include-hidden-files: true`). Set it the same on both.
- A mismatch now lists the files counted and the hidden files left out, and the fingerprint step lists the files it counted in its log and on its summary page, so two jobs can be compared at a glance. Before, the message held only two digests.

### Upgrading

If you fingerprinted a directory whose hidden files you do upload, add `include-hidden: "true"` to both actions and `include-hidden-files: true` to the upload. Otherwise nothing changes, and a pipeline that failed on the `.gitignore` now passes.

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
