import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import gitview
from fixture import build


def test_survey_covers_every_local_branch():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        rows, _ = gitview.survey(repo, want_prs=False)
        names = {r.branch for r in rows}
        assert {"landed-squash", "live-work", "conflicting", "no-upstream", "trunk"} <= names


def test_the_squashed_branch_is_the_one_marked_safe():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        rows, _ = gitview.survey(repo, want_prs=False)
        safe = {r.branch for r in rows if r.safe.startswith("YES")}
        assert "landed-squash" in safe
        assert "live-work" not in safe
        assert "conflicting" not in safe


def test_a_branch_ahead_of_trunk_can_still_be_safe_to_delete():
    """Ahead is a commit count, not a measure of unlanded work."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        rows, _ = gitview.survey(repo, want_prs=False)
        row = next(r for r in rows if r.branch == "landed-squash")
        assert row.ahead > 0
        assert row.safe == "YES, adds nothing to trunk"


def test_the_trunk_is_never_offered_for_deletion():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        rows, _ = gitview.survey(repo, want_prs=False)
        assert next(r for r in rows if r.branch == "trunk").safe == "no, trunk"


def test_a_branch_with_no_upstream_says_so():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        rows, _ = gitview.survey(repo, want_prs=False)
        assert next(r for r in rows if r.branch == "no-upstream").unpushed == "no remote"


def test_the_worktree_directory_name_is_shown_not_the_branch_name():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        rows, _ = gitview.survey(repo, want_prs=False)
        assert next(r for r in rows if r.branch == "live-work").worktree == "checkout-alpha"


def test_a_branch_with_no_worktree_shows_a_dash():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        rows, _ = gitview.survey(repo, want_prs=False)
        assert next(r for r in rows if r.branch == "no-upstream").worktree == "-"


def test_verify_exits_zero_only_for_a_finished_branch():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        assert gitview.main(["--verify", "landed-squash", "--no-pr", repo]) == 0
        assert gitview.main(["--verify", "live-work", "--no-pr", repo]) == 1


def test_verify_refuses_the_trunk():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        assert gitview.main(["--verify", "trunk", "--no-pr", repo]) == 1


def test_a_directory_that_is_not_a_repository_exits_non_zero():
    with tempfile.TemporaryDirectory() as tmp:
        assert gitview.main([tmp]) != 0


def test_the_whole_run_prints_a_table_and_names_the_trunk(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        assert gitview.main(["--no-pr", repo]) == 0
        out = capsys.readouterr().out
        assert "| Worktree | Branch |" in out
        assert "Trunk is" in out
