#!/usr/bin/env python3
"""Hold GitHub Actions workflows to a few rules that keep a release pipeline trustworthy
(standard library only).

    workflow_policy.py [PATH ...] [--rules a,b] [--id-token-jobs x,y] [--allow-secrets A,B]

PATH is a workflows directory (default ``.github/workflows``) or a workflow file. The rules:

  pinned-actions       every ``uses:`` is a commit, ``owner/repo@<40 hex> # v1.2.3`` (a local
                       ``./`` action and a ``docker://`` image with a digest are fine)
  pinned-runners       no ``runs-on`` label, also inside a matrix, says ``latest``
  read-only-token      the workflow's default token is ``contents: read`` and nothing more
  job-timeouts         every job that runs steps has a ``timeout-minutes``
  checkout-credentials every ``actions/checkout`` sets ``persist-credentials: false``
  no-stored-secrets    no ``secrets.NAME`` except those allowed, and no ``secrets: inherit``
  oidc-jobs            ``id-token: write`` only in the jobs named by --id-token-jobs
  concurrency          the workflow has a ``concurrency`` group (off unless asked for)

Standard-library Python has no YAML reader, so this file carries a small one for the block-style
YAML that workflows are written in. It does not guess: anything it does not understand (anchors,
tags, a flow collection or a quoted string that runs over several lines) is a finding, not a
skipped file, so a workflow can never pass because it was not read.
"""

import argparse
import os
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RULES = (
    "pinned-actions",
    "pinned-runners",
    "read-only-token",
    "job-timeouts",
    "checkout-credentials",
    "no-stored-secrets",
    "oidc-jobs",
    "concurrency",
)
DEFAULT_RULES = tuple(rule for rule in RULES if rule != "concurrency")


class PolicyError(Exception):
    """The checker was asked something it cannot do; the message says what."""


class YamlError(Exception):
    """The YAML cannot be read by this reader; ``line`` is where."""

    def __init__(self, message: str, line: int) -> None:
        super().__init__(message)
        self.line = line


# --- a small, fail-closed reader for block-style YAML --------------------------------------------


class Map(dict[str, Any]):
    """A mapping that remembers the line each key was written on."""

    def __init__(self, line: int) -> None:
        super().__init__()
        self.line = line
        self.lines: dict[str, int] = {}


class Seq(list[Any]):
    """A sequence that remembers the line each item was written on."""

    def __init__(self, line: int) -> None:
        super().__init__()
        self.line = line
        self.lines: list[int] = []


NULL = {"~", "null", "Null", "NULL"}
TRUE = {"true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"}
FALSE = {"false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF"}
INT = re.compile(r"[-+]?(?:0|[1-9][0-9]*)")
FLOAT = re.compile(r"[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+][0-9]+)?")
# Plain scalars that YAML 1.1 reads as something this reader does not model (octal and hex
# numbers, digit separators, dates, sexagesimal numbers, infinity): refused rather than guessed.
SPECIAL = re.compile(
    r"[-+]?0[0-9_xXoObB][0-9a-fA-F_]*"
    r"|[-+]?[0-9][0-9_]*_[0-9_]*"
    r"|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}.*"
    r"|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+(?:\.[0-9_]*)?"
    r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN)"
)


def typed(text: str, line: int) -> Any:
    """A plain scalar as the YAML types a workflow uses give it; strings otherwise."""
    if text in NULL or text == "":
        return None
    if text in TRUE:
        return True
    if text in FALSE:
        return False
    if INT.fullmatch(text):
        return int(text)
    if FLOAT.fullmatch(text):
        return float(text)
    if SPECIAL.fullmatch(text):
        raise YamlError(f"{text} is a number or date this reader does not model: quote it", line)
    return text


