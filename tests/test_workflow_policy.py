"""lib/workflow_policy.py: a fail-closed reader for block YAML, and the rules built on it.

The reader exists because Python's standard library has no YAML parser and these scripts use only
the standard library. So it is held to two promises, each tested hard: on every workflow it can
read it agrees with PyYAML, and on anything it cannot read faithfully it refuses, with the line,
instead of guessing. A workflow that is not read must never pass.
"""

import datetime
from pathlib import Path
from typing import Any

import pytest
import workflow_policy as wp
import yaml

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "workflows" / "conclude"


def py(value: Any) -> Any:
    """PyYAML's reading, with the one thing it does differently on purpose normalized."""
    if isinstance(value, dict):
        return {("on" if key is True else str(key)): py(item) for key, item in value.items()}
    if isinstance(value, list):
        return [py(item) for item in value]
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


def same_as_pyyaml(text: str) -> None:
    assert plain(wp.parse(text)) == py(yaml.safe_load(text))


# --- it agrees with PyYAML on everything real ----------------------------------------------------

REAL = sorted(
    {
        *(ROOT / ".github").glob("**/*.yml"),
        *ROOT.glob("*/*/action.yml"),
        *(ROOT / "templates").glob("*/*.yml"),
        *FIXTURES.glob("*.yml"),
    }
)


