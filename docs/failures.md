# What a failure looks like

Every check ends in one of three ways: it passes and says what it checked, it is *not yet* (the index has not caught up, so it waits and looks again), or it fails with a reason. A failure is printed as a GitHub annotation, `::error::<message>`, shown on the run's page and repeated in the job summary. This page lists every message, what it means, and what to do. A test fails if a message in `lib/` is not listed here.

Messages show `<placeholders>` where a value goes.

## `release/guard`

| You see | It means | Do  |
| ------- | -------- | --- |
| `There is no release tag: this check is for a published GitHub Release.` | The guard ran on something other than a release event. | Put `if: github.event_name == 'release'` on its step. |
| `No version was given: the step that reads it from the code found none.` | The `version` input was empty: the step before the guard read nothing. | Check that step's command, and that it has an `id` the guard's `version:` refers to. |
| `The release tag <tag> does not match the package version (<prefix><version>).` | The tag is not exactly the prefix plus the version in the code. | Fix whichever is wrong. A published release's tag can't be moved: delete the release, retag, publish again. |
| `<changelog> does not exist.` | The changelog path is wrong. | Check `changelog:`, which is relative to the workspace. |
| `<changelog> has no entry for <version>.` | There is no `## [<version>]` heading. | Add the entry. |
| `<changelog> still marks <version> as Unreleased; put the date on it.` | The heading says *Unreleased*. | Put the release date on it. |
| `<changelog> must head <version> as '## [<version>] - YYYY-MM-DD', found '## [<version>] <what is there>'.` | `require-date` is on and the heading has no valid ISO date. | Write `## [1.2.3] - 2026-10-04`. |

## `artifact/fingerprint` and `artifact/verify-fingerprint`

| You see | It means | Do  |
| ------- | -------- | --- |
| `<path> does not exist.` | The path to fingerprint or check is wrong. | Check `path:`. In a later job, did the download step put the files there? |
| `<path> holds no files, so there is nothing to fingerprint.` | The directory is empty. | The build produced nothing, or the download failed. |
| `<item> is a symbolic link; a fingerprint covers real files.` | A symlink is among the files. | Fingerprint a directory of real files. |
| `'<value>' is not a fingerprint (expected sha256- and 64 hex digits); was the step that produces it skipped?` | `expected` is empty or malformed, almost always an output that was never set. | Check the output's name in `needs.<job>.outputs`, and that the job that fingerprints ran. |
| `The files are not the ones that were fingerprinted (expected <digest>, here <digest>).` | The files changed since the fingerprint was made. The log lists the files counted here and any hidden files left out. | Compare that list with the one the fingerprint step printed (also on its summary page): the file in one and not the other is the difference. If it is a hidden file, set `include-hidden: "true"` on both actions and `include-hidden-files: true` on the upload. Otherwise never re-run only the failed job to "fix" this: rebuild from the start. |

## `python/verify-install` (the stage)

| You see | It means | Do  |
| ------- | -------- | --- |
| `<dist> is not a directory: dist is where the build left its files.` | The `dist` path is wrong. | Point it at the directory with the wheel and the sdist. |
| `<dist> should hold exactly one wheel and at most one sdist, found <files>` | There are none, several wheels, or several sdists. | Build into a clean directory. Packages with several platform wheels are out of scope. |
| `<name> is not a wheel file name` | A `.whl` file is not named like a wheel. | Rebuild with a standard backend. |
| `the wheel is for <name> but the sdist is for <name>` | The two files are different packages. | They are not from one build: use a clean directory. |
| `the wheel is <version> but the sdist is <version>` | The two files are different versions. | Same: they are not from one build. |
| `cannot find the package under <root>: tried <dirs>. Is source-root the project root (where pyproject.toml is)? If the package is somewhere else, say where with package-dir.` | The package directory is not where the check looked. | Fix `source-root` first (the usual mistake), then `package-dir` or `import-name`. |
| `the distributions do not hold the package:` followed by `the wheel is missing <pkg>/<file>` | A source file is not in the build: the failure this check exists for. | An include/exclude rule, or `.gitignore`, left it out of the build. Fix the packaging. |
| `the wheel has <pkg>/<file>, which is not in the source tree` | The build holds a file the source does not (also for the sdist). | If it is generated on purpose, such as `_version.py`, list it in `allow-extra`. |
| `pip could not install the wheel:` (or `sdist`) | The file does not install. Pip's own message follows. | Read it: usually a missing dependency, or for an sdist a build backend that cannot run. |
| `the installed package failed its smoke test:` | It installed, but the version, the import or `py.typed` is wrong. The reason follows. | The version in the file must equal the built one; the import must come from `site-packages`; set `import-name` if it differs from the distribution name. |
| `<script> failed on the installed package:` | Your own `smoke` script exited non-zero. Its output follows. | Fix the package, or the script. |
| `cannot create a virtual environment with <python>:` | The new environment's `ensurepip` failed. The output follows. | Usually a Python that does not support venvs with pip (some distributions split them out). |

## `python/rehearsal-version`

| You see | It means | Do  |
| ------- | -------- | --- |
| `<file> has no line matching '<pattern>'` | The version is not where, or how, the pattern expects. | Set `file:` and `pattern:`; the default matches `__version__ = "1.2.3"`. |
| `<version> is already a development version` | The version in the file already has `.dev`. | Start from the release version. |
| `run attempt <n> is outside 1..99` | The attempt number does not fit the version scheme. | Start a new run instead of re-running 100 times. |

## `python/verify-published` (the read-back)

Some lines are *not yet*, printed as `<step>: <reason> (attempt <n> of <m>)` while it waits:

| Reason | It means |
| ------ | -------- |
| `<index> lists no <project> <version> yet` | The index has not published the release. |
| `<file> is not listed yet` | One of the two files is not listed yet. |
| `cannot reach <url>: <reason>` | The connection failed (DNS, refused, reset, timed out). It is retried like the rest. |
| `no attestation for <file> yet` | Provenance has not appeared yet. |

When the attempts run out, the failure is `<step>: still not there after <n> attempts: <last reason>`. The default is 20 attempts, 15 seconds apart. Failures that prove the files are *wrong* are final and not retried:

| You see | It means | Do  |
| ------- | -------- | --- |
| `<index> answered <status> for <project> <version>` | The index gave an error other than "not found". | Look at the index's status page, then at the project. |
| `<file> on <index> is not the file that was built (built <digest>, listed <digest>)` | The index lists a different file than the one you built. | **Do not re-run.** Yank the release and publish a fixed version. |
| `the <file> that users download is not the one built` | The URL serves other bytes than were built. | Same. |
| `pip resolved <file>, which was not built here` | `pip` resolves a file that is not one of yours. | Same: look at the project's files on the index. |
| `the <file> that pip resolves is not the one built` | `pip` fetches other bytes than were built. | Same. |
| `pip could not install what the index serves:` | The wheel the index serves does not install. Pip's message follows. | Same: the release is broken for users. |
| `<index> answered <status> for the provenance of <file>` | The provenance endpoint returned an error. | Look at the index's status page. |
| `<file> has an empty provenance record` | The file is attested by nothing. | The upload was not made with trusted publishing, or the index has not recorded it. |

After the upload, a red read-back means *look at the release*, never *run it again*: the upload is finished and cannot be undone. See [the guide](guide.md#if-the-read-back-is-red).

## Where the messages are shown

- In the step's log, as `::error::` lines.
- As a red annotation on the run's page.
- In the job summary, under a heading such as `❌ verify-install failed`, with the message in full.
- A pass is a short summary too: `✅ Stage: <project> <version> on Python <version>`, listing what was
  checked.