class Reader:
    """Reads one YAML document, one line at a time."""

    def __init__(self, text: str) -> None:
        self.rows = text.replace("\r\n", "\n").split("\n")
        for number, row in enumerate(self.rows, 1):
            if "\t" in row[: len(row) - len(row.lstrip(" \t"))]:
                raise YamlError("a tab is used for indentation; YAML indents with spaces", number)
        self.i = 0  # index of the next row to read

    # -- rows -----------------------------------------------------------------------------------

    def significant(self) -> tuple[int, int, str] | None:
        """``(row index, indent, content)`` of the next row that is not blank or a comment."""
        j = self.i
        while j < len(self.rows):
            row = self.rows[j]
            content = row.strip()
            if content and not content.startswith("#"):
                return j, len(row) - len(row.lstrip(" ")), content
            j += 1
        return None

    # -- the document ---------------------------------------------------------------------------

    def document(self) -> Any:
        first = self.significant()
        if first is not None and first[2] == "---":
            self.i = first[0] + 1
        first = self.significant()
        if first is None:
            return None
        value = self.block(first[1])
        rest = self.significant()
        if rest is not None:
            if rest[2] in {"---", "..."}:
                raise YamlError("a second document in one file is not supported", rest[0] + 1)
            raise YamlError("unexpected content: is the indentation consistent?", rest[0] + 1)
        return value

    def block(self, indent: int) -> Any:
        found = self.significant()
        assert found is not None
        _, at, content = found
        if at != indent:
            raise YamlError("unexpected indentation", found[0] + 1)
        if content == "-" or content.startswith("- "):
            return self.sequence(indent)
        return self.mapping(indent)

    # -- mappings and sequences -----------------------------------------------------------------

    def mapping(self, indent: int) -> Map:
        found = self.significant()
        assert found is not None
        result = Map(found[0] + 1)
        while True:
            found = self.significant()
            if found is None or found[1] != indent:
                break
            index, _, content = found
            if content in {"---", "..."}:
                raise YamlError("a second document in one file is not supported", index + 1)
            if content == "-" or content.startswith("- "):
                break
            line = index + 1
            if content.startswith(("? ", "&", "*", "!", "<<")):
                raise YamlError(
                    "a complex key, anchor, alias, tag or merge key is not supported", line
                )
            key, rest = split_key(content, line)
            if key in result:
                raise YamlError(f"the key {key!r} appears twice in one mapping", line)
            result.lines[key] = line
            self.i = index + 1
            result[key] = self.value(rest, indent, line, in_mapping=True)
        return result

    def sequence(self, indent: int) -> Seq:
        found = self.significant()
        assert found is not None
        result = Seq(found[0] + 1)
        while True:
            found = self.significant()
            if found is None or found[1] != indent:
                break
            index, _, content = found
            if content in {"---", "..."}:
                raise YamlError("a second document in one file is not supported", index + 1)
            if not (content == "-" or content.startswith("- ")):
                break
            line = index + 1
            rest = content[1:].lstrip(" ")
            row = self.rows[index]
            offset = len(row) - len(row.lstrip(" ")) + len(content) - len(rest)
            result.lines.append(line)
            if rest == "" or rest.startswith("#"):
                self.i = index + 1
                result.append(self.value("", indent, line, in_mapping=False))
            elif rest.startswith("- ") or rest == "-":
                raise YamlError("a sequence inside a sequence on one line is not supported", line)
            elif looks_like_mapping(rest):
                # `- key: value`: the first key sits on the dash's line; the rest line up under it
                self.rows[index] = " " * offset + rest
                result.append(self.mapping(offset))
            else:
                self.i = index + 1
                result.append(self.value(rest, indent, line, in_mapping=False))
        return result

    # -- values ---------------------------------------------------------------------------------

    def value(self, rest: str, parent_indent: int, line: int, in_mapping: bool) -> Any:
        rest = rest.strip()
        if rest.startswith("#"):
            rest = ""
        if rest == "":
            follow = self.significant()
            if follow is None:
                return None
            _, at, content = follow
            is_dash = content == "-" or content.startswith("- ")
            if at > parent_indent:
                return self.block(at)
            if in_mapping and at == parent_indent and is_dash:
                return self.sequence(at)
            return None
        if rest[0] in "&*!":
            raise YamlError("an anchor, alias or tag is not supported", line)
        if rest[0] in "|>":
            return self.block_scalar(rest, parent_indent, line)
        if rest[0] in "\"'":
            text, after = quoted(rest, line)
            if after and not after.startswith("#") and not after.startswith(" #"):
                raise YamlError("unexpected text after a quoted string", line)
            return text
        if rest[0] in "[{":
            return flow(strip_comment(rest), line)
        text = strip_comment(rest)
        follow = self.significant()
        if (
            follow is not None
            and follow[1] > parent_indent
            and not (follow[2] == "-" or follow[2].startswith("- "))
        ):
            raise YamlError(
                "a plain value that continues on the next line is not supported: quote it or use |",
                line,
            )
        if text == "-" or text.startswith("- "):
            raise YamlError("a sequence entry is not allowed here: quote the value", line)
        if text.endswith(":") or ": " in text:
            raise YamlError("a plain value that contains ': ' is ambiguous: quote it", line)
        return typed(text, line)

    def block_scalar(self, header: str, parent_indent: int, line: int) -> str:
        match = re.fullmatch(r"([|>])([-+]?)\s*(?:#.*)?", header)
        if match is None:
            raise YamlError(f"cannot read the block scalar header {header!r}", line)
        style, chomp = match.group(1), match.group(2)
        body: list[str] = []
        block_indent: int | None = None
        j = self.i
        while j < len(self.rows):
            row = self.rows[j]
            if row.strip() == "":
                body.append("")
                j += 1
                continue
            at = len(row) - len(row.lstrip(" "))
            if block_indent is None:
                if at <= parent_indent:
                    break
                block_indent = at
            if at < block_indent:
                break
            body.append(row[block_indent:])
            j += 1
        # blank rows at the end belong to the chomping, not to the text
        trailing = 0
        while body and body[-1] == "":
            body.pop()
            trailing += 1
        self.i = j
        if not body:
            return ""
        text = "\n".join(body) if style == "|" else fold(body)
        if chomp == "-":
            return text
        if chomp == "+":
            return text + "\n" * (1 + trailing)
        return text + "\n"


