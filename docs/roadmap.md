# Roadmap

Nothing here is promised or dated. It is the order in which things will be built if the need arrives, and a list of things that are deliberately not.

## Next

- **`node/verify-published`**: the npm read-back (registry listing, integrity, provenance, install in a clean project), generalizing `scripts/registry.mjs` from conclude. Plus a template for publishing an npm package.
- **`bash/setup-bash`**: build a pinned Bash from source with a checked hash, for repositories that need a newer Bash than the runner's, generalizing conclude's `install-bash.sh`.
- **`github-release/verify-assets`**: the same read-back for a GitHub Release that ships files and their checksums (what conclude's Bash release does).
- **A template for `release.yml` of an action repository**, once there is a second one.

## Maybe

- **Reusable CI workflows**, if a second package has the same shape as the first. A reusable workflow is fine for CI (nothing in CI needs an OIDC identity); it is publishing that needs the composite design. Not worth abstracting from one example.
- **`uses: $/path`** for this repository's own actions in its own workflows, which `zizmor` now prefers over `./path`, once it has been tried on a real run (`.github/zizmor.yml` says where).
- **Online `zizmor`** audits in CI beyond the offline ones, with a token.
- **Immutable releases** on this repository, if the setting is available, so a published tag cannot be moved even by its owner.

## No

- **A stage that uploads to a real registry** for the real version. On PyPI that burns the version.
- **Actions that publish.** The upload and its permissions stay in the consumer's workflow ([why](trusted-publishing.md)).
- **Anything that stores a token.** Trusted publishing or nothing.
- **Actions that use other actions.** The supply chain of an action here stays at zero.
