"""A worktree has state the branch does not: uncommitted edits, a lock, a
directory that has gone. The survey has to show it, because a branch whose
worktree holds uncommitted work is not finished, whatever its commits say.
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
import table
from fixture import build, git


def _row(rows, name):
    return next(r for r in rows if r.branch == name)


def _finished_worktree(tmp, repo, name="checkout-finished"):
    """A linked worktree on `trunk-only`, a branch that adds nothing to the trunk."""
    path = os.path.join(tmp, name)
    git(repo, "worktree", "add", "-q", path, "trunk-only")
    return path


def _write(path, text="edit\n"):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def test_a_clean_worktree_on_a_finished_branch_reads_yes_and_not_dirty():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        _finished_worktree(tmp, repo)
        rows, _ = gitview.survey(repo, want_prs=False)
        row = _row(rows, "trunk-only")
        assert row.worktree == "checkout-finished"
        assert row.dirty == "no"
        assert row.safe == "YES, adds nothing to trunk"


def test_a_worktree_with_an_uncommitted_edit_is_never_yes():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = _finished_worktree(tmp, repo)
        _write(os.path.join(path, "other.txt"))
        rows, _ = gitview.survey(repo, want_prs=False)
        row = _row(rows, "trunk-only")
        assert row.dirty == "1 changed"
        assert row.safe == "no, landed but its worktree has uncommitted changes"


def test_an_untracked_file_counts_as_dirty():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = _finished_worktree(tmp, repo)
        _write(os.path.join(path, "notes.txt"))
        rows, _ = gitview.survey(repo, want_prs=False)
        row = _row(rows, "trunk-only")
        assert row.dirty == "1 untracked"
        assert not row.safe.startswith("YES")


def test_a_landed_branch_in_a_dirty_worktree_is_still_not_at_risk():
    """Its commits are on the trunk. The edits are shown in Dirty, not here."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = _finished_worktree(tmp, repo)
        _write(os.path.join(path, "other.txt"))
        rows, notes = gitview.survey(repo, want_prs=False)
        assert not gitview.at_risk(_row(rows, "trunk-only"))


def test_a_locked_worktree_says_so_and_is_not_yes():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = _finished_worktree(tmp, repo)
        git(repo, "worktree", "lock", "--reason", "on a laptop", path)
        rows, _ = gitview.survey(repo, want_prs=False)
        row = _row(rows, "trunk-only")
        assert row.worktree == "checkout-finished (locked)"
        assert row.safe == "no, landed but its worktree is locked"


def test_a_prunable_worktree_says_so_and_is_not_yes():
    """Its directory has gone. It may be a drive not mounted yet, so nothing
    about its contents can be known, and the survey must not guess clean.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = _finished_worktree(tmp, repo)
        os.rename(path, path + ".away")
        try:
            rows, _ = gitview.survey(repo, want_prs=False)
        finally:
            os.rename(path + ".away", path)
        row = _row(rows, "trunk-only")
        assert row.worktree == "checkout-finished (prunable)"
        assert row.dirty == "?"
        assert row.safe == "no, landed but its worktree directory is missing"


def test_a_detached_worktree_gets_a_row_with_its_sha():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        sha = git(repo, "rev-parse", "trunk").strip()
        rows, _ = gitview.survey(repo, want_prs=False)
        detached = [r for r in rows if r.detached]
        assert len(detached) == 1
        row = detached[0]
        assert row.worktree == "checkout-detached"
        assert row.branch == sha[:7]
        assert row.unpushed == "on trunk"
        assert row.safe == "-"
        assert not gitview.at_risk(row)
        assert f"detached at `{sha[:7]}`" in table.render(rows)


def test_a_detached_commit_no_branch_holds_is_at_risk():
    """The one place a commit lives only in a worktree's HEAD."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = os.path.join(tmp, "checkout-detached")
        _write(os.path.join(path, "spike.txt"))
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", "a commit on no branch")
        sha = git(path, "rev-parse", "HEAD").strip()
        rows, notes = gitview.survey(repo, want_prs=False)
        row = next(r for r in rows if r.detached)
        assert row.branch == sha[:7]
        assert row.unpushed == "no branch"
        assert gitview.at_risk(row)
        risk = next(n for n in notes if n.startswith("At risk of being lost:"))
        assert f"detached `{sha[:7]}` in `checkout-detached` (no branch holds it)" in risk


