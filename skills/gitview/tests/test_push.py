"""The push offer. A push the remote rejects, or one that only makes a remote
branch nobody needs, is noise at best. A push to the trunk can be a deploy.
"""
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import gitview
from fixture import build, colleague_pushes, git


def _commit(path, name, text="more\n"):
    with open(os.path.join(path, name), "a", encoding="utf-8") as fh:
        fh.write(text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", f"edit {name}")


def _note(notes, start):
    return next((n for n in notes if n.startswith(start)), "")


def _push_note(notes):
    return _note(notes, "To push the work that has not landed")


def test_a_diverged_trunk_is_reported_and_never_offered_for_a_push():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        colleague_pushes(tmp, "trunk")
        git(repo, "fetch", "-q", "origin")
        _commit(repo, "trunk-local.txt")
        _, notes = gitview.survey(repo, want_prs=False)
        diverged = _note(notes, "Local `trunk` has diverged from `origin/trunk`")
        assert diverged.startswith(
            "Local `trunk` has diverged from `origin/trunk`: 1 commit only here, 1 only there."
        )
        assert "never offers to push the trunk" in diverged
        assert " trunk`" not in _push_note(notes)
        assert "trunk:trunk" not in _push_note(notes)


def test_a_trunk_only_ahead_is_reported_and_never_offered_for_a_push():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        _commit(repo, "trunk-local.txt")
        _, notes = gitview.survey(repo, want_prs=False)
        assert _note(notes, "Local `trunk` has 1 commit `origin/trunk` does not.")
        assert "trunk:trunk" not in _push_note(notes)


def test_a_trunk_in_step_with_its_upstream_gets_no_note():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        _, notes = gitview.survey(repo, want_prs=False)
        assert not _note(notes, "Local `trunk`")


def test_unlanded_work_is_offered_with_an_explicit_refspec():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        _commit(os.path.join(tmp, "checkout-alpha"), "feature.txt")
        _, notes = gitview.survey(repo, want_prs=False)
        offer = _push_note(notes)
        assert f"`git -C {repo} push origin live-work:live-work`" in offer
        assert f"`git -C {repo} push -u origin no-upstream`" in offer


def test_a_landed_branch_with_unpushed_commits_is_not_offered():
    """Everything in it is on the trunk. A push only makes a branch nobody needs."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "branch", "-f", "landed-squash", "trunk")
        rows, notes = gitview.survey(repo, want_prs=False)
        row = next(r for r in rows if r.branch == "landed-squash")
        assert row.safe.startswith("YES")
        assert int(row.unpushed) > 0
        assert "landed-squash" not in _push_note(notes)


def test_a_branch_behind_its_upstream_is_not_offered_and_says_why():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        colleague_pushes(tmp, "live-work")
        git(repo, "fetch", "-q", "origin")
        _commit(os.path.join(tmp, "checkout-alpha"), "feature.txt")
        rows, notes = gitview.survey(repo, want_prs=False)
        assert next(r for r in rows if r.branch == "live-work").unpushed == "1"
        assert "live-work" not in _push_note(notes)
        held = _note(notes, "Not offered for a push:")
        assert "`live-work` is also 1 behind its upstream, so the remote would reject it" in held


def test_nothing_to_push_means_no_push_note():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "push", "-q", "-u", "origin", "no-upstream")
        _, notes = gitview.survey(repo, want_prs=False)
        assert not _push_note(notes)
