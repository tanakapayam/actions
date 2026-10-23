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

Some lines are *not yet*. They are printed as `<step>: not yet: <reason> (attempt <n> of <m>; looking again in <s>s)` while it waits, and `<step>: there on attempt <n> of <m>` when the step gets there after one or more of them. A `not yet` line is not a failure: a fresh upload shows up on the index's pages, and then on the one `pip` reads, a little at a time.

The reasons:

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

## `ci/all-green`

| You see | It means | Do  |
| ------- | -------- | --- |
| `needs is not JSON (<why>): pass it ${{ toJSON(needs) }}` | The `needs` input is not the JSON of the `needs` context, often because it was typed by hand or left out. | Write `needs: ${{ toJSON(needs) }}` exactly. |
| `needs must be the JSON of the needs context: an object with a result for each job` | The value is JSON but not shaped like the `needs` context. | Pass `toJSON(needs)`, not a list of names. |
| `needs is empty: this job waits for nothing, so it checks nothing` | The calling job has no `needs:`, so there was nothing to check. | List the jobs to wait for under `needs:`. |
| `allow-skipped names <name>, which is not one of the jobs waited for (<jobs>)` | A name in `allow-skipped` is not in `needs:`, usually a typo, and a typo would allow nothing and hide that. | Fix the name, or add the job to `needs:`. |
| `not every job succeeded: <job> <result>` | A job failed, was cancelled, or was skipped without being allowed. | Open that job. If a skip is normal (a job that runs only on some events), name it in `allow-skipped`. |

## `python/supported-versions`

| You see | It means | Do  |
| ------- | -------- | --- |
| `<file> does not exist.` | The `pyproject` path is wrong. | Check `pyproject:`, which is relative to the workspace (did a checkout step run first?). |
| `<file> is not valid TOML (<why>).` | The file cannot be parsed. | Fix the syntax the message points at. |
| `<file> has no [project] table.` | There is no `[project]` table to read classifiers from. | Add one, or point `pyproject:` at the right file. |
| `<file> lists no 'Programming Language :: Python :: 3.x' classifiers, so there is no list of versions to test: add one for each version you support.` | There are no classifiers, so there is nothing to build a matrix from. | Add a `Programming Language :: Python :: 3.x` classifier for each version you support. |
| `classifier Python <versions> is outside requires-python '<spec>': remove the classifier, or widen requires-python.` | A classifier claims a version that `requires-python` rules out. | Remove the classifier, or widen `requires-python`. |
| `requires-python '<spec>' admits Python <versions>, which no classifier lists: raise requires-python, or add the classifiers and test them.` | `requires-python` allows a version that is not tested, so users can install where nothing was checked. | Raise `requires-python`, or add the classifiers so the version is tested. |

A `::warning::` (not a failure) says `requires-python '<spec>' was not understood` when the specifier is not a simple one (`>=3.11`, `>=3.11,<3.15`); the classifiers are still used, but the two are not compared.

## `workflow/policy`

Each finding is an annotation on the line it is about, titled with its rule, for example `::error file=.github/workflows/ci.yml,line=12,title=pinned-actions::<message>`. The message starts with what was found.

| You see | It means | Do  |
| ------- | -------- | --- |
| `<uses> is not pinned to a commit (owner/repo@<40 hex> # v1.2.3)` | A tag or branch can move, so the code that runs can change without a change here (`pinned-actions`). | Pin the 40-hex commit and keep the version in a comment. |
| `<uses> has no version comment (# v1.2.3) saying what the commit is` | A bare commit says nothing to the reader or to an updater (`pinned-actions`). | Add `# v1.2.3` after the commit. |
| `<uses> is a container image without a digest (image@sha256:<64 hex>)` | An image tag can move (`pinned-actions`). | Pin the image by digest. |
| `job <job> runs on <label>, which moves under you: name a version, such as ubuntu-24.04` | `latest` changes under you on the provider's schedule (`pinned-runners`). | Name a version. A `${{ matrix.<key> }}` label is checked through the matrix. |
| `the workflow has no top-level permissions, so its token gets the repository's default: add 'permissions: contents: read'` | The token gets whatever the repository default is (`read-only-token`). | Add `permissions: contents: read` at the top. |
| `the default permissions are <value>: use 'contents: read' and give a job more only where it needs it` | The top-level permissions are not a read-only map (`read-only-token`). | Use `contents: read` on top, and grant more per job. |
| `the default permissions include <scopes>: keep the top level to 'contents: read' and give a job more only where it needs it` | Every job gets the extra scopes (`read-only-token`). | Move them to the jobs that need them. |
| `job <job> has no timeout-minutes, so a hang runs for six hours` | A stuck job holds a runner and a check (`job-timeouts`). | Set `timeout-minutes:`. |
| `actions/checkout keeps the token in the clone unless it is given 'persist-credentials: false'` | Later steps could read the token from the clone (`checkout-credentials`). | Add `persist-credentials: false` to the checkout's `with:`. |
| `uses secrets.<name>: publish with trusted publishing, and do not keep a token that could leak` | A stored secret can leak, and one that publishes is the thing trusted publishing replaces (`no-stored-secrets`). | Use trusted publishing, or add the name to `allow-secrets` if it is meant. |
| `secrets: inherit hands every secret to the called workflow` | The called workflow gets every secret (`no-stored-secrets`). | Pass the secrets it needs by name. |
| `id-token: write at the top level gives every job an identity it can show to a registry` | Every job can publish as this workflow (`oidc-jobs`). | Grant it on the publishing job only. |
| `job <job> may write id-token but is not one of the jobs allowed to (<jobs>)` | A job that is not a publisher has an identity (`oidc-jobs`). | Remove it, or list the job in `id-token-jobs`. |
| `the workflow has no concurrency group, so two runs of it can overlap` | Two runs can race (`concurrency`, off by default). | Add a `concurrency:` group, or leave the rule out. |

