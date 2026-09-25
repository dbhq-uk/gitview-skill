import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import landed  # noqa: E402


@pytest.fixture(params=["merge-tree", "worktree"])
def engine(request, monkeypatch):
    """Run a test once per way of computing the merge.

    git 2.38 and later use `git merge-tree`. Older git falls back to a merge in a
    throwaway worktree, so that path is forced here too: it has to reach the
    same verdicts, and it is the one users on an older git actually run.
    """
    if request.param == "merge-tree":
        if not landed.has_merge_tree():
            pytest.skip("git merge-tree --write-tree needs git 2.38 or later")
    else:
        monkeypatch.setattr(landed, "has_merge_tree", lambda: False)
    return request.param
