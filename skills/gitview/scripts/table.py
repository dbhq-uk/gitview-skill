"""Orders the rows and renders the markdown table."""
from dataclasses import dataclass

COLUMNS = ("Worktree", "Dirty", "Branch", "PR", "Ahead", "Behind", "Unpushed", "Safe to delete")
HEADER = "| " + " | ".join(COLUMNS) + " |"
RULE = "|" + "---|" * len(COLUMNS)


@dataclass
class Row:
    worktree: str
    branch: str  # the branch name, or the short SHA of a detached worktree
    pr: str
    ahead: int
    behind: int
    unpushed: str
    safe: str
    dirty: str = "-"  # "-" with no worktree, "no" when clean, "?" when unreadable
    detached: bool = False
    landed: bool = False  # adds nothing to the trunk, even where Safe to delete says no


def order(rows):
    """Worktree rows first, then the rest.

    Branches with no worktree are kept deliberately, and sorted last rather
    than hidden: that is exactly where finished branches accumulate.
    """
    return sorted(rows, key=lambda r: (r.worktree == "-", r.worktree, r.branch))


def _escape(value):
    """A pipe in a branch name would otherwise split the row into extra cells."""
    return str(value).replace("|", "\\|")


def _safe(value):
    """Bold the YES so it is findable. What follows it names the proof."""
    if value.startswith("YES"):
        return "**YES**" + _escape(value[3:])
    return _escape(value)


def _branch(row):
    """A detached worktree has no branch to name, so it names the commit."""
    if row.detached:
        return f"detached at `{_escape(row.branch)}`"
    return f"`{_escape(row.branch)}`"


def render(rows):
    lines = [HEADER, RULE]
    for row in order(rows):
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                _escape(row.worktree),
                _escape(row.dirty),
                _branch(row),
                _escape(row.pr),
                row.ahead,
                row.behind,
                _escape(row.unpushed),
                _safe(row.safe),
            )
        )
    return "\n".join(lines)
