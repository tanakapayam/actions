# Trusted publishing, and why the upload stays in your workflow

PyPI (and TestPyPI) can publish without a stored token: the upload step proves who it is with a short-lived OpenID Connect token that GitHub issues to the running job, and the index checks the token against a *trusted publisher* you registered for the project. No secret exists to leak.

## Registering a publisher

On the index (<https://pypi.org/manage/project/PACKAGE/settings/publishing/>, or TestPyPI's equivalent; for a project that does not exist yet, use *pending publishers* in your account settings) add a GitHub publisher with:

| Field         | Value                                                                         |
| ------------- | ----------------------------------------------------------------------------- |
| Owner         | your GitHub user or organization                                              |
| Repository    | the repository that holds the workflow                                        |
| Workflow name | the **file name** of the workflow that uploads, such as `python-publish.yml`  |
| Environment   | the environment the upload job runs in, such as `pypi` (optional, but use it) |

Then in the repository: create the environments (`pypi`, and `testpypi` for rehearsals), give `pypi` **required reviewers** (that is the approval gate), and keep `permissions: id-token: write` on the publish jobs and nowhere else.

## Why these are composite actions

A trusted publisher is matched against claims in the token, including which workflow ran. If the upload were inside a reusable workflow that lives in *this* repository, the token would describe a workflow that is not the one you registered.

Reports differ on exactly which claim PyPI compares in that case: a guide on the topic says reusable workflows are not supported as the trusted workflow, a project's write-up of a failing run cites an open warehouse issue, and a pull request in another project argues it is the caller's file name that counts. The disagreement itself is the reason to avoid the question:

> A **composite action runs inside the caller's job.** The token is the caller's, the claims are the
> caller's, and the registered publisher keeps matching the workflow file you registered.

So the line that uploads (`pypa/gh-action-pypi-publish`), the `id-token: write` permission and the `environment:` stay in your own workflow, and everything around the upload (the guard, the fingerprint checks, the stage, the read-back) is a composite action from here.

## What each job may do

| Job              | `id-token: write` | `environment:`                  | Why                                                                  |
| ---------------- | ----------------- | ------------------------------- | -------------------------------------------------------------------- |
| build, stage     | no                | no                              | They handle files and run code; neither can mint an upload identity. |
| publish-testpypi | yes               | `testpypi`                      | Rehearsal uploads, under throwaway versions.                         |
| publish-pypi     | yes               | `pypi`, with required reviewers | The one irreversible step, behind a person.                          |

Nothing here stores or needs a token. If you see `password:` or a `secrets.` reference in a publish workflow, something has gone back to a long-lived credential.

## npm

npm has its own trusted publishing with the same shape (an OIDC token, a registered workflow). Node support is on the [roadmap](roadmap.md); the same reasoning will apply, and one report says npm accepts a cross-repository reusable workflow because it matches the caller's file. That has not been verified here, so the same composite-action design is planned.
