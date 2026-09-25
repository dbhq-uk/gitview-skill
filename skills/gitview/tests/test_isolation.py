"""The survey reads the repository. It must not run its hooks, depend on the
user's commit settings, or change any other worktree's registration.

Each test runs against both ways of computing the merge (see conftest.py).
"""
import os
import pathlib
import stat
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import gitview
import landed
from fixture import build, git

TRUNK = "origin/trunk"


def _verdicts(repo):
    return {
        name: landed.verdict(repo, TRUNK, name).state
        for name in ("landed-squash", "live-work", "conflicting")
    }


EXPECTED = {"landed-squash": "landed", "live-work": "unlanded", "conflicting": "conflicts"}


def test_a_failing_commit_signer_does_not_change_the_verdict(engine):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "config", "commit.gpgsign", "true")
        git(repo, "config", "gpg.program", "false")
        assert _verdicts(repo) == EXPECTED


def test_merge_ff_only_does_not_change_the_verdict(engine):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "config", "merge.ff", "only")
        assert _verdicts(repo) == EXPECTED


def test_no_committer_identity_does_not_change_the_verdict(engine, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "config", "--unset", "user.name")
        git(repo, "config", "--unset", "user.email")
        git(repo, "config", "user.useConfigOnly", "true")
        empty = os.path.join(tmp, "empty-gitconfig")
        open(empty, "w").close()
        for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                     "GIT_COMMITTER_EMAIL", "EMAIL"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", empty)
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        monkeypatch.setenv("HOME", tmp)
        assert _verdicts(repo) == EXPECTED


HOOKS = (
    "post-checkout", "pre-merge-commit", "prepare-commit-msg", "commit-msg",
    "post-merge", "pre-commit", "post-commit", "reference-transaction",
)


def test_no_repository_hook_runs_during_a_survey(engine):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        marker = os.path.join(tmp, "hooks-that-ran")
        hooks = os.path.join(repo, ".git", "hooks")
        for name in HOOKS:
            path = os.path.join(hooks, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"#!/bin/sh\necho {name} >> '{marker}'\n")
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

        gitview.survey(repo, want_prs=False)

        ran = open(marker, encoding="utf-8").read().split() if os.path.exists(marker) else []
        assert ran == [], f"hooks ran during the survey: {ran}"


def test_a_briefly_absent_worktree_keeps_its_registration(engine):
    """A directory mid-move, or on a drive not mounted yet, is not a stale worktree.

    A repo-wide `git worktree prune` would drop its registration, and after that
    `git branch -D` deletes the branch still checked out there.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = os.path.join(tmp, "checkout-finished")
        git(repo, "worktree", "add", "-q", path, "trunk-only")
        os.rename(path, path + ".away")
        try:
            gitview.survey(repo, want_prs=False)
        finally:
            os.rename(path + ".away", path)

        assert f"worktree {path}" in git(repo, "worktree", "list", "--porcelain")
        deleted = subprocess.run(
            ["git", "-C", repo, "branch", "-D", "trunk-only"], capture_output=True, text=True
        )
        assert deleted.returncode != 0, "git must still refuse to delete a checked-out branch"


def _subcommand(cmd):
    """(subcommand, first argument) of a git argv, skipping -C and -c pairs."""
    args = list(cmd[1:])
    while args and args[0] in ("-C", "-c"):
        args = args[2:]
    return tuple(args[:2])


def test_merge_tree_makes_no_merge_and_no_worktree(monkeypatch):
    if not landed.has_merge_tree():
        pytest.skip("git merge-tree --write-tree needs git 2.38 or later")
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        calls = []
        real = subprocess.run

        def spy(cmd, *args, **kwargs):
            if cmd and cmd[0] == "git":
                calls.append(_subcommand(cmd))
            return real(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", spy)
        for name in ("landed-squash", "live-work", "conflicting", "trunk-only", "no-upstream"):
            landed.verdict(repo, TRUNK, name)

        assert calls, "the spy saw nothing, so the test proves nothing"
        assert not [c for c in calls if c[:1] == ("merge",)]
        assert not [c for c in calls if c[:1] == ("worktree",)]
        assert ("merge-tree", "--write-tree") in calls