These findings are about the workflow itself, with the rule `parse`:

| You see | It means | Do  |
| ------- | -------- | --- |
| `cannot be checked, so it is not trusted: <why>` | The file uses YAML the checker's reader will not guess at (the reasons are below). A file it cannot read is a failure, never a skip. | Write it in the plain block style the message asks for. |
| `is not a workflow: there is no top-level 'jobs'` | The file under the path is not a workflow. | Move it out of the directory, or point `path:` at the workflows. |

The reader is deliberately small and refuses what it would have to guess. Its reasons, each with a line number:

| You see | It means | Do  |
| ------- | -------- | --- |
| `a tab is used for indentation; YAML indents with spaces` | A tab in the indentation. | Use spaces. |
| `a second document in one file is not supported` | A `---` line starts a second document. | Keep one workflow per file. |
| `a complex key, anchor, alias, tag or merge key is not supported` | A `? key`, `&anchor`, `*alias`, `!tag` or `<<` key. | Write the value out. |
| `an anchor, alias or tag is not supported` | Anchors, aliases and tags in a value. | Write the value out. |
| `the key <key> appears twice in one mapping` | A repeated key, where YAML parsers disagree on which wins. | Remove one. |
| `unexpected content: is the indentation consistent?` | Lines that do not line up. | Fix the indentation. |
| `unexpected indentation` | A line indented further than its parent allows. | Fix the indentation. |
| `expected 'key: value', found <text>` | A line that is neither a key nor a list item. | Fix the line. |
| `expected ':' after a quoted key` | A quoted key without its colon. | Add it. |
| `a plain value that contains ': ' is ambiguous: quote it` | A plain value with `: ` in it. | Quote the value. |
| `a sequence entry is not allowed here: quote the value` | A `- ` where a value is expected. | Quote the value. |
| `<value> is a number or date this reader does not model: quote it` | Dates, hex, octal and the like, which parsers read differently. | Quote the value. |
| `a sequence inside a sequence on one line is not supported` | `- - x`. | Put each on its own line. |
| `unexpected text after a quoted string` | Text after a closing quote. | Fix the quoting. |
| `a quoted string that does not close on its line is not supported` | A quoted string over several lines. | Keep it on one line, or use `\|` or `>`. |
| `the escape \<char> in a double-quoted string is not supported` | An escape the reader does not model. | Use single quotes or another spelling. |
| `cannot read the block scalar header <header>` | A `\|` or `>` header with something unusual after it. | Use `\|`, `\|-`, `>` or `>-`. |
| `a flow collection that does not close on its line is not supported` | A `[...]` or `{...}` over several lines. | Write it in block style. |
| `a flow sequence that does not close on its line is not supported` | A `[...]` over several lines. | Write it in block style. |
| `a flow mapping that does not close on its line is not supported` | A `{...}` over several lines. | Write it in block style. |
| `unexpected text after a flow collection` | Text after the closing bracket. | Fix the line. |

One more reason, kept out of the table because it contains a pipe: `a plain value that continues on the next line is not supported: quote it or use |`. Quote the value, or write it as a block scalar.

Errors about the call itself, which stop the check before any file is read:

| You see | It means | Do  |
| ------- | -------- | --- |
| `<path> does not exist.` | The `path` is wrong. | Check `path:`, relative to the workspace (did a checkout step run first?). |
| `no workflow files (*.yml, *.yaml) under <path>.` | Nothing to check, which is a failure and never a pass. | Check `path:`. |
| `unknown rule <name>; the rules are <rules>.` | A name in `rules` is not a rule (a typo would otherwise disable a check). | Use the names in the list. |

## Where the messages are shown

- In the step's log, as `::error::` lines.
- As a red annotation on the run's page.
- In the job summary, under a heading such as `❌ verify-install failed`, with the message in full.
- A pass is a short summary too: `✅ Stage: <project> <version> on Python <version>`, listing what was
  checked.