def fold(lines: list[str]) -> str:
    """The text of a ``>`` block: a single line break becomes a space, a blank line stays a break,
    and a more-indented line keeps its breaks."""
    out = []
    for number, row in enumerate(lines):
        if number == 0:
            out.append(row)
        elif row == "":
            out.append("\n")
        elif lines[number - 1] == "":
            out.append(row)
        elif lines[number - 1].startswith(" ") or row.startswith(" "):
            out.append("\n" + row)
        else:
            out.append(" " + row)
    return "".join(out)


def strip_comment(text: str) -> str:
    """A plain scalar without its trailing ``# comment``."""
    cut = re.search(r"\s#", text)
    return (text[: cut.start()] if cut else text).rstrip()


def quoted(text: str, line: int) -> tuple[str, str]:
    """``(value, what follows)`` for a quoted scalar that closes on this line."""
    quote = text[0]
    out = []
    i = 1
    while i < len(text):
        char = text[i]
        if quote == "'" and char == "'":
            if text[i + 1 : i + 2] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), text[i + 1 :].strip()
        if quote == '"':
            if char == "\\":
                escape = text[i + 1 : i + 2]
                mapping = {
                    "n": "\n",
                    "t": "\t",
                    '"': '"',
                    "\\": "\\",
                    "/": "/",
                    "r": "\r",
                    "0": "\0",
                    " ": " ",
                }
                if escape not in mapping:
                    raise YamlError(
                        f"the escape \\{escape} in a double-quoted string is not supported", line
                    )
                out.append(mapping[escape])
                i += 2
                continue
            if char == '"':
                return "".join(out), text[i + 1 :].strip()
        out.append(char)
        i += 1
    raise YamlError("a quoted string that does not close on its line is not supported", line)


