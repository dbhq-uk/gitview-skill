"""Builds a throwaway repository exercising every case gitview must get right.

The main line is called `trunk`, not `main`, on purpose: any code that assumes
`main` then fails loudly here rather than passing by luck.
"""
import os
import subprocess


def _git(repo, *args):
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="T",
        GIT_AUTHOR_EMAIL="t@e",
        GIT_COMMITTER_NAME="T",
        GIT_COMMITTER_EMAIL="t@e",
    )
    return subprocess.run(
        ["git", "-C", repo, *args], check=True, env=env, capture_output=True, text=True
    ).stdout


def _write(repo, name, text):
    with open(os.path.join(repo, name), "w", encoding="utf-8") as fh:
        fh.write(text)


def build(root):
    """Create the repository and return its path."""
    origin = os.path.join(root, "origin.git")
    repo = os.path.join(root, "work")
    subprocess.run(["git", "init", "--bare", "-b", "trunk", origin], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "trunk", repo], check=True, capture_output=True)
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "user.email", "t@e")
    _git(repo, "remote", "add", "origin", origin)

    # A file with well separated regions, so a later edit at the bottom is a
    # different hunk from the branch's edit near the top.
    _write(repo, "shared.txt", "alpha\nbravo\ncharlie\ndelta\necho\n")
    _write(repo, "other.txt", "base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "push", "-u", "origin", "trunk")
    _git(repo, "remote", "set-head", "origin", "trunk")

    # landed-squash: its content reaches trunk by squash, and trunk then edits
    # the SAME FILE in a different region. Merging trunk in resolves to trunk's
    # version exactly, so the branch adds nothing, yet reverse-applying its
    # patch fails because the context moved. That is the case this whole
    # module exists for.
    _git(repo, "switch", "-c", "landed-squash")
    _write(repo, "shared.txt", "alpha\nbravo\nbravo-two\ncharlie\ndelta\necho\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add bravo-two")
    _git(repo, "switch", "trunk")
    _git(repo, "merge", "--squash", "landed-squash")
    _git(repo, "commit", "-m", "squash: add bravo-two")
    _write(repo, "shared.txt", "alpha\nbravo\nbravo-two\ncharlie\ndelta\necho changed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "trunk edits the same file afterwards, elsewhere")
    _git(repo, "push", "origin", "trunk")
    _git(repo, "push", "-u", "origin", "landed-squash")

    # live-work: genuine unlanded content, in a file trunk does not touch.
    _git(repo, "switch", "-c", "live-work", "trunk")
    _write(repo, "feature.txt", "new feature\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "a feature")
    _git(repo, "push", "-u", "origin", "live-work")

    # conflicting: edits the same line trunk edited, differently.
    _git(repo, "switch", "-c", "conflicting", "trunk~1")
    _write(repo, "shared.txt", "alpha\nbravo\nbravo-two\ncharlie\ndelta\necho DIFFERENT\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "conflicting edit")
    _git(repo, "push", "-u", "origin", "conflicting")

    # no-upstream: never pushed, so its work exists only here.
    _git(repo, "switch", "-c", "no-upstream", "trunk")
    _write(repo, "local.txt", "local only\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "local only")

    # trunk-only: identical to trunk, adds nothing.
    _git(repo, "switch", "-c", "trunk-only", "trunk")

    _git(repo, "switch", "trunk")

    # A worktree whose directory name differs from its branch name.
    _git(repo, "worktree", "add", os.path.join(root, "checkout-alpha"), "live-work")
    # A detached worktree, which must not crash anything.
    _git(repo, "worktree", "add", "--detach", os.path.join(root, "checkout-detached"), "trunk")
    return repo


def git(repo, *args):
    """Run git in a fixture repository, with a fixed identity. Returns stdout."""
    return _git(repo, *args)


def colleague_pushes(root, branch, name="colleague"):
    """Somebody else pushes one more commit to BRANCH from their own clone.

    Returns the SHA they pushed. The surveyed repository does not fetch here,
    so the caller decides whether it has seen the push yet.
    """
    origin = os.path.join(root, "origin.git")
    other = os.path.join(root, name)
    if not os.path.isdir(other):
        subprocess.run(["git", "clone", "-q", origin, other], check=True, capture_output=True)
    _git(other, "fetch", "-q", "origin")
    _git(other, "switch", "-q", "-C", branch, f"origin/{branch}")
    _write(other, f"{name}.txt", "a follow-up after the merge\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "follow-up after the merge")
    _git(other, "push", "-q", "origin", branch)
    return _git(other, "rev-parse", "HEAD").strip()


def squash_then_edit(repo, name="squashed-then-edited"):
    """A two-commit branch squash-merged into the trunk, then the trunk edits
    the same line. Merging the trunk back into the branch now conflicts, so
    the tree check cannot see that it landed. Returns the squash commit.
    """
    _git(repo, "switch", "-q", "-c", name, "trunk")
    _write(repo, "notes.txt", "one\ntwo\nthree\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "notes, first pass")
    _write(repo, "notes.txt", "one\nTWO\nthree\n")
    _write(repo, "extra.txt", "extra\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "notes, second pass")
    _git(repo, "switch", "-q", "trunk")
    _git(repo, "merge", "--squash", name)
    _git(repo, "commit", "-m", "squash: notes")
    landing = _git(repo, "rev-parse", "HEAD").strip()
    _write(repo, "notes.txt", "one\n2\nthree\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "trunk rewrites the same line")
    _git(repo, "push", "-q", "origin", "trunk")
    _git(repo, "push", "-q", "-u", "origin", name)
    return landing

