# Concepts

## The problem

Publishing a package is the one step of a project's life that cannot be taken back. A version on PyPI or npm can be yanked but never replaced, and the file users download is not the file in your repository: it is whatever the build produced, on whatever day, from whatever was checked out. Nearly every release mishap is the same few things: the build left out a file that is new in the source, a different build was uploaded than the one that was tested, the version or the changelog was not what the tag said, or the upload succeeded and nobody looked at what users now get.

These actions are the steps that make each of those impossible to miss.

## The pipeline

```
 release published
        |
        v
  build ──fingerprint──> stage (every supported Python) ──> approval ──> publish ──> read back
   |                      |                                    |            |          |
   | one set of files,    | the files are still the built      | a person   | re-check | the index lists,
   | built once           | ones, hold the whole package,      | decides    | the      | serves and installs
   |                      | install and run in clean envs      |            | finger-  | exactly those files
                                                                              print
```

1. **Build once and promote unchanged.** The distributions are built a single time and uploaded as an artifact. Every later job downloads that artifact; nothing is ever rebuilt.
2. **Fingerprint.** Right after the build, the files get a fingerprint: one digest of every name and every byte. Every job that touches the files downloads them and *verifies the fingerprint first*, so "what was checked" and "what is uploaded" are the same bytes by construction, not by hope.
3. **Stage.** Registries like npm can stage a package somewhere harmless and install it back. PyPI cannot: GitHub Packages has no PyPI registry, and TestPyPI never accepts a file name twice, so it would burn the real version. So the *stage is the checks themselves*, run on the exact files that will be uploaded: do they hold every module in the source tree, and do they install and run from a clean environment, on every Python you support?
4. **Approve.** A person decides, after the stage is green, behind a protected environment. This is a repository setting, not something an action can do for you.
5. **Publish, then read back.** The upload is the only step that cannot be undone, so it is followed by looking at the result the way a user would: does the index list the version, with the hashes that were built? Do the URLs serve those bytes? Does `pip` resolve and install them? Is there provenance? A red read-back means *look at the release*, never *run it again*.
6. **Rehearse.** A manual run defaults to a dry run: build and stage, upload nothing. A rehearsal upload to TestPyPI goes under a throwaway version (`1.1.0.dev10101`), so nothing real is used up and nothing can be mistaken for a release.

## Fail closed

Every check is written so that the absence of a thing is a failure, not a pass:

- an empty or malformed fingerprint never verifies (a skipped job's missing output would otherwise pass a comparison to "nothing");
- an empty directory is not fingerprinted ("a digest of nothing" is a digest);
- an empty version, a missing changelog entry and an absent release tag are each their own error;
- `pip` not finding the version yet is *retried*; a hash that differs is *final*: waiting does not fix wrong bytes;
- a symbolic link in the files is refused rather than followed.

## Design rules for the actions themselves

- **Composite actions, not reusable workflows.** A composite action runs inside the caller's job, so the caller's OIDC identity, `permissions` and `environment` are untouched. A reusable workflow is a separate job in a separate file, which is exactly what trusted publishing's matching on "which workflow ran" is least comfortable with ([details](trusted-publishing.md)). The upload step and its permissions stay in *your* workflow.
- **No action uses another action.** An action here has only `run` steps. Its supply chain is this repository's `lib/` and the runner's `bash` and `python3`; there is nothing to pin inside it.
- **Inputs reach scripts as environment variables, never as text in a shell command.** A version that contained `$(...)` or `; rm -rf` is an inert string, not code. Expressions appear in `env:` only; none is ever inside a `run:` body. A test enforces it for every action.
- **Standard-library Python.** Each script is one file with no dependencies, runs on the runner's own `python3`, and is the same code the tests import and run.
- **Small enough to read.** An action is a screenful of YAML around a script a person can read in ten minutes. If one needs to be bigger, it should probably be two.
- **Pinned by commit by their consumers, and tested to a standard that makes that safe.** See [Testing](testing.md).

## What this does not do

- It is not a security boundary against a compromised build job. The fingerprint is computed in the build job, so a build that is already malicious can fingerprint whatever it likes. What it rules out is *accidental or mid-pipeline* substitution: a different artifact, a re-run that rebuilt, a download that went wrong. The read-back's provenance check is what ties the upload to a workflow run and a commit.
- It does not stage inside the registry. A test in an environment that is not PyPI is a test of something else.
- Version 0.1 handles pure-Python packages with a single wheel. Extension modules and per-platform wheels need a different install check.
- It does not replace your tests. It checks that the package you tested is the package you ship.

## Vocabulary

| Term            | Meaning                                                                                                           |
| --------------- | ----------------------------------------------------------------------------------------------------------------- |
| **Fingerprint** | `sha256-` plus the SHA-256 of a manifest of `<sha256>  <path>` lines; covers names, content and the set of files. |
| **Stage**       | The checks on the exact files to be uploaded, before anyone approves.                                             |
| **Read back**   | Looking at what the index now serves, after the upload, as a user would.                                          |
| **Rehearsal**   | A run that goes through the whole pipeline without producing a real release.                                      |
| **Dry run**     | A rehearsal that stops before any upload.                                                                         |