def split_key(content: str, line: int) -> tuple[str, str]:
    """``(key, the rest of the line)`` for a ``key: value`` line."""
    if content[0] in "\"'":
        key, after = quoted(content, line)
        if not after.startswith(":"):
            raise YamlError("expected ':' after a quoted key", line)
        return key, after[1:]
    match = re.match(r"(.+?)\s*:(?=\s|$)\s*(.*)$", content)
    if match is None:
        raise YamlError(f"expected 'key: value', found {content!r}", line)
    return match.group(1), match.group(2)


def looks_like_mapping(text: str) -> bool:
    """Whether the text after ``- `` starts a ``key: value`` mapping and not a scalar."""
    if text[0] in "[{|>&*!#":
        return False
    if text[0] in "\"'":
        try:
            _, after = quoted(text, 0)
        except YamlError:
            return False
        return after.startswith(":")
    return bool(re.match(r"[^\s:][^:]*?:(?:\s|$)", text))


def flow(text: str, line: int) -> Any:
    """A flow collection written on one line: ``[a, b]`` or ``{a: 1, b: [2, 3]}``."""
    pos = 0

    def skip() -> None:
        nonlocal pos
        while pos < len(text) and text[pos] == " ":
            pos += 1

    def scalar(stops: str) -> Any:
        nonlocal pos
        skip()
        if pos < len(text) and text[pos] in "\"'":
            value, after = quoted(text[pos:], line)
            pos = len(text) - len(after)
            return value
        start = pos
        while pos < len(text) and text[pos] not in stops:
            pos += 1
        raw = text[start:pos].strip()
        if raw and raw[0] in "&*!":
            raise YamlError("an anchor, alias or tag is not supported", line)
        return typed(raw, line)

    def item() -> Any:
        nonlocal pos
        skip()
        if pos >= len(text):
            raise YamlError(
                "a flow collection that does not close on its line is not supported", line
            )
        if text[pos] == "[":
            pos += 1
            out = Seq(line)
            skip()
            while pos < len(text) and text[pos] != "]":
                out.append(item())
                out.lines.append(line)
                skip()
                if pos < len(text) and text[pos] == ",":
                    pos += 1
                    skip()
            if pos >= len(text):
                raise YamlError(
                    "a flow sequence that does not close on its line is not supported", line
                )
            pos += 1
            return out
        if text[pos] == "{":
            pos += 1
            result = Map(line)
            skip()
            while pos < len(text) and text[pos] != "}":
                key = scalar(":,}")
                skip()
                value: Any = None
                if pos < len(text) and text[pos] == ":":
                    pos += 1
                    value = item()
                result[str(key)] = value
                result.lines[str(key)] = line
                skip()
                if pos < len(text) and text[pos] == ",":
                    pos += 1
                    skip()
            if pos >= len(text):
                raise YamlError(
                    "a flow mapping that does not close on its line is not supported", line
                )
            pos += 1
            return result
        return scalar(",]}")

    value = item()
    skip()
    if pos != len(text):
        raise YamlError("unexpected text after a flow collection", line)
    return value


def parse(text: str) -> Any:
    """The YAML document in ``text``, or YamlError if this reader cannot read it faithfully."""
    return Reader(text).document()


# --- the rules -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    rule: str
    message: str


PIN = re.compile(r"[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}")
VERSION_COMMENT = re.compile(r"\s#\s*v\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.]+)?\s*$")
DOCKER_PIN = re.compile(r"docker://\S+@sha256:[0-9a-f]{64}")
SECRET = re.compile(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)")
MATRIX_REFERENCE = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")


def jobs_of(document: Any) -> Map:
    jobs = document.get("jobs") if isinstance(document, Map) else None
    return jobs if isinstance(jobs, Map) else Map(1)


