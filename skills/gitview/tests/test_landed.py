import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import gitrepo
import landed
from fixture import build

TRUNK = "origin/trunk"


def test_a_squash_merged_branch_reads_as_landed(engine):
    """The case that defeats reverse-applying the branch's patch."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        assert landed.verdict(repo, TRUNK, "landed-squash").state == "landed"


def test_git_branch_merged_would_have_missed_it():
    """Proves the naive check really is wrong here, so the suite is not circular."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        merged = gitrepo.git(["branch", "--merged", TRUNK], repo).replace("*", "").split()
        assert "landed-squash" not in merged


def test_reverse_applying_the_patch_would_also_have_got_it_wrong(engine):
    """The other naive check, and the one that actually caused a bad call.

    The branch's content is in the trunk, so reverse-applying its diff should
    succeed. It does not, because the trunk edited the same file afterwards and
    the context no longer matches. A survey built on this reports a finished
    branch as live work forever.
    """
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        patch = gitrepo.git(["diff", f"{TRUNK}...landed-squash"], repo)
        assert patch, "the branch must have a diff against its merge base"
        applied = subprocess.run(
            ["git", "-C", repo, "apply", "-R", "--check", "-"],
            input=patch + "\n", capture_output=True, text=True,
        )
        assert applied.returncode != 0, "expected the naive reverse-apply check to fail here"
        assert landed.verdict(repo, TRUNK, "landed-squash").state == "landed"


def test_genuine_work_does_not_read_as_landed(engine):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        v = landed.verdict(repo, TRUNK, "live-work")
        assert v.state == "unlanded"
        assert "insertion" in v.detail


def test_a_conflicting_branch_reads_as_conflicts_not_landed(engine):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        assert landed.verdict(repo, TRUNK, "conflicting").state == "conflicts"


def test_a_branch_identical_to_trunk_is_landed(engine):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        assert landed.verdict(repo, TRUNK, "trunk-only").state == "landed"


def test_the_fast_path_never_disagrees_with_the_slow_one(engine):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        for name in ("landed-squash", "trunk-only", "live-work", "conflicting"):
            if landed.fast_is_landed(repo, TRUNK, name):
                assert landed.verdict(repo, TRUNK, name).state == "landed"


def test_both_engines_reach_the_same_verdicts(monkeypatch):
    if not landed.has_merge_tree():
        pytest.skip("git merge-tree --write-tree needs git 2.38 or later")
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        names = ("landed-squash", "trunk-only", "live-work", "conflicting", "no-upstream")
        fast = {name: landed.verdict(repo, TRUNK, name) for name in names}
        monkeypatch.setattr(landed, "has_merge_tree", lambda: False)
        slow = {name: landed.verdict(repo, TRUNK, name) for name in names}
        assert fast == slow


def test_no_worktree_is_left_behind(engine):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        before = gitrepo.git(["worktree", "list"], repo)
        landed.verdict(repo, TRUNK, "conflicting")
        landed.verdict(repo, TRUNK, "live-work")
        assert gitrepo.git(["worktree", "list"], repo) == before
