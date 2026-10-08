# FAQ

## Do I need all six actions?

No. They are independent. The guard alone is a fine first step for any release workflow, and the fingerprint pair helps any build-then-publish flow in any language. The Python pair (`verify-install`, `verify-published`) and `rehearsal-version` are for Python packages.
[Examples](examples.md) shows each on its own.

## Does it publish my package?

No, it does not. The upload, its `id-token: write` permission and its approval gate stay in your own workflow, using `pypa/gh-action-pypi-publish`. These actions run *around* it: before (guard, stage) and after (read-back). See [why](trusted-publishing.md#why-these-are-composite-actions).

## How is this different from `pypa/gh-action-pypi-publish`, `twine check` or release tools?

They answer different questions, and they combine.

- **`gh-action-pypi-publish`** uploads. These check what is about to be uploaded, and what the
  index now serves.
- **`twine check`** (and similar tools) validate a package's metadata. This also checks that the
  build holds every source file, that it installs and runs on every Python you support, and that
  nothing changed between the build and the upload.
- **Release tools** (changelog and version automation) decide *when* a release happens and *what
  version* it is. These check the release before it goes out. The guard is the only part that
  touches that question, and only to verify the tag, the code and the changelog agree.

## Do I have to use trusted publishing?

The checks do not care how you upload. The templates and the guide assume trusted publishing, because it removes the stored token, and `expect-provenance` only means something when the upload is made that way. If you upload with a token, leave `expect-provenance` off.

## Which build tools work?

Any: the checks run on the built wheel and sdist, not on how they were made (`uv build`, `python -m build`, hatchling, setuptools, flit, poetry-core, ...).

## Which packages work?

Pure-Python packages with one wheel and, optionally, an sdist. Packages with compiled extensions or several platform wheels need a different install check, which these do not do.

## Does it work with a private index, or something other than PyPI?

The read-back uses the PyPI JSON API (`/pypi/<project>/<version>/json`) and the simple index (`/simple/<project>/`), plus `/integrity/...` for provenance. Indexes that implement them should work; others may not. It has been tested against PyPI's behavior through a local imitation and against a real PyPI release, and not against any other index. The guard, the fingerprint pair and the stage do not use an index (the stage's installs reach one only for dependencies).

## Which runners and Python versions?

The actions need `bash` and `python3` 3.11 or newer on the runner, and are developed and tested on `ubuntu-24.04` (whose `python3` is 3.12). Their scripts and the whole test suite also pass on macOS. GitHub-hosted macOS and Windows *runners* are not part of CI, so treat them as untested. The stage tests *your package* on any Python you can put on the runner (see [Examples](examples.md#one-stage-job-per-python-version)).

## What does it cost in CI minutes?

The stage runs once per Python version you list, each a few minutes at most (it creates two fresh virtual environments and installs into each). The read-back waits for the index, usually seconds and at most about five minutes by default. A four-version matrix is about four short jobs per release.

## Is it safe to run?

The actions need no secrets and no token, and nothing in them writes anywhere but the job's own files, summary and output. Each is a screenful of `bash` around a script of standard-library Python; none uses another action; and an input only ever reaches a script as an environment variable, so a value that contains `$(...)` is just text. Pin the commit, as for any action. The one thing to watch is your own workflow: keep `id-token: write` on the publish jobs and nowhere else. See [SECURITY.md](../SECURITY.md) for what the actions do and do not defend against.

## Why pin a commit and not a tag, or `@main`?

A tag can be moved and a branch always moves; a commit cannot. For something that sits in your release pipeline, "exactly this code" is the right guarantee. Keep the version as a comment (`# v0.1.0`) and let Dependabot propose updates, which it will, as a pull request with the changelog.

## Why isn't a hidden file such as `.gitignore` counted in the fingerprint?

Because it would not survive the trip. `actions/upload-artifact` leaves hidden files out of an artifact unless you say `include-hidden-files: true`, and `uv build` leaves a `.gitignore` in its output directory. A fingerprint that counted it would match in the job that built and never in the job that checks. If you do upload hidden files, set `include-hidden: "true"` on both fingerprint actions and `include-hidden-files: true` on the upload.

## What if the read-back is red?

Do not re-run it. The upload is done and cannot be undone. See [the guide](guide.md#if-the-read-back-is-red) and [what each message means](failures.md).

## How do I check a release that already exists?

The checks are plain Python scripts. Put the release's wheel and sdist in a directory and run `python lib/pyrelease.py verify-published dist --expect-provenance` ([how](examples.md#checking-a-release-that-already-exists)).

## Can I re-run a publish job?

Re-running the *upload* of a version that is already on PyPI fails, correctly: PyPI never accepts the same file twice. For TestPyPI rehearsals the upload uses `skip-existing`, which is why the read-back compares hashes: a skipped upload must not be mistaken for the files just built.

## What about npm, containers, crates?

The generic actions (`release/guard`, `artifact/fingerprint`, `artifact/verify-fingerprint`) work for anything today. Ecosystem-specific read-backs are on the [roadmap](roadmap.md): npm first. If you need another, open an issue describing the registry's listing and provenance APIs.

## How is it tested, and why should I trust it?

Every script is unit-tested; the Python checks are integration-tested against a real build, real virtual environments and a local index that can misbehave on purpose; each `action.yml` is run through a test runner and again for real in CI. The first real read-back was run by hand against a published release. [Testing](testing.md) lists what is covered and, as plainly, what is not.

## Where do I ask for help or report a problem?

See [SUPPORT.md](../SUPPORT.md). For a security problem, [SECURITY.md](../SECURITY.md).
