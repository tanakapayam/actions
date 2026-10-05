"""tests/actionrun.py: the runner that the action tests stand on has to be trustworthy itself."""

from pathlib import Path

import actionrun
import pytest


def action(tmp_path: Path, document: str) -> Path:
    directory = tmp_path / "act"
    directory.mkdir()
    (directory / "action.yml").write_text(document, encoding="utf-8")
    return directory


ECHO = """\
name: t
description: t
inputs:
  who:
    description: d
    default: world
  need:
    description: d
    required: true
  github-default:
    description: d
    default: ${{ github.event.release.tag_name }}
outputs:
  greeting:
    description: d
    value: ${{ steps.say.outputs.greeting }}
runs:
  using: composite
  steps:
    - id: say
      shell: bash
      env:
        WHO: ${{ inputs.who }}
        TAG: ${{ inputs.github-default }}
        PATH_HERE: ${{ github.action_path }}
        TEMP: ${{ runner.temp }}
      run: |
        echo "greeting=hello $WHO $TAG" >> "$GITHUB_OUTPUT"
        echo "summary line" >> "$GITHUB_STEP_SUMMARY"
        echo "visible"
        echo "problem" >&2
"""


def test_inputs_defaults_contexts_outputs_and_the_summary(tmp_path):
    directory = action(tmp_path, ECHO)
    result = actionrun.run_action(
        directory,
        {"need": "x"},
        github={"event": {"release": {"tag_name": "python-v1.0.0"}}},
    )
    assert result.ok
    assert result.outputs == {"greeting": "hello world python-v1.0.0"}
    assert result.summary.strip() == "summary line"
    assert result.stdout == "visible\n" and result.stderr == "problem\n"


def test_a_given_input_beats_the_default_and_an_unset_github_property_is_empty(tmp_path):
    result = actionrun.run_action(action(tmp_path, ECHO), {"need": "x", "who": "Mo"})
    assert result.outputs == {"greeting": "hello Mo "}  # no release tag: GitHub gives ""


def test_a_missing_required_input_and_an_unknown_input_are_mistakes_in_the_test(tmp_path):
    directory = action(tmp_path, ECHO)
    with pytest.raises(actionrun.HarnessError, match="required input need was not given"):
        actionrun.run_action(directory, {})
    with pytest.raises(actionrun.HarnessError, match="no input"):
        actionrun.run_action(directory, {"need": "x", "typo": "y"})


def test_a_failing_step_fails_the_action_stops_the_steps_and_yields_no_outputs(tmp_path):
    directory = action(
        tmp_path,
        """\
name: t
description: t
outputs:
  out:
    description: d
    value: ${{ steps.a.outputs.x }}
runs:
  using: composite
  steps:
    - id: a
      shell: bash
      run: |
        echo "x=1" >> "$GITHUB_OUTPUT"
        false
        echo "not reached"
    - shell: bash
      run: echo "second step"
""",
    )
    result = actionrun.run_action(directory)
    assert not result.ok and result.returncode == 1
    assert result.outputs == {} and "not reached" not in result.stdout
    assert "second step" not in result.stdout


def test_a_failure_inside_a_command_substitution_still_fails_the_step(tmp_path):
    # `echo "x=$(failing)"` would exit 0; an assignment first would not. The actions rely on that.
    directory = action(
        tmp_path,
        """\
name: t
description: t
runs:
  using: composite
  steps:
    - shell: bash
      run: |
        value=$(exit 3)
        echo "unreachable"
""",
    )
    assert actionrun.run_action(directory).returncode == 3