def steps_of(job: Any) -> Iterator[Map]:
    steps = job.get("steps") if isinstance(job, Map) else None
    if isinstance(steps, list):
        yield from (step for step in steps if isinstance(step, Map))


def check_pinned_actions(file: str, document: Any, rows: list[str]) -> Iterator[Finding]:
    def places() -> Iterator[tuple[str, int]]:
        for job in jobs_of(document).values():
            if isinstance(job, Map) and isinstance(job.get("uses"), str):
                yield job["uses"], job.lines["uses"]
            for step in steps_of(job):
                if isinstance(step.get("uses"), str):
                    yield step["uses"], step.lines["uses"]

    for uses, line in places():
        if uses.startswith("./"):
            continue
        if uses.startswith("docker://"):
            if not DOCKER_PIN.fullmatch(uses):
                yield Finding(
                    file,
                    line,
                    "pinned-actions",
                    f"{uses} is a container image without a digest (image@sha256:<64 hex>)",
                )
            continue
        if not PIN.fullmatch(uses):
            yield Finding(
                file,
                line,
                "pinned-actions",
                f"{uses} is not pinned to a commit (owner/repo@<40 hex> # v1.2.3)",
            )
        elif not VERSION_COMMENT.search(rows[line - 1]):
            yield Finding(
                file,
                line,
                "pinned-actions",
                f"{uses} has no version comment (# v1.2.3) saying what the commit is",
            )


def runner_labels(job: Map) -> Iterator[str]:
    runs_on = job.get("runs-on")
    values: list[str] = []
    if isinstance(runs_on, str):
        values = [runs_on]
    elif isinstance(runs_on, list):
        values = [item for item in runs_on if isinstance(item, str)]
    elif isinstance(runs_on, Map):
        labels = runs_on.get("labels")
        if isinstance(labels, str):
            values = [labels]
        elif isinstance(labels, list):
            values = [item for item in labels if isinstance(item, str)]
    for value in values:
        match = MATRIX_REFERENCE.fullmatch(value.strip())
        if match is None:
            yield value
            continue
        strategy = job.get("strategy")
        matrix = strategy.get("matrix") if isinstance(strategy, Map) else None
        if not isinstance(matrix, Map):
            continue
        key = match.group(1)
        listed = matrix.get(key)
        if isinstance(listed, list):
            yield from (str(item) for item in listed)
        included = matrix.get("include")
        if isinstance(included, list):
            yield from (
                str(item[key]) for item in included if isinstance(item, Map) and key in item
            )


def check_pinned_runners(file: str, document: Any, rows: list[str]) -> Iterator[Finding]:
    for name, job in jobs_of(document).items():
        if not isinstance(job, Map):
            continue
        for label in runner_labels(job):
            if "latest" in label:
                line = job.lines.get("runs-on", jobs_of(document).lines[name])
                yield Finding(
                    file,
                    line,
                    "pinned-runners",
                    f"job {name} runs on {label}, which moves under you: "
                    "name a version, such as ubuntu-24.04",
                )


def check_read_only_token(file: str, document: Any, rows: list[str]) -> Iterator[Finding]:
    if not isinstance(document, Map) or "permissions" not in document:
        yield Finding(
            file,
            1,
            "read-only-token",
            "the workflow has no top-level permissions, so its token gets the repository's "
            "default: add 'permissions: contents: read'",
        )
        return
    permissions = document["permissions"]
    line = document.lines["permissions"]
    if permissions is None or permissions == {}:
        return
    if permissions in ("read-all", "write-all") or not isinstance(permissions, Map):
        yield Finding(
            file,
            line,
            "read-only-token",
            f"the default permissions are {permissions!r}: use 'contents: read' and give a "
            "job more only where it needs it",
        )
        return
    extra = {
        name: level for name, level in permissions.items() if (name, level) != ("contents", "read")
    }
    if extra:
        shown = ", ".join(f"{name}: {level}" for name, level in extra.items())
        yield Finding(
            file,
            line,
            "read-only-token",
            f"the default permissions include {shown}: keep the top level to "
            "'contents: read' and give a job more only where it needs it",
        )


