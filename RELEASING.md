# Releasing

A release of this repository is a Git tag and a GitHub Release; there is nothing to upload, because consumers pin a commit. What the release workflow checks is that the commit is worth pinning.

## Before the first release

Once, in the repository's settings:

- **Security, private vulnerability reporting: on.** `SECURITY.md`, the code of conduct and the issue forms all point reporters at it.
- **A ruleset or branch protection on `main`:** require a pull request and the `CI passed` check (the `all-green` job), and block force pushes and deletion.
- **Actions, General: workflow permissions read-only,** which every workflow here asks for anyway.
- **Dependabot: alerts and security updates on.** Version updates are configured in `.github/dependabot.yml`.
- **Immutable releases, if the setting is offered,** so a published tag cannot be moved even by its owner.
- **About: a description and topics,** such as `github-actions`, `pypi`, `release-automation`, `supply-chain-security`, `trusted-publishing`, so people can find it.
- **The repository is public,** which a consumer's public repository needs to use its actions.

Then release as below, and use the new release yourself: migrate [conclude](docs/migrating-conclude.md) and watch its `dry-run`. A first real consumer finds what tests cannot.

## Steps

1. In `CHANGELOG.md`, change the heading to the version and the date: `## [0.2.0] - 2026-11-03` (it says `Unreleased` until now). Move anything that is still pending to a new `## [Unreleased]` section above it.
2. Merge to `main` with CI green.
3. Create a GitHub Release from a new tag `v0.2.0` on that commit. Write the notes from the changelog entry; call out anything that changes an input or an output.
4. The `Release` workflow runs CI again on the tag, then checks that the tag is `v<major>.<minor>.<patch>`, that the changelog has a dated entry for it, and that the commit is on `main`. Its summary prints the exact line to pin.
5. Update the consumers (conclude's workflows, any template copies) to the new commit. Dependabot will propose it, with the cooldown, in a week; do it by hand if you are in a hurry.

## Rules

- **Tags are never moved or deleted.** Someone may have read one as the meaning of a pin. A mistake is fixed by a new version. If the repository's settings offer *immutable releases*, turn them on.
- **A breaking change is a new minor before 1.0 and a new major after**, and is the first line of the changelog entry.
- **Pre-releases** use a `-` suffix (`v0.2.0-rc.1`) and a GitHub Release marked *pre-release*; consumers should not pin them.

## If the workflow fails after the release exists

The release is public, so fix forward: leave the tag, fix `main`, and release the next patch version. If the release was wrong in a way a consumer could pin and be harmed by, edit the release notes to say "do not use", and say what to use instead.
