"""Three signals can prove a branch landed, and each YES says which one did.

The tree check misses a squash merge the trunk has since edited, because
merging the trunk back in conflicts. The squashed patch id and a merged pull
request's head SHA both still see it. Neither ever matches on a branch name.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import forge
import gitrepo
import gitview
import landed
from fixture import build, git, squash_then_edit

TRUNK = "origin/trunk"


def _row(rows, name):
    return next(r for r in rows if r.branch == name)


def _forge(monkeypatch, merged):
    """Pretend origin is on GitHub, with no open pull requests and these merged ones."""
    monkeypatch.setattr(forge, "detect", lambda _url: "github")
    monkeypatch.setattr(forge, "list_prs", lambda _kind, _cwd: ({}, None))
    monkeypatch.setattr(forge, "list_merged", lambda _kind, _cwd: (dict(merged), None))


def test_a_squash_the_trunk_later_edited_reads_as_landed_with_its_commit(engine):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        landing = squash_then_edit(repo)
        if landed.has_merge_tree():
            tree_check = subprocess.run(
                ["git", "-C", repo, "merge-tree", "--write-tree", "squashed-then-edited", TRUNK],
                capture_output=True,
            )
            assert tree_check.returncode == 1, "the tree check alone must not see this one"

        verdict = landed.verdict(repo, TRUNK, "squashed-then-edited")
        assert verdict.state == "landed"
        assert verdict.detail == f"landed as {landing[:7]}"

        rows, _ = gitview.survey(repo, want_prs=False)
        assert _row(rows, "squashed-then-edited").safe == f"YES, landed as {landing[:7]}"


def test_a_squashed_branch_with_new_work_since_is_not_landed(engine):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        squash_then_edit(repo)
        git(repo, "switch", "-q", "squashed-then-edited")
        with open(os.path.join(repo, "later.txt"), "w", encoding="utf-8") as fh:
            fh.write("more work after the merge\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "more work after the merge")
        git(repo, "switch", "-q", "trunk")
        assert landed.verdict(repo, TRUNK, "squashed-then-edited").state != "landed"


def test_verify_accepts_a_squash_the_trunk_later_edited(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        landing = squash_then_edit(repo)
        assert gitview.main(["--verify", "squashed-then-edited", "--no-pr", repo]) == 0
        assert f"landed (landed as {landing[:7]})" in capsys.readouterr().out


def test_a_merged_pull_request_whose_head_is_the_tip_is_landed(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        tip = gitrepo.local_sha(repo, "conflicting")
        _forge(monkeypatch, {tip: "12"})
        rows, _ = gitview.survey(repo, want_prs=True)
        assert _row(rows, "conflicting").safe == "YES, merged in PR 12"


def test_a_merged_pull_request_is_never_matched_by_branch_name(monkeypatch):
    """The name was merged once. The work on it now is new, and nobody merged that."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        merged_then = gitrepo.local_sha(repo, "live-work")
        checkout = os.path.join(tmp, "checkout-alpha")
        with open(os.path.join(checkout, "second.txt"), "w", encoding="utf-8") as fh:
            fh.write("a second round\n")
        git(checkout, "add", "-A")
        git(checkout, "commit", "-m", "a second round on the same branch name")
        _forge(monkeypatch, {merged_then: "7"})
        rows, _ = gitview.survey(repo, want_prs=True)
        row = _row(rows, "live-work")
        assert not row.safe.startswith("YES")
        assert "PR 7" not in row.safe


def test_verify_applies_the_pull_request_signal_too(capsys, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "remote", "set-url", "origin", "https://github.com/owner/repo.git")
        tip = gitrepo.local_sha(repo, "conflicting")
        _forge(monkeypatch, {tip: "12"})
        assert gitview.main(["--verify", "conflicting", repo]) == 0
        assert "merged in PR 12" in capsys.readouterr().out


def test_every_yes_names_the_signal_behind_it(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        squash_then_edit(repo)
        _forge(monkeypatch, {gitrepo.local_sha(repo, "conflicting"): "12"})
        rows, _ = gitview.survey(repo, want_prs=True)
        signals = {r.safe.split(", ", 1)[1].split(" ")[0] for r in rows if r.safe.startswith("YES")}
        assert signals == {"adds", "landed", "merged"}