def test_step_outputs_flow_between_steps_in_name_value_and_heredoc_form(tmp_path):
    directory = action(
        tmp_path,
        """\
name: t
description: t
outputs:
  both:
    description: d
    value: ${{ steps.second.outputs.joined }}
runs:
  using: composite
  steps:
    - id: first
      shell: bash
      run: |
        echo "one=1" >> "$GITHUB_OUTPUT"
        {
          echo "multi<<EOF"
          echo "line a"
          echo "line b"
          echo "EOF"
        } >> "$GITHUB_OUTPUT"
    - id: second
      shell: bash
      env:
        ONE: ${{ steps.first.outputs.one }}
        MULTI: ${{ steps.first.outputs.multi }}
      run: echo "joined=$ONE/${MULTI//$'\\n'/|}" >> "$GITHUB_OUTPUT"
""",
    )
    assert actionrun.run_action(directory).outputs == {"both": "1/line a|line b"}


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ("- uses: actions/checkout@v4", "`uses:` and `if:` are not modelled"),
        (
            "- if: always()\n      shell: bash\n      run: echo",
            "`uses:` and `if:` are not modelled",
        ),
        ("- run: echo", "needs `shell: bash`"),
        ("- shell: sh\n      run: echo", "needs `shell: bash`"),
        ('- shell: bash\n      run: echo "${{ inputs.x }}"', "an expression in a script"),
        ("- shell: bash\n      env:\n        A: ${{ secrets.TOKEN }}\n      run: echo",
         "unsupported expression"),
        ("- shell: bash\n      env:\n        A: ${{ format('{0}', 1) }}\n      run: echo",
         "unsupported expression"),
        ("- shell: bash\n      env:\n        A: ${{ inputs.nope }}\n      run: echo",
         "inputs.nope is not declared"),
    ],
)  # fmt: skip
def test_anything_beyond_what_the_actions_may_use_is_refused_loudly(tmp_path, step, message):
    directory = action(
        tmp_path,
        f"name: t\ndescription: t\nruns:\n  using: composite\n  steps:\n    {step}\n",
    )
    with pytest.raises(actionrun.HarnessError, match=message):
        actionrun.run_action(directory)


def test_a_non_composite_action_is_refused(tmp_path):
    directory = action(tmp_path, "name: t\ndescription: t\nruns:\n  using: node20\n  main: x.js\n")
    with pytest.raises(actionrun.HarnessError, match="not a composite action"):
        actionrun.run_action(directory)


def test_the_working_directory_and_the_workspace_are_honoured(tmp_path):
    directory = action(
        tmp_path,
        """\
name: t
description: t
runs:
  using: composite
  steps:
    - shell: bash
      run: pwd; echo "$GITHUB_WORKSPACE"
    - shell: bash
      working-directory: ${{ github.workspace }}/sub
      run: pwd
""",
    )
    (tmp_path / "sub").mkdir()
    result = actionrun.run_action(directory, cwd=tmp_path)
    assert result.stdout.splitlines() == [str(tmp_path), str(tmp_path), str(tmp_path / "sub")]


def test_the_surrounding_github_variables_do_not_leak_into_a_step(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("INPUT_WHO", "leaked")
    directory = action(
        tmp_path,
        "name: t\ndescription: t\nruns:\n  using: composite\n  steps:\n"
        '    - shell: bash\n      run: echo "[$GITHUB_TOKEN][$INPUT_WHO]"\n',
    )
    assert actionrun.run_action(directory).stdout == "[][]\n"


def test_flatten_dots_nested_github_context():
    assert actionrun.flatten({"a": {"b": {"c": 1}}, "d": "x"}) == {"a.b.c": "1", "d": "x"}


def test_a_step_with_no_working_directory_runs_where_the_jobs_default_says(tmp_path):
    directory = action(
        tmp_path,
        "name: t\ndescription: t\nruns:\n  using: composite\n  steps:\n"
        "    - shell: bash\n      run: pwd\n"
        "    - shell: bash\n      working-directory: ${{ github.workspace }}\n      run: pwd\n",
    )
    (tmp_path / "default").mkdir()
    (tmp_path / "ws").mkdir()
    result = actionrun.run_action(directory, cwd=tmp_path / "ws", default_cwd=tmp_path / "default")
    assert result.stdout.splitlines() == [str(tmp_path / "default"), str(tmp_path / "ws")]