def check_job_timeouts(file: str, document: Any, rows: list[str]) -> Iterator[Finding]:
    for name, job in jobs_of(document).items():
        if isinstance(job, Map) and "uses" not in job and "timeout-minutes" not in job:
            yield Finding(
                file,
                jobs_of(document).lines[name],
                "job-timeouts",
                f"job {name} has no timeout-minutes, so a hang runs for six hours",
            )


def check_checkout_credentials(file: str, document: Any, rows: list[str]) -> Iterator[Finding]:
    for job in jobs_of(document).values():
        for step in steps_of(job):
            uses = step.get("uses")
            if isinstance(uses, str) and uses.startswith("actions/checkout@"):
                options = step.get("with")
                if not (isinstance(options, Map) and options.get("persist-credentials") is False):
                    yield Finding(
                        file,
                        step.lines["uses"],
                        "checkout-credentials",
                        "actions/checkout keeps the token in the clone unless it is given "
                        "'persist-credentials: false'",
                    )


def check_no_stored_secrets(
    file: str, document: Any, rows: list[str], allow: Sequence[str]
) -> Iterator[Finding]:
    for number, row in enumerate(rows, 1):
        code = row if not row.lstrip().startswith("#") else ""
        cut = re.search(r"\s#", code)
        code = code[: cut.start()] if cut else code
        for match in SECRET.finditer(code):
            if match.group(1) not in allow:
                yield Finding(
                    file,
                    number,
                    "no-stored-secrets",
                    f"uses secrets.{match.group(1)}: publish with trusted publishing, and do "
                    "not keep a token that could leak",
                )
        if re.match(r"\s*secrets:\s*inherit\b", code):
            yield Finding(
                file,
                number,
                "no-stored-secrets",
                "secrets: inherit hands every secret to the called workflow",
            )


def check_oidc_jobs(
    file: str, document: Any, rows: list[str], allowed: Sequence[str]
) -> Iterator[Finding]:
    top = document.get("permissions") if isinstance(document, Map) else None
    if isinstance(top, Map) and top.get("id-token") == "write":
        yield Finding(
            file,
            document.lines["permissions"],
            "oidc-jobs",
            "id-token: write at the top level gives every job an identity it can show "
            "to a registry",
        )
    for name, job in jobs_of(document).items():
        permissions = job.get("permissions") if isinstance(job, Map) else None
        if (
            isinstance(permissions, Map)
            and permissions.get("id-token") == "write"
            and name not in allowed
        ):
            yield Finding(
                file,
                job.lines["permissions"],
                "oidc-jobs",
                f"job {name} may write id-token but is not one of the jobs allowed to "
                f"({', '.join(allowed) or 'none are'})",
            )


def check_concurrency(file: str, document: Any, rows: list[str]) -> Iterator[Finding]:
    if not isinstance(document, Map) or "concurrency" not in document:
        yield Finding(
            file,
            1,
            "concurrency",
            "the workflow has no concurrency group, so two runs of it can overlap",
        )


