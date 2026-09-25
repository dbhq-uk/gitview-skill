"""The README's demo says it is real output from a real run. This holds it to
that: it builds the demo repository with the script the README names, runs the
survey, and compares the result with what the README shows.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import gitview

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
README = REPO_ROOT / "README.md"
BUILD = REPO_ROOT / "docs" / "build-demo-fixture.sh"
DEFAULT_ROOT = "/tmp/gitview-demo"


def _readme_demo():
    """The table and the notes under it, as the README shows them."""
    lines = README.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("| Worktree |"))
    block = []
    for line in lines[start:]:
        if not line.strip() and block and not block[-1].startswith("|"):
            break
        block.append(line)
    return block


def _real_run(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "demo")
        subprocess.run(["bash", str(BUILD), root], check=True, capture_output=True)
        assert gitview.main(["--no-pr", os.path.join(root, "checkout-service")]) == 0
        out = capsys.readouterr().out
    return out.replace(root, DEFAULT_ROOT).splitlines()


def test_the_readme_demo_is_the_output_the_fixture_produces(capsys):
    assert _readme_demo() == _real_run(capsys)


def test_the_branch_the_fixture_calls_behind_is_behind(capsys):
    row = next(line for line in _real_run(capsys) if "`wip/rename-basket`" in line)
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert cells[5] != "0", "the fixture comment says branch 5 is behind the trunk"
