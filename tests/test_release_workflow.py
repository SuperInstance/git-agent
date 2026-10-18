"""The release workflow must not publish a tag that points at nothing.

`twine upload` used to run under `continue-on-error: true` and the GitHub Release that
followed it was unconditional. So a missing or wrong PYPI_API_TOKEN gave you: upload failed,
job green, release published, and a tag that downstream consumers could install and get
nothing.

These tests read the shipped workflow and assert the invariant directly, because the failure
mode is invisible in the diff -- every individual line looks reasonable.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RELEASE = REPO / ".github" / "workflows" / "release.yml"
TEXT = RELEASE.read_text()


def step_named(name: str) -> str:
    """Return the YAML block of the step whose `name:` is `name`."""
    lines = TEXT.splitlines()
    for i, line in enumerate(lines):
        if re.match(rf"\s*-\s+(name:\s*{re.escape(name)}\s*$)", line):
            block = [line]
            indent = len(line) - len(line.lstrip())
            for follow in lines[i + 1:]:
                if follow.strip() and (len(follow) - len(follow.lstrip())) <= indent:
                    break
                block.append(follow)
            return "\n".join(block)
    raise AssertionError(f"step not found in {RELEASE.name}: {name}")


def test_upload_step_is_not_swallowed():
    assert "continue-on-error" not in TEXT, (
        "a failed PyPI upload must fail the job; continue-on-error turns it into a green "
        "run with no artefact"
    )


def test_release_is_gated_on_the_upload_succeeding():
    release_step = step_named("Create GitHub Release")
    assert "if:" in release_step, (
        "Create GitHub Release must be conditional -- an unconditional release publishes a "
        "tag for a version that was never uploaded"
    )
    assert "steps.publish.outcome" in release_step, (
        "gate the release on the upload step's OUTCOME, not on a stringified output"
    )


def test_release_gate_passes_when_the_upload_succeeds():
    release_step = step_named("Create GitHub Release")
    condition = re.search(r"if:\s*(.+)", release_step).group(1).strip()
    assert condition == "steps.publish.outcome == 'success'", (
        f"unexpected release condition: {condition!r}"
    )


@pytest.mark.parametrize(
    "outcome, release_should_run",
    [("success", True), ("failure", False), ("skipped", False), ("cancelled", False)],
)
def test_release_only_runs_after_a_successful_upload(outcome, release_should_run):
    """The decision matrix behind the gate.

    A skipped step publishes no outputs, so a gate that compared an output string to a
    literal would read it as 0 and wave it through. Keying on `outcome` has no such hole:
    anything that is not `success` blocks the release.
    """
    release_step = step_named("Create GitHub Release")
    condition = re.search(r"if:\s*steps\.publish\.outcome\s*(==|!=)\s*'([^']+)'", release_step)
    assert condition, "release gate must compare steps.publish.outcome to a literal"
    op, literal = condition.group(1), condition.group(2)
    runs = (outcome == literal) if op == "==" else (outcome != literal)
    assert runs is release_should_run, f"{outcome=} -> release runs={runs}"


def test_workflow_asserts_the_artefact_exists():
    """`twine upload` exiting 0 is a claim, not a receipt."""
    assert "pypi.org/pypi/" in TEXT, (
        "assert the uploaded artefact is actually on PyPI before anything points a tag at it"
    )
