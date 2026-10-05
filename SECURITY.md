# Security policy

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository (Security, then *Report a vulnerability*). Do not open a public issue. You will get an acknowledgement, and the fix will be released with a note that credits you unless you prefer otherwise.

## What matters here

These actions run in other people's release pipelines, so the interesting vulnerabilities are:

- an input that can become code (shell, Python, or a workflow command) in any action;
- a check that passes when it should fail (an empty value, a missing file, a mismatch that is treated as "not yet");
- a way to make the fingerprint or the read-back accept bytes other than the ones built;
- anything that would make an action store, print or exfiltrate a credential. None of the actions needs a secret, and none should ever be given one.

## What is out of scope

The [concepts](docs/concepts.md#what-this-does-not-do) say what the actions do *not* defend against, most importantly a build job that is already malicious: it can fingerprint whatever it likes.

## Supported versions

The latest release. Pin a commit, read the changelog before moving the pin, and let Dependabot tell you when there is a new one.
