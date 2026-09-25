"""Unpushed is how the skill decides what could be lost, so it must never
read as backed up when it is not, and never raise the alarm for a branch whose
work is already safe.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import gitrepo
import gitview
from fixture import build, git


def _row(rows, name):
    return next(r for r in rows if r.branch == name)


def _risk_note(notes):
    return next((n for n in notes if n.startswith("At risk of being lost:")), "")


def test_an_upstream_deleted_on_the_remote_reads_gone_not_zero():
    """rev-list fails on a gone upstream, and a failure used to read as 0."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "push", "-q", "origin", "--delete", "conflicting")
        git(repo, "fetch", "-q", "--prune", "origin")
        rows, notes = gitview.survey(repo, want_prs=False)
        assert _row(rows, "conflicting").unpushed == "gone"
        assert "`conflicting` (its upstream was deleted on the remote)" in _risk_note(notes)


def test_a_failed_count_is_none_never_zero():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        assert gitrepo.count(repo, "refs/remotes/origin/no-such-branch..trunk") is None


def test_a_branch_pushed_without_an_upstream_is_not_no_remote():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "push", "-q", "origin", "no-upstream")
        rows, notes = gitview.survey(repo, want_prs=False)
        assert _row(rows, "no-upstream").unpushed == "on origin/no-upstream"
        assert "no-upstream" not in _risk_note(notes)


def test_a_branch_with_no_remote_copy_still_says_no_remote():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        rows, notes = gitview.survey(repo, want_prs=False)
        assert _row(rows, "no-upstream").unpushed == "no remote"
        assert "`no-upstream` (no remote holds it)" in _risk_note(notes)


def test_a_landed_branch_is_never_at_risk():
    """Its commits exist nowhere else, but its content is already on the trunk."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        # The trunk's last edit, made again by hand. A new message, so the
        # commit cannot come out identical to the trunk's in the same second.
        git(repo, "switch", "-q", "-c", "redone", "trunk~1")
        git(repo, "cherry-pick", "--no-commit", "trunk")
        git(repo, "commit", "-q", "-m", "the same edit, made again by hand")
        git(repo, "switch", "-q", "trunk")
        rows, notes = gitview.survey(repo, want_prs=False)
        row = _row(rows, "redone")
        assert row.unpushed == "no remote"
        assert row.safe == "YES"
        assert not gitview.at_risk(row)
        assert "redone" not in _risk_note(notes)


def test_unpushed_commits_on_unlanded_work_are_at_risk():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        checkout = os.path.join(tmp, "checkout-alpha")
        with open(os.path.join(checkout, "more.txt"), "w", encoding="utf-8") as fh:
            fh.write("more\n")
        git(checkout, "add", "-A")
        git(checkout, "commit", "-m", "not pushed yet")
        rows, notes = gitview.survey(repo, want_prs=False)
        assert _row(rows, "live-work").unpushed == "1"
        assert "`live-work` (1 unpushed)" in _risk_note(notes)


def test_the_survey_says_when_the_remote_refs_were_last_fetched():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        _, notes = gitview.survey(repo, want_prs=False)
        assert any(n.startswith("No fetch is recorded in this clone") for n in notes)

        git(repo, "fetch", "-q", "origin")
        _, notes = gitview.survey(repo, want_prs=False)
        assert any(n.startswith("Remote-tracking refs were last fetched") for n in notes)
        assert any("git fetch --prune" in n for n in notes)


def test_a_fetch_from_another_worktree_counts():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(os.path.join(tmp, "checkout-alpha"), "fetch", "-q", "origin")
        assert gitrepo.last_fetch(repo) is not None


def test_stashes_are_noted_because_they_are_local_only_work():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        with open(os.path.join(repo, "other.txt"), "a", encoding="utf-8") as fh:
            fh.write("half done\n")
        git(repo, "stash", "push", "-q", "-m", "half done")
        _, notes = gitview.survey(repo, want_prs=False)
        assert "1 stash entry exists in this clone." in " ".join(notes)


def test_the_whole_run_leads_its_notes_with_what_is_at_risk(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        assert gitview.main(["--no-pr", repo]) == 0
        out = capsys.readouterr().out
        notes = out.split("\n\n", 1)[1].strip().splitlines()
        assert notes[0].startswith("At risk of being lost:")


def test_no_remote_means_no_fetch_note():
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "solo")
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
        git(repo, "commit", "-q", "--allow-empty", "-m", "first")
        _, notes = gitview.survey(repo, want_prs=False)
        assert not any("fetch" in n for n in notes)
