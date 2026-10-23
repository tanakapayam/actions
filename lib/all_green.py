#!/usr/bin/env python3
"""The one check to require: did every job this one waits for succeed? (standard library only)

    all_green.py --needs "$NEEDS_JSON" [--allow-skipped JOB ...]

``needs`` is GitHub's ``toJSON(needs)``: an object with one entry per job the calling job waits
for, each holding that job's ``result``. Every job must have succeeded. A job that was skipped
counts as a failure unless it is named with --allow-skipped, because a skipped job is how a
required check quietly stops checking. Run it in a job with ``if: always()``, otherwise the
job is skipped as soon as one of the jobs it waits for fails, and a skipped required check
passes on GitHub.
"""

import argparse
import json
import os
import sys
from collections.abc import Collection, Sequence
from typing import Any


class GateError(Exception):
    """The jobs did not all succeed, or the gate was set up wrongly; the message says why."""


def summarize(*lines: str) -> None:
    """Append Markdown to the job summary on GitHub (``$GITHUB_STEP_SUMMARY``), else do nothing."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n\n")


def parse_needs(text: str) -> dict[str, str]:
    """``{job: result}`` from the JSON of the ``needs`` context."""
    try:
        needs: Any = json.loads(text)
    except json.JSONDecodeError as error:
        raise GateError(
            f"needs is not JSON ({error.msg}): pass it ${{{{ toJSON(needs) }}}}"
        ) from None
    if not isinstance(needs, dict) or not all(
        isinstance(job, dict) and isinstance(job.get("result"), str) for job in needs.values()
    ):
        raise GateError(
            "needs must be the JSON of the needs context: an object with a result for each job"
        )
    if not needs:
        raise GateError("needs is empty: this job waits for nothing, so it checks nothing")
    return {name: job["result"] for name, job in needs.items()}


def check(needs_json: str, allow_skipped: Collection[str] = ()) -> tuple[str, dict[str, str]]:
    """Raise GateError unless every job succeeded; return a confirmation and the results."""
    results = parse_needs(needs_json)
    unknown = sorted(set(allow_skipped) - set(results))
    if unknown:
        raise GateError(
            f"allow-skipped names {', '.join(unknown)}, which is not one of the jobs waited for "
            f"({', '.join(sorted(results))})"
        )
    bad = {
        name: result
        for name, result in results.items()
        if result != "success" and not (result == "skipped" and name in allow_skipped)
    }
    if bad:
        shown = ", ".join(f"{name} {result}" for name, result in bad.items())
        raise GateError(f"not every job succeeded: {shown}")
    return f"all {len(results)} job(s) succeeded: {', '.join(results)}", results


def table(results: dict[str, str]) -> list[str]:
    rows = ["| Job | Result |", "| --- | --- |"]
    return rows + [f"| `{name}` | {result} |" for name, result in results.items()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--needs",
        required=True,
        metavar="JSON",
        help="the JSON of the needs context, ${{ toJSON(needs) }}",
    )
    parser.add_argument(
        "--allow-skipped",
        action="append",
        default=[],
        metavar="JOB",
        help="a job whose skipped result is acceptable, such as one that only runs on some events "
        "(repeatable)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        confirmation, results = check(args.needs, args.allow_skipped)
    except GateError as error:
        print(f"::error::{error}", file=sys.stderr)
        try:
            summarize("### ❌ CI did not pass", "", str(error), "", *table(parse_needs(args.needs)))
        except GateError:
            summarize("### ❌ CI gate is set up wrongly", "", str(error))
        return 1
    print(confirmation)
    summarize("### ✅ CI passed", "", *table(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