@pytest.mark.parametrize("path", REAL, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_real_workflow_and_manifest_reads_exactly_as_pyyaml_reads_it(path):
    same_as_pyyaml(path.read_text(encoding="utf-8"))


def test_there_are_real_samples_to_agree_on():
    assert len(REAL) >= 20 and len(list(FIXTURES.glob("*.yml"))) == 6


# --- and on every construct a workflow is written with -------------------------------------------

CASES = {
    "mapping": "a: 1\nb: two\nc: true\nd:\ne: ~\n",
    "nested": "a:\n  b:\n    c: 1\n  d: 2\ne: 3\n",
    "sequence under a key": "a:\n  - x\n  - y\n",
    "sequence at the key's indent": "a:\n- x\n- y\nb: 1\n",
    "sequence of mappings": "steps:\n  - uses: a@1\n    with:\n      k: v\n  - run: x\n",
    "mapping first key on the dash line": "-   name: a\n    run: b\n-   name: c\n",
    "sequence of sequences' scalars": "a:\n  - 1\n  - 2.5\n  - 'x'\n  - \"y\"\n  - true\n",
    "comments": "# top\na: 1 # trailing\n# between\nb:\n  # inside\n  c: 2\n",
    "document marker": "---\na: 1\n",
    "quoted keys and values": "'a b': 'it''s'\n\"c\": \"x \\\"y\\\" \\\\ z\"\n",
    "a url and a colon without a space": "a: https://example.com/x?y=1\nb: a:b\nc: 'x: y'\n",
    "hash inside a word": "a: abc#def\nb: 'x # y'\n",
    "expressions": "a: ${{ github.event.release.tag_name }}\nb: ${{ matrix.os }}\n",
    "flow sequence": "a: [1, 2, three]\nb: []\nc: [a, [b, c]]\n",
    "flow mapping": "a: {x: 1, y: two}\nb: {}\nc: {k: [1, 2]}\n",
    "flow with quotes": "a: ['x, y', \"z\"]\nb: {'k': 'v'}\n",
    "literal block": "run: |\n  echo a\n  echo b\nnext: 1\n",
    "literal block with blank lines and indent": "run: |\n  a\n\n    b\n\n  c\nnext: 1\n",
    "literal strip": "run: |-\n  a\n  b\n\nnext: 1\n",
    "literal keep": "run: |+\n  a\n\n\nnext: 1\n",
    "folded": "d: >\n  one\n  two\n\n  three\nn: 1\n",
    "folded strip": "d: >-\n  one\n  two\nn: 1\n",
    "folded more indented": "d: >\n  a\n    b\n  c\nn: 1\n",
    "block scalar holding a hash and a colon": "run: |\n  # not a comment\n  x: y\nn: 1\n",
    "block scalar in a sequence": "a:\n  - |\n    text\n  - b\n",
    "block scalar at the end of the file": "run: |\n  last\n",
    "numbers": "a: 1\nb: -2\nc: 3.14\nd: 3.10\ne: 0\nf: 1.5e+3\n",
    "version strings stay strings": "a: 3.10.1\nb: v1.2.3\nc: 1.2.3-rc1\n",
    "booleans and nulls": "a: yes\nb: No\nc: ON\nd: off\ne: null\nf: ~\ng: TRUE\n",
    "key called on": "on:\n  push:\n    branches: [main]\n",
    "empty value then a sibling": "a:\nb: 1\n",
    "nested empty": "a:\n  b:\nc: 1\n",
    "deep and mixed": "a:\n  - b:\n      - c: 1\n        d: [1, 2]\n      - e\n  - f\n",
    "crlf line endings": "a: 1\r\nb:\r\n  - x\r\n",
    "no final newline": "a: 1",
    "blank lines everywhere": "\n\na: 1\n\n\nb:\n\n  c: 2\n\n",
    "indent of four": "a:\n    b:\n        c: 1\n",
    "key with spaces": "some key: v\nother key:\n  x: 1\n",
    "dashes in values": "a: --flag\nb: -x\nc: a - b\n",
}


@pytest.mark.parametrize("name", CASES)
def test_the_reader_agrees_with_pyyaml_on_each_construct(name):
    same_as_pyyaml(CASES[name])


# --- it refuses what it cannot read faithfully, and says where -----------------------------------

REFUSED = {
    "an anchor": ("a: &x 1\nb: 2\n", "anchor"),
    "an alias": ("a: *x\n", "anchor, alias or tag"),
    "a tag": ("a: !!str 1\n", "anchor, alias or tag"),
    "a merge key": ("a:\n  <<: *d\n", "merge key"),
    "a complex key": ("? a\n: b\n", "complex key"),
    "a tab for indentation": ("a:\n\tb: 1\n", "tab"),
    "a second document": ("a: 1\n---\nb: 2\n", "second document"),
    "a second document after a sequence": ("- a\n---\n- b\n", "second document"),
    "a lone dash as a value": ("a: -\n", "sequence entry is not allowed here"),
    "a dash and a word as a value": ("a: - x\n", "sequence entry is not allowed here"),
    "a duplicate key": ("a: 1\nb: 2\na: 3\n", "appears twice"),
    "a quoted string over lines": ('a: "one\n  two"\n', "does not close"),
    "a single-quoted string over lines": ("a: 'one\n  two'\n", "does not close"),
    "a flow sequence over lines": ("a: [1,\n  2]\n", "does not close"),
    "a flow mapping over lines": ("a: {x: 1,\n  y: 2}\n", "does not close"),
    "a plain value over lines": ("a: one\n  two\n", "continues on the next line"),
    "a plain value with a colon": ("a: b: c\n", "ambiguous"),
    "a nested sequence on one line": ("- - a\n", "sequence inside a sequence"),
    "a bad indentation": ("a:\n    b: 1\n  c: 2\n", "unexpected"),
    "text after a quoted string": ('a: "x" y\n', "after a quoted"),
    "a date": ("a: 2026-10-12\n", "number or date"),
    "a hex number": ("a: 0x1F\n", "number or date"),
    "an octal number": ("a: 0755\n", "number or date"),
    "a number with separators": ("a: 1_000\n", "number or date"),
    "a sexagesimal number": ("a: 1:30\n", "number or date"),
    "infinity": ("a: .inf\n", "number or date"),
    "an unknown escape": ('a: "\\q"\n', "escape"),
    "a block scalar header it cannot read": ("a: |2\n  x\n", "block scalar header"),
    "a quoted key without a colon": ("'a' b\n", "expected ':'"),
}


@pytest.mark.parametrize("name", REFUSED)
def test_what_the_reader_cannot_read_faithfully_it_refuses(name):
    text, message = REFUSED[name]
    with pytest.raises(wp.YamlError, match=message) as caught:
        wp.parse(text)
    assert caught.value.line >= 1


def test_a_refusal_names_the_line_of_the_problem():
    with pytest.raises(wp.YamlError) as caught:
        wp.parse("a: 1\nb: 2\nc: &x 3\nd: 4\n")
    assert caught.value.line == 3
    with pytest.raises(wp.YamlError) as caught:
        wp.parse("a:\n  b: 1\n  b: 2\n")
    assert caught.value.line == 3


def test_an_empty_document_is_none_not_an_error():
    assert wp.parse("") is None and wp.parse("# only a comment\n") is None


# --- it remembers where everything is ------------------------------------------------------------


def test_every_key_and_item_knows_its_line():
    document = wp.parse("a: 1\n\nb:\n  - x\n  - y: 1\n    z: 2\n# c\nd:\n  e: 3\n")
    assert document.lines == {"a": 1, "b": 3, "d": 8}
    assert document["b"].lines == [4, 5]
    assert document["b"][1].lines == {"y": 5, "z": 6}
    assert document["d"].lines == {"e": 9}


def test_a_sequence_at_the_keys_indent_keeps_its_lines():
    document = wp.parse("steps:\n- uses: a\n- uses: b\n")
    assert document["steps"].lines == [2, 3] and document["steps"][1].lines == {"uses": 3}


# --- the rules -----------------------------------------------------------------------------------

SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
GOOD = f"""\
name: ok
on: push
permissions:
  contents: read
concurrency:
  group: x
jobs:
  build:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@{SHA} # v7.0.1
        with:
          persist-credentials: false
      - run: echo hi
"""


def findings(tmp_path: Path, text: str, rules=wp.RULES, **options: Any) -> list[wp.Finding]:
    path = tmp_path / "w.yml"
    path.write_text(text, encoding="utf-8")
    return wp.check_file(path, rules, shown_as="w.yml", **options)


def rules_hit(tmp_path: Path, text: str, **options: Any) -> list[tuple[str, int]]:
    return [(f.rule, f.line) for f in findings(tmp_path, text, **options)]


def test_a_workflow_that_follows_every_rule_has_no_findings(tmp_path):
    assert findings(tmp_path, GOOD) == []


def test_unpinned_actions_are_found_with_the_line(tmp_path):
    text = GOOD.replace(f"actions/checkout@{SHA} # v7.0.1", "actions/checkout@v4")
    [finding] = findings(tmp_path, text, ["pinned-actions"])
    assert (finding.rule, finding.line) == ("pinned-actions", 12)
    assert "actions/checkout@v4 is not pinned to a commit" in finding.message


@pytest.mark.parametrize(
    "uses",
    [
        "actions/checkout@main",
        "actions/checkout@3d3c42e",  # abbreviated
        f"actions/checkout@{SHA[:-1]}",  # 39 characters
        "actions/checkout",
        f"actions/checkout@{SHA.upper()}",  # a SHA is lower case
    ],
)
def test_only_a_full_commit_counts_as_a_pin(tmp_path, uses):
    text = GOOD.replace(f"actions/checkout@{SHA} # v7.0.1", f"{uses} # v7.0.1")
    assert [f.rule for f in findings(tmp_path, text, ["pinned-actions"])] == ["pinned-actions"]


@pytest.mark.parametrize("comment", ["", " # latest", " # 7.0.1", " # main"])
def test_a_pin_needs_a_version_comment_saying_what_the_commit_is(tmp_path, comment):
    text = GOOD.replace(f"@{SHA} # v7.0.1", f"@{SHA}{comment}")
    [finding] = findings(tmp_path, text, ["pinned-actions"])
    assert "has no version comment" in finding.message


@pytest.mark.parametrize("comment", [" # v7", " # v7.0.1", " # v1.2.3-rc.1", "  #  v0.1.3"])
def test_the_version_comment_may_be_short_or_a_prerelease(tmp_path, comment):
    text = GOOD.replace(f"@{SHA} # v7.0.1", f"@{SHA}{comment}")
    assert findings(tmp_path, text, ["pinned-actions"]) == []


def test_local_actions_and_digest_pinned_images_are_fine_and_unpinned_images_are_not(tmp_path):
    digest = "a" * 64
    ok = GOOD + f"      - uses: ./ci/all-green\n      - uses: docker://alpine@sha256:{digest}\n"
    assert findings(tmp_path, ok, ["pinned-actions"]) == []
    bad = GOOD + "      - uses: docker://alpine:3.20\n"
    [finding] = findings(tmp_path, bad, ["pinned-actions"])
    assert "container image without a digest" in finding.message


def test_a_reusable_workflow_called_by_a_job_must_be_pinned_too(tmp_path):
    text = GOOD + "  call:\n    uses: someone/repo/.github/workflows/ci.yml@main\n"
    [finding] = findings(tmp_path, text, ["pinned-actions"])
    assert finding.line == 17 and "someone/repo/.github/workflows/ci.yml@main" in finding.message
    local = GOOD + "  call:\n    uses: ./.github/workflows/ci.yml\n"
    assert findings(tmp_path, local, ["pinned-actions"]) == []


@pytest.mark.parametrize("runner", ["ubuntu-latest", "macos-latest", "windows-latest"])
def test_a_runner_that_says_latest_is_found(tmp_path, runner):
    [finding] = findings(tmp_path, GOOD.replace("ubuntu-24.04", runner), ["pinned-runners"])
    assert finding.line == 9 and f"runs on {runner}" in finding.message


def test_latest_is_found_in_a_list_and_in_a_matrix(tmp_path):
    listed = GOOD.replace("runs-on: ubuntu-24.04", "runs-on: [self-hosted, ubuntu-latest]")
    assert rules_hit(tmp_path, listed, rules=["pinned-runners"]) == [("pinned-runners", 9)]
    matrix = GOOD.replace(
        "    runs-on: ubuntu-24.04\n",
        "    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n"
        "        os: [ubuntu-24.04, macos-latest]\n",
    )
    [finding] = findings(tmp_path, matrix, ["pinned-runners"])
    assert "macos-latest" in finding.message
    included = GOOD.replace(
        "    runs-on: ubuntu-24.04\n",
        "    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n        os: [ubuntu-24.04]\n"
        "        include:\n          - os: windows-latest\n",
    )
    assert [f.rule for f in findings(tmp_path, included, ["pinned-runners"])] == ["pinned-runners"]


def test_a_runner_it_cannot_resolve_is_not_guessed_at(tmp_path):
    unknown = GOOD.replace("runs-on: ubuntu-24.04", "runs-on: ${{ inputs.runner }}")
    assert findings(tmp_path, unknown, ["pinned-runners"]) == []


@pytest.mark.parametrize(
    ("block", "found"),
    [
        ("", False),
        ("permissions: {}\n", False),
        ("permissions:\n", False),
        ("permissions:\n  contents: read\n", False),
        ("permissions: read-all\n", True),
        ("permissions: write-all\n", True),
        ("permissions:\n  contents: write\n", True),
        ("permissions:\n  contents: read\n  id-token: write\n", True),
        ("permissions:\n  contents: read\n  packages: read\n", True),
    ],
)
def test_the_default_token_must_be_contents_read_and_no_more(tmp_path, block, found):
    text = GOOD.replace("permissions:\n  contents: read\n", block)
    hit = list(findings(tmp_path, text, ["read-only-token"]))
    assert bool(hit) is found or (block == "" and hit)  # no block at all is a finding too
    if block == "":
        assert "no top-level permissions" in hit[0].message


def test_a_job_may_ask_for_more_than_the_default_where_it_needs_it(tmp_path):
    text = (
        GOOD
        + "  other:\n    runs-on: ubuntu-24.04\n    timeout-minutes: 1\n"
        + "    permissions:\n      contents: write\n    steps:\n      - run: x\n"
    )
    assert findings(tmp_path, text, ["read-only-token"]) == []


def test_a_job_without_a_timeout_is_found_and_a_reusable_call_is_not(tmp_path):
    text = GOOD.replace("    timeout-minutes: 5\n", "")
    assert rules_hit(tmp_path, text, rules=["job-timeouts"]) == [("job-timeouts", 8)]
    call = GOOD + "  call:\n    uses: ./.github/workflows/ci.yml\n"
    assert findings(tmp_path, call, ["job-timeouts"]) == []


@pytest.mark.parametrize(
    "with_block",
    [
        "",
        "        with:\n          fetch-depth: 0\n",
        "        with:\n          persist-credentials: true\n",
    ],
)
def test_a_checkout_must_not_keep_the_credentials(tmp_path, with_block):
    text = GOOD.replace("        with:\n          persist-credentials: false\n", with_block)
    [finding] = findings(tmp_path, text, ["checkout-credentials"])
    assert finding.line == 12 and "persist-credentials: false" in finding.message


def test_a_secret_is_found_unless_it_is_allowed(tmp_path):
    text = (
        GOOD
        + "      - run: echo ${{ secrets.PYPI_TOKEN }}\n"
        + "      - run: echo ${{ secrets.GITHUB_TOKEN }}\n"
    )
    [finding] = findings(tmp_path, text, ["no-stored-secrets"])
    assert finding.line == 16 and "secrets.PYPI_TOKEN" in finding.message
    allowed = findings(
        tmp_path, text, ["no-stored-secrets"], allow_secrets=["GITHUB_TOKEN", "PYPI_TOKEN"]
    )
    assert allowed == []


def test_a_secret_mentioned_only_in_a_comment_is_not_a_use(tmp_path):
    text = GOOD + "      # was: ${{ secrets.OLD }}\n      - run: echo ok # not ${{ secrets.X }}\n"
    assert findings(tmp_path, text, ["no-stored-secrets"]) == []


def test_secrets_inherit_is_found(tmp_path):
    text = GOOD + "  call:\n    uses: ./w.yml\n    secrets: inherit\n"
    [finding] = findings(tmp_path, text, ["no-stored-secrets"])
    assert "secrets: inherit" in finding.message


def test_an_identity_is_only_for_the_jobs_named(tmp_path):
    text = (
        GOOD
        + "  publish:\n    runs-on: ubuntu-24.04\n    timeout-minutes: 1\n"
        + "    permissions:\n      id-token: write\n    steps:\n      - run: x\n"
    )
    [finding] = findings(tmp_path, text, ["oidc-jobs"])
    assert "job publish may write id-token" in finding.message and finding.line == 19
    assert findings(tmp_path, text, ["oidc-jobs"], id_token_jobs=["publish"]) == []
    assert findings(tmp_path, text, ["oidc-jobs"], id_token_jobs=["other"]) != []


def test_an_identity_at_the_top_level_is_never_fine(tmp_path):
    text = GOOD.replace("  contents: read\n", "  contents: read\n  id-token: write\n")
    found = findings(tmp_path, text, ["oidc-jobs"], id_token_jobs=["build"])
    assert [f.rule for f in found] == ["oidc-jobs"] and "top level" in found[0].message


def test_concurrency_is_only_checked_when_asked(tmp_path):
    text = GOOD.replace("concurrency:\n  group: x\n", "")
    assert findings(tmp_path, text, wp.DEFAULT_RULES) == []
    [finding] = findings(tmp_path, text, ["concurrency"])
    assert "no concurrency group" in finding.message


def test_findings_come_in_line_order_across_rules(tmp_path):
    text = GOOD.replace("ubuntu-24.04", "ubuntu-latest").replace(f"@{SHA} # v7.0.1", "@v4")
    text = text.replace("    timeout-minutes: 5\n", "")
    found = findings(tmp_path, text, wp.DEFAULT_RULES)
    assert [(f.line, f.rule) for f in found] == [
        (8, "job-timeouts"),
        (9, "pinned-runners"),
        (11, "pinned-actions"),
    ]


# --- a file that cannot be read is a finding -----------------------------------------------------


def test_a_workflow_the_reader_cannot_read_is_a_finding_not_a_pass(tmp_path):
    [finding] = findings(tmp_path, "on: push\njobs:\n  a: &x\n    runs-on: ubuntu-24.04\n")
    assert finding.rule == "parse" and finding.line == 3
    assert "cannot be checked, so it is not trusted" in finding.message


def test_a_file_that_is_not_a_workflow_is_a_finding(tmp_path):
    [finding] = findings(tmp_path, "name: x\non: push\n")
    assert finding.rule == "parse" and "is not a workflow" in finding.message


# --- the real thing ------------------------------------------------------------------------------

ALL_BUT_NONE = ",".join(wp.RULES)


def test_this_repositorys_own_workflows_hold_to_every_rule_including_concurrency():
    found = [
        f
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        for f in wp.check_file(path, wp.RULES)
    ]
    assert found == []


def test_conclude_real_workflows_hold_to_the_default_rules():
    found = [
        f
        for path in sorted(FIXTURES.glob("*.yml"))
        for f in wp.check_file(
            path,
            wp.DEFAULT_RULES,
            id_token_jobs=["publish-pypi", "publish-testpypi", "production"],
        )
    ]
    assert found == []


def test_conclude_workflows_name_the_jobs_that_publish_or_the_rule_finds_them():
    found = [
        f for path in sorted(FIXTURES.glob("*.yml")) for f in wp.check_file(path, ["oidc-jobs"])
    ]
    assert sorted(f.message.split()[1] for f in found) == [
        "production",
        "publish-pypi",
        "publish-testpypi",
    ]


# --- the command line ----------------------------------------------------------------------------


def write_workflows(tmp_path: Path, **files: str) -> Path:
    directory = tmp_path / ".github" / "workflows"
    directory.mkdir(parents=True)
    for name, text in files.items():
        (directory / f"{name}.yml").write_text(text, encoding="utf-8")
    return directory


def test_the_command_line_checks_a_directory_and_prints_what_it_checked(tmp_path, capsys):
    directory = write_workflows(tmp_path, a=GOOD, b=GOOD)
    assert wp.main([str(directory)]) == 0
    assert "2 workflow file(s) pass pinned-actions" in capsys.readouterr().out


def test_the_command_line_defaults_to_the_workflows_directory(tmp_path, capsys, monkeypatch):
    write_workflows(tmp_path, a=GOOD)
    monkeypatch.chdir(tmp_path)
    assert wp.main([]) == 0
    assert "1 workflow file(s)" in capsys.readouterr().out


def test_a_finding_is_an_annotation_on_its_file_and_line(tmp_path, capsys):
    directory = write_workflows(tmp_path, a=GOOD.replace("ubuntu-24.04", "ubuntu-latest"))
    assert wp.main([str(directory)]) == 1
    err = capsys.readouterr().err
    assert (
        f"::error file={directory / 'a.yml'},line=9,title=pinned-runners::job build runs on" in err
    )
    assert "1 finding(s) in 1 workflow file(s)" in err


def test_the_command_line_takes_rules_and_the_allowed_lists(tmp_path, capsys):
    text = (
        GOOD
        + "  publish:\n    runs-on: ubuntu-latest\n    timeout-minutes: 1\n"
        + "    permissions:\n      id-token: write\n    steps:\n"
        + "      - run: echo ${{ secrets.TOKEN }}\n"
    )
    directory = write_workflows(tmp_path, a=text)
    assert wp.main([str(directory), "--rules", "oidc-jobs", "--id-token-jobs", "publish"]) == 0
    assert wp.main([str(directory), "--rules", "no-stored-secrets"]) == 1
    assert (
        wp.main([str(directory), "--rules", "no-stored-secrets", "--allow-secrets", "TOKEN"]) == 0
    )
    assert wp.main([str(directory), "--rules", "pinned-runners\nno-stored-secrets"]) == 1


def test_the_command_line_accepts_one_file_and_several_paths(tmp_path, capsys):
    one = tmp_path / "one.yml"
    one.write_text(GOOD, encoding="utf-8")
    directory = write_workflows(tmp_path, a=GOOD)
    assert wp.main([str(one)]) == 0
    assert wp.main([str(one), str(directory)]) == 0
    assert "2 workflow file(s)" in capsys.readouterr().out


def test_a_missing_directory_or_no_workflows_or_an_unknown_rule_fails_with_a_message(
    tmp_path, capsys
):
    assert wp.main([str(tmp_path / "nope")]) == 1
    assert "nope does not exist." in capsys.readouterr().err
    empty = tmp_path / "empty"
    empty.mkdir()
    assert wp.main([str(empty)]) == 1
    assert "no workflow files (*.yml, *.yaml) under" in capsys.readouterr().err
    directory = write_workflows(tmp_path, a=GOOD)
    assert wp.main([str(directory), "--rules", "pinned-actons"]) == 1
    assert "unknown rule pinned-actons; the rules are pinned-actions" in capsys.readouterr().err


def test_yaml_extension_files_are_checked_too(tmp_path):
    directory = write_workflows(tmp_path)
    (directory / "x.yaml").write_text(
        GOOD.replace("ubuntu-24.04", "ubuntu-latest"), encoding="utf-8"
    )
    assert wp.main([str(directory)]) == 1


def test_the_summary_page_lists_the_findings_or_the_files_checked(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    good = write_workflows(tmp_path / "g", a=GOOD)
    assert wp.main([str(good)]) == 0
    assert "### ✅ Workflow policy" in summary.read_text(encoding="utf-8")
    bad = write_workflows(tmp_path / "b", a=GOOD.replace("ubuntu-24.04", "ubuntu-latest"))
    assert wp.main([str(bad)]) == 1
    text = summary.read_text(encoding="utf-8")
    assert "### ❌ Workflow policy" in text and "| pinned-runners |" in text
