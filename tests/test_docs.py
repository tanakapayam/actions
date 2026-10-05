"""The documentation as something a developer will actually use.

Examples that name an input that does not exist, a catalogue of messages that has fallen behind the
code, or a doc nobody links to, are the ways documentation quietly stops being true. Each is a test.
"""

import ast
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
ACTIONS = sorted(path.parent.relative_to(ROOT).as_posix() for path in ROOT.glob("*/*/action.yml"))
OWN = "tanakapayam/actions/"
DOCS = sorted((ROOT / "docs").glob("*.md"))
EVERY_DOC = [*DOCS, ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "RELEASING.md"]
FENCE = re.compile(r"```yaml\n(.*?)```", re.S)


def snippets(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    return [(text[: m.start()].count("\n") + 2, m.group(1)) for m in FENCE.finditer(text)]


def own_uses(node: Any) -> list[dict[str, Any]]:
    """Every step, anywhere in a parsed snippet, that uses an action of this repository."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if str(node.get("uses", "")).startswith(OWN):
            found.append(node)
        for value in node.values():
            found.extend(own_uses(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(own_uses(item))
    return found


ALL_SNIPPETS = [(path, line, text) for path in EVERY_DOC for line, text in snippets(path)]


@pytest.mark.parametrize(
    ("path", "line", "text"),
    ALL_SNIPPETS,
    ids=[f"{p.relative_to(ROOT).as_posix()}:{n}" for p, n, _ in ALL_SNIPPETS],
)
def test_every_yaml_example_is_valid_and_uses_real_inputs(path, line, text):
    document = yaml.safe_load(text)
    for step in own_uses(document):
        action = step["uses"][len(OWN) :].split("@")[0]
        assert action in ACTIONS, f"{path.name}:{line}: there is no action {action}"
        spec = yaml.safe_load((ROOT / action / "action.yml").read_text(encoding="utf-8"))
        declared = set(spec.get("inputs") or {})
        given = set(step.get("with") or {})
        assert given <= declared, f"{path.name}:{line}: {action} has no input {given - declared}"
        required = {n for n, i in (spec.get("inputs") or {}).items() if i.get("required")}
        assert required <= given, f"{path.name}:{line}: {action} needs {required - given}"
        # booleans are strings: an unquoted `true` would be a YAML boolean, which an input is not
        for name, value in (step.get("with") or {}).items():
            assert isinstance(value, str), f"{path.name}:{line}: quote the value of {name}"


def test_there_are_examples_to_check():
    assert len(ALL_SNIPPETS) >= 10
    used = {
        step["uses"][len(OWN) :].split("@")[0]
        for _, _, t in ALL_SNIPPETS
        for step in own_uses(yaml.safe_load(t))
    }
    assert used == set(ACTIONS), f"no example shows: {set(ACTIONS) - used}"


# --- the catalogue of messages -------------------------------------------------------------------


def error_fragments() -> list[tuple[str, str]]:
    """The most distinctive literal piece of every error message the scripts can raise."""
    found = []
    for name in ("guard", "fingerprint", "pyrelease"):
        tree = ast.parse((ROOT / "lib" / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                continue
            kind = getattr(node.exc.func, "id", getattr(node.exc.func, "attr", ""))
            if kind in {"GuardError", "FingerprintError", "ReleaseError"} and node.exc.args:
                pieces = [
                    n.value
                    for n in ast.walk(node.exc.args[0])
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                ]
                found.append((f"{name}.py:{node.lineno}", max(pieces, key=len).strip()))
    return found


def test_the_catalogue_covers_every_message_in_the_scripts():
    catalogue = (ROOT / "docs" / "failures.md").read_text(encoding="utf-8")
    fragments = error_fragments()
    assert len(fragments) >= 25
    missing = [(where, text) for where, text in fragments if text not in catalogue]
    assert not missing, f"docs/failures.md does not list: {missing}"


def test_the_catalogue_also_covers_the_not_yet_and_content_messages():
    catalogue = (ROOT / "docs" / "failures.md").read_text(encoding="utf-8")
    for text in [
        "lists no",
        "is not listed yet",
        "cannot reach",
        "no attestation for",
        "is missing",
        "which is not in the source tree",
    ]:
        assert text in catalogue, text


# --- the pieces a newcomer looks for -------------------------------------------------------------


def test_every_doc_has_one_title_and_is_linked_from_the_readme():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for doc in DOCS:
        text = re.sub(r"```.*?```", "", doc.read_text(encoding="utf-8"), flags=re.S)
        assert len(re.findall(r"^# ", text, re.M)) == 1, doc.name
        assert f"docs/{doc.name}" in readme, f"{doc.name} is not linked from the README"


def test_the_readme_answers_the_questions_a_newcomer_arrives_with():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for heading in ["Who is this for", "Quick start", "Requirements", "Getting help"]:
        assert f"## {heading}" in readme, heading
    assert "never publish" in readme  # the thing people most want to know first


def test_the_community_files_exist_and_link_to_each_other_correctly():
    for name in ["SECURITY.md", "SUPPORT.md", "CODE_OF_CONDUCT.md", "CONTRIBUTING.md", "LICENSE"]:
        assert (ROOT / name).is_file(), name
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for name in ["SUPPORT.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "CONTRIBUTING.md"]:
        assert name in readme, f"the README does not link {name}"


def test_the_issue_forms_are_valid_and_ask_for_what_makes_a_bug_reproducible():
    folder = ROOT / ".github" / "ISSUE_TEMPLATE"
    config = yaml.safe_load((folder / "config.yml").read_text(encoding="utf-8"))
    assert config["blank_issues_enabled"] is False
    assert any("security/advisories/new" in link["url"] for link in config["contact_links"])
    bug = yaml.safe_load((folder / "bug_report.yml").read_text(encoding="utf-8"))
    ids = {item["id"]: item for item in bug["body"] if "id" in item}
    assert {"version", "action", "step", "log"} <= set(ids)
    assert all(
        ids[name]["validations"]["required"] for name in ("version", "action", "step", "log")
    )
    assert set(ids["action"]["attributes"]["options"]) >= set(ACTIONS)
    feature = yaml.safe_load((folder / "feature_request.yml").read_text(encoding="utf-8"))
    assert feature["body"] and feature["name"] == "Feature request"


def test_the_faq_and_the_guide_point_at_the_catalogue():
    assert "failures.md" in (ROOT / "docs" / "faq.md").read_text(encoding="utf-8")
    assert "failures.md" in (ROOT / "docs" / "guide.md").read_text(encoding="utf-8")
    assert "failures.md" in (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(
        encoding="utf-8"
    )


def test_the_pre_release_checklist_names_what_the_other_files_rely_on():
    releasing = (ROOT / "RELEASING.md").read_text(encoding="utf-8")
    assert "private vulnerability reporting" in releasing
    for text in ("SECURITY.md", "code of conduct"):
        assert text in releasing