def check_file(
    path: Path,
    rules: Sequence[str] = DEFAULT_RULES,
    id_token_jobs: Sequence[str] = (),
    allow_secrets: Sequence[str] = ("GITHUB_TOKEN",),
    shown_as: str | None = None,
) -> list[Finding]:
    """Every finding for one workflow file, in line order."""
    name = shown_as or path.as_posix()
    text = path.read_text(encoding="utf-8")
    rows = text.replace("\r\n", "\n").split("\n")
    try:
        document = parse(text)
    except YamlError as error:
        return [
            Finding(name, error.line, "parse", f"cannot be checked, so it is not trusted: {error}")
        ]
    if not isinstance(document, Map) or "jobs" not in document:
        return [Finding(name, 1, "parse", "is not a workflow: there is no top-level 'jobs'")]
    checks = {
        "pinned-actions": lambda: check_pinned_actions(name, document, rows),
        "pinned-runners": lambda: check_pinned_runners(name, document, rows),
        "read-only-token": lambda: check_read_only_token(name, document, rows),
        "job-timeouts": lambda: check_job_timeouts(name, document, rows),
        "checkout-credentials": lambda: check_checkout_credentials(name, document, rows),
        "no-stored-secrets": lambda: check_no_stored_secrets(name, document, rows, allow_secrets),
        "oidc-jobs": lambda: check_oidc_jobs(name, document, rows, id_token_jobs),
        "concurrency": lambda: check_concurrency(name, document, rows),
    }
    findings = [finding for rule in rules for finding in checks[rule]()]
    return sorted(findings, key=lambda finding: (finding.line, finding.rule))


def workflow_files(paths: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files += sorted([*path.glob("*.yml"), *path.glob("*.yaml")])
        elif path.is_file():
            files.append(path)
        else:
            raise PolicyError(f"{path} does not exist.")
    if not files:
        raise PolicyError(f"no workflow files (*.yml, *.yaml) under {', '.join(map(str, paths))}.")
    return files


def parse_list(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,\n]", text) if item.strip()]


def check_rules(rules: Sequence[str]) -> list[str]:
    unknown = [rule for rule in rules if rule not in RULES]
    if unknown:
        raise PolicyError(f"unknown rule {', '.join(unknown)}; the rules are {', '.join(RULES)}.")
    return list(rules)


def summarize(*lines: str) -> None:
    """Append Markdown to the job summary on GitHub (``$GITHUB_STEP_SUMMARY``), else do nothing."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path(".github/workflows")],
        help="workflow files, or directories of them (default: .github/workflows)",
    )
    parser.add_argument(
        "--rules",
        default=",".join(DEFAULT_RULES),
        metavar="LIST",
        help=f"the rules to check, comma-separated; one or more of {', '.join(RULES)} "
        "(default: all but concurrency)",
    )
    parser.add_argument(
        "--id-token-jobs",
        default="",
        metavar="LIST",
        help="the jobs allowed 'id-token: write', comma-separated (default: none)",
    )
    parser.add_argument(
        "--allow-secrets",
        default="GITHUB_TOKEN",
        metavar="LIST",
        help="secrets a workflow may use, comma-separated (default: %(default)s)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rules = check_rules(parse_list(args.rules))
        files = workflow_files(args.paths)
    except PolicyError as error:
        print(f"::error::{error}", file=sys.stderr)
        summarize("### ❌ Workflow policy", "", str(error))
        return 1
    findings = [
        finding
        for path in files
        for finding in check_file(
            path, rules, parse_list(args.id_token_jobs), parse_list(args.allow_secrets)
        )
    ]
    for finding in findings:
        print(
            f"::error file={finding.file},line={finding.line},title={finding.rule}"
            f"::{finding.message}",
            file=sys.stderr,
        )
    if findings:
        summarize(
            "### ❌ Workflow policy",
            "",
            "| Where | Rule | Finding |",
            "| --- | --- | --- |",
            *[
                f"| `{f.file}:{f.line}` | {f.rule} | {f.message.replace('|', chr(92) + '|')} |"
                for f in findings
            ],
        )
        print(f"{len(findings)} finding(s) in {len(files)} workflow file(s)", file=sys.stderr)
        return 1
    print(f"workflow policy: {len(files)} workflow file(s) pass {', '.join(rules)}")
    summarize(
        "### ✅ Workflow policy",
        "",
        f"{len(files)} workflow file(s) pass {', '.join(rules)}: "
        + ", ".join(f"`{path.as_posix()}`" for path in files),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
