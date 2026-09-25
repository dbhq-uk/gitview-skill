"""SKILL.md is what the agent actually runs, so its commands are tested too.

Claude Code substitutes `${CLAUDE_SKILL_DIR}` in a skill's text before the agent
sees it, and substitutes nothing else. The unbraced `$CLAUDE_SKILL_DIR` is left
for the shell, where the variable is not set, so the command becomes
`python3 "/scripts/gitview.py"` and fails. That shipped unnoticed from the first
commit, because nothing ran the documented commands.
"""
import os
import pathlib
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from fixture import build

SKILL_DIR = pathlib.Path(__file__).resolve().parents[1]
SKILL_MD = SKILL_DIR / "SKILL.md"


def _rendered():
    """SKILL.md as Claude Code hands it to the agent: the braced form only."""
    return SKILL_MD.read_text(encoding="utf-8").replace("${CLAUDE_SKILL_DIR}", str(SKILL_DIR))


def _commands():
    return [
        line.strip()
        for line in _rendered().splitlines()
        if line.strip().startswith("python3 ")
    ]


def _run(command, repo, branch):
    command = command.replace("[PATH]", repo).replace("BRANCH", branch)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_SKILL_DIR"}
    return subprocess.run(["bash", "-c", command], capture_output=True, text=True, env=env)


def test_skill_md_never_uses_the_unbraced_variable():
    text = SKILL_MD.read_text(encoding="utf-8")
    assert not re.search(r"\$CLAUDE_SKILL_DIR", text), (
        "write ${CLAUDE_SKILL_DIR} with braces: Claude Code does not substitute the unbraced form"
    )


def test_every_documented_command_names_an_absolute_path_once_rendered():
    commands = _commands()
    assert commands, "SKILL.md should document at least one python3 command"
    for command in commands:
        script = re.search(r'python3 "([^"]+)"', command)
        assert script, f"no quoted script path in: {command}"
        assert os.path.isabs(script.group(1)), f"not an absolute path once rendered: {command}"
        assert os.path.isfile(script.group(1)), f"no such script once rendered: {command}"


def test_the_documented_survey_and_verify_commands_run():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        survey = next(c for c in _commands() if "--verify" not in c)
        verify = next(c for c in _commands() if "--verify" in c)

        ran = _run(survey, repo, "landed-squash")
        assert ran.returncode == 0, ran.stderr
        assert "| Worktree | Dirty | Branch |" in ran.stdout

        ran = _run(verify, repo, "landed-squash")
        assert ran.returncode == 0, ran.stderr


def test_skill_md_never_calls_a_landed_branch_at_risk():
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "A landed branch is never at risk" in text
    assert "no remote` is the urgent one" not in text


def test_skill_md_documents_worktree_removal_and_never_forces_it():
    """A forced remove deletes uncommitted work. The skill must never offer one."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "worktree remove" in text
    assert not re.search(r"worktree remove[^\n]*--force", text)
    assert not re.search(r"--force[^\n]*worktree remove", text)
