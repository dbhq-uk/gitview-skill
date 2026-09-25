import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from table import Row, order, render


def _row(worktree, branch, safe="no"):
    return Row(worktree=worktree, branch=branch, pr="-", ahead=0, behind=0, unpushed="0", safe=safe)


def test_worktree_rows_come_before_worktreeless_ones():
    rows = order([_row("-", "aaa"), _row("app", "zzz")])
    assert [r.branch for r in rows] == ["zzz", "aaa"]


def test_rows_within_a_group_sort_by_name():
    rows = order([_row("-", "b"), _row("-", "a")])
    assert [r.branch for r in rows] == ["a", "b"]


def test_render_produces_a_markdown_table_with_every_column():
    header = render([_row("app", "feature")]).splitlines()[0]
    for column in ("Worktree", "Dirty", "Branch", "PR", "Ahead", "Behind", "Unpushed", "Safe to delete"):
        assert column in header


def test_a_safe_branch_is_emphasised_so_it_is_findable():
    assert "**YES**" in render([_row("-", "old", safe="YES")])


def test_an_empty_repository_still_renders_a_header():
    assert render([]).splitlines()[0].startswith("| Worktree |")


def test_a_pipe_in_a_branch_name_cannot_break_the_table():
    row = render([_row("-", "odd|name")]).splitlines()[2]
    assert "odd\\|name" in row, "the pipe must be escaped"
    delimiters = row.replace("\\|", "").count("|")
    assert delimiters == 9, "eight columns means nine delimiters"


def test_a_yes_keeps_its_emphasis_and_names_its_signal():
    row = render([_row("-", "old", safe="YES, landed as abc1234")]).splitlines()[2]
    assert "**YES**, landed as abc1234" in row