def test_a_bare_repository_is_surveyed_not_refused(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        build(tmp)
        bare = os.path.join(tmp, "bare.git")
        subprocess.run(
            ["git", "clone", "-q", "--bare", os.path.join(tmp, "origin.git"), bare],
            check=True, capture_output=True,
        )
        assert gitrepo.is_repo(bare)
        assert gitview.main(["--no-pr", bare]) == 0
        out = capsys.readouterr().out
        assert "| Worktree | Dirty | Branch |" in out
        assert "Trunk is `trunk`." in out

        rows, _ = gitview.survey(bare, want_prs=False)
        assert _row(rows, "landed-squash").safe.startswith("YES")
        assert not _row(rows, "live-work").safe.startswith("YES")
        assert _row(rows, "trunk").worktree == "-"


def test_a_bare_repository_with_no_remote_tracking_refs_says_what_that_means():
    with tempfile.TemporaryDirectory() as tmp:
        build(tmp)
        bare = os.path.join(tmp, "bare.git")
        subprocess.run(
            ["git", "clone", "-q", "--bare", os.path.join(tmp, "origin.git"), bare],
            check=True, capture_output=True,
        )
        _, notes = gitview.survey(bare, want_prs=False)
        assert any(n.startswith("This bare repository has no remote-tracking refs") for n in notes)


def test_the_survey_does_not_rewrite_any_worktree_index():
    """`git status` refreshes the index when it can, and that is a write."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = _finished_worktree(tmp, repo)
        # Same content, new mtime: the index's stat data is now stale, which
        # is exactly what a refreshing status would rewrite.
        target = os.path.join(path, "other.txt")
        stamp = os.stat(target).st_mtime + 10
        os.utime(target, (stamp, stamp))
        index = git(path, "rev-parse", "--git-path", "index").strip()
        index = os.path.join(path, index) if not os.path.isabs(index) else index
        before = open(index, "rb").read()
        gitview.survey(repo, want_prs=False)
        assert open(index, "rb").read() == before


def test_verify_offers_to_remove_a_clean_worktree_on_a_finished_branch(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = _finished_worktree(tmp, repo)
        code = gitview.main(["--verify", "trunk-only", "--no-pr", repo])
        out = capsys.readouterr().out
        assert code == 1, "a branch with a worktree is still refused"
        assert f"Refused: it is checked out in the worktree at {path}." in out
        removal = [line.strip() for line in out.splitlines() if "worktree remove" in line]
        assert len(removal) == 1
        assert "--force" not in removal[0]

        ran = subprocess.run(["bash", "-c", removal[0]], capture_output=True, text=True)
        assert ran.returncode == 0, ran.stderr
        assert not os.path.exists(path)

        assert gitview.main(["--verify", "trunk-only", "--no-pr", repo]) == 0
        capsys.readouterr()


def test_verify_names_the_ignored_files_a_removal_would_delete(capsys):
    """git counts ignored files as clean and deletes them with the directory."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = _finished_worktree(tmp, repo)
        common = os.path.join(path, git(path, "rev-parse", "--git-common-dir").strip())
        os.makedirs(os.path.join(common, "info"), exist_ok=True)
        with open(os.path.join(common, "info", "exclude"), "a", encoding="utf-8") as fh:
            fh.write(".env\nbuild/\n")
        _write(os.path.join(path, ".env"), "TOKEN=local\n")
        os.makedirs(os.path.join(path, "build"))
        _write(os.path.join(path, "build", "out.bin"))

        code = gitview.main(["--verify", "trunk-only", "--no-pr", repo])
        out = capsys.readouterr().out
        assert code == 1
        assert "worktree remove" in out
        assert "It also deletes 2 ignored paths in that directory: .env, build/." in out


def test_verify_offers_no_removal_for_a_dirty_worktree(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = _finished_worktree(tmp, repo)
        _write(os.path.join(path, "notes.txt"))
        code = gitview.main(["--verify", "trunk-only", "--no-pr", repo])
        out = capsys.readouterr().out
        assert code == 1
        assert f"checked out in the worktree at {path}, which has uncommitted changes" in out
        assert "worktree remove" not in out


def test_verify_offers_no_removal_for_a_locked_worktree(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = _finished_worktree(tmp, repo)
        git(repo, "worktree", "lock", path)
        code = gitview.main(["--verify", "trunk-only", "--no-pr", repo])
        out = capsys.readouterr().out
        assert code == 1
        assert "which is locked" in out
        assert "worktree remove" not in out


def test_verify_offers_no_removal_when_another_gate_refuses(capsys):
    """Only a finished branch gets its worktree removed."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        code = gitview.main(["--verify", "live-work", "--no-pr", repo])
        out = capsys.readouterr().out
        assert code == 1
        assert "checked out in the worktree at" in out
        assert "worktree remove" not in out


def test_verify_never_offers_to_remove_the_main_worktree(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "switch", "-q", "trunk-only")
        code = gitview.main(["--verify", "trunk-only", "--no-pr", repo])
        out = capsys.readouterr().out
        assert code == 1
        assert "checked out in the main worktree" in out
        assert "worktree remove" not in out
