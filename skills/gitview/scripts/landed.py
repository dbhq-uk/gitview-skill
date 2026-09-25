"""Decides whether a branch still contributes anything to the trunk.

A branch is finished when merging the trunk into it produces the trunk's tree
exactly. Then it adds nothing, whatever its commit count says.

Read references/safe-to-delete.md before changing any of this. Both of the
obvious cheaper tests are wrong, and the wrongness is silent: they do not
error, they quietly report live work forever.

On git 2.38 or later the merge is `git merge-tree --write-tree`, which computes
the merged tree in the object store and touches nothing else: no worktree, no
index, no hooks, no commit, and none of the user's commit or merge settings.
Older git has no such command, so it falls back to a real merge in a throwaway
worktree, isolated from hooks and config as far as git allows.
"""
import functools
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

import gitrepo


@dataclass
class Verdict:
    state: str  # landed, unlanded, conflicts
    detail: str


@functools.lru_cache(maxsize=None)
def _git_version():
    out = subprocess.run(["git", "version"], capture_output=True, text=True).stdout
    found = re.search(r"(\d+)\.(\d+)", out)
    return (int(found.group(1)), int(found.group(2))) if found else (0, 0)


def has_merge_tree():
    """`git merge-tree --write-tree` arrived in git 2.38."""
    return _git_version() >= (2, 38)


def _tree(cwd, ref):
    return gitrepo.git(["rev-parse", f"{ref}^{{tree}}"], cwd, check=False)


def _shown(names):
    return ", ".join(names[:3]) + (", ..." if len(names) > 3 else "")


def _compare(cwd, trunk_ref, merged_tree):
    """Landed when the merge result is the trunk's tree, byte for byte."""
    if merged_tree == _tree(cwd, trunk_ref):
        return Verdict("landed", "adds nothing to trunk")
    stat = gitrepo.git(["diff", "--shortstat", trunk_ref, merged_tree], cwd, check=False)
    return Verdict("unlanded", stat.strip() or "differs from trunk")


def _merge_tree(cwd, trunk_ref, branch):
    """The merge, computed without a worktree. Exit 1 means conflicts."""
    result = subprocess.run(
        [
            "git", "-C", cwd, "merge-tree", "--write-tree", "--name-only", "-z",
            "--no-messages", branch, trunk_ref,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        reason = (result.stderr or "").strip().split("\n")[0] or "merge-tree failed"
        return Verdict("unlanded", f"could not merge with the trunk: {reason}")
    parts = result.stdout.split("\0")
    tree, conflicted = parts[0].strip(), [name for name in parts[1:] if name]
    if result.returncode == 1:
        return Verdict("conflicts", _shown(conflicted) or "unknown files")
    return _compare(cwd, trunk_ref, tree)


def fast_is_landed(cwd, trunk_ref, branch):
    """Old git only: a trivial three-way merge into a temporary index.

    Definitive only when it says yes. If every path resolved to the trunk's
    version then the branch either never touched it or agrees with it, which is
    exactly what contributing nothing means.

    A no answer proves nothing, because read-tree refuses any file both sides
    edited, even where a real merge would combine the two edits cleanly. That
    is why a no falls through to the real merge below.
    """
    base = gitrepo.git(["merge-base", trunk_ref, branch], cwd, check=False)
    if not base:
        return False

    handle, index = tempfile.mkstemp(prefix="gitview-index-")
    os.close(handle)
    os.unlink(index)
    env = dict(os.environ, GIT_INDEX_FILE=index)

    def run(args):
        return subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True, env=env
        )

    try:
        if run(["read-tree", "-m", "--aggressive", base, branch, trunk_ref]).returncode != 0:
            return False
        if run(["ls-files", "-u"]).stdout.strip():
            return False
        written = run(["write-tree"])
        if written.returncode != 0:
            return False
        return written.stdout.strip() == _tree(cwd, trunk_ref)
    finally:
        if os.path.exists(index):
            os.unlink(index)


# Everything the throwaway merge must not inherit from the user or the
# repository. No hooks run, nothing is signed or verified, rerere neither
# replays nor records, and a merge.ff=only setting cannot turn it into a no-op.
_ISOLATED = [
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.fsmonitor=false",
    "-c", "commit.gpgSign=false",
    "-c", "merge.verifySignatures=false",
    "-c", "rerere.enabled=false",
]

# A fixed identity, in case anything asks. --no-commit means nothing should.
_IDENTITY = {
    "GIT_AUTHOR_NAME": "gitview",
    "GIT_AUTHOR_EMAIL": "gitview@localhost",
    "GIT_COMMITTER_NAME": "gitview",
    "GIT_COMMITTER_EMAIL": "gitview@localhost",
    "GIT_LFS_SKIP_SMUDGE": "1",
}


def _isolated(args, cwd):
    return subprocess.run(
        ["git", *_ISOLATED, "-C", cwd, *args],
        capture_output=True,
        text=True,
        env=dict(os.environ, **_IDENTITY),
    )


def _forget_worktree(cwd, path):
    """Remove the one worktree this module created, and nothing else.

    Never `git worktree prune`. That acts on every worktree in the repository,
    and it drops the registration of any whose directory is briefly absent, an
    unmounted drive or a directory mid-move. After that, `git branch -D` will
    delete a branch that is still checked out there.
    """
    if _isolated(["worktree", "remove", "--force", path], cwd).returncode == 0:
        return
    common = gitrepo.git(["rev-parse", "--git-common-dir"], cwd, check=False)
    admin = os.path.join(os.path.abspath(os.path.join(cwd, common)), "worktrees") if common else ""
    if not os.path.isdir(admin):
        return
    expected = os.path.realpath(os.path.join(path, ".git"))
    for entry in os.listdir(admin):
        pointer = os.path.join(admin, entry, "gitdir")
        try:
            with open(pointer, encoding="utf-8") as fh:
                if os.path.realpath(fh.read().strip()) == expected:
                    shutil.rmtree(os.path.join(admin, entry), ignore_errors=True)
        except OSError:
            continue


def _worktree_merge(cwd, trunk_ref, branch):
    """Old git only: a real merge in a throwaway detached worktree.

    Only reached where the fast check could not prove the branch finished.
    --no-commit leaves the result in the index, so no commit, signature or
    identity is needed, and --no-ff stops a fast-forward standing in for it.
    """
    tmp = tempfile.mkdtemp(prefix="gitview-merge-")
    path = os.path.join(tmp, "wt")
    try:
        added = _isolated(["worktree", "add", "--detach", path, branch], cwd)
        if added.returncode != 0:
            return Verdict("unlanded", f"could not check out: {added.stderr.strip()}")

        _isolated(["merge", "--no-commit", "--no-ff", "--no-edit", trunk_ref], path)
        conflicted = _isolated(["diff", "--name-only", "--diff-filter=U"], path).stdout.strip()
        if conflicted:
            return Verdict("conflicts", _shown(conflicted.split("\n")))
        return _compare(cwd, trunk_ref, _isolated(["write-tree"], path).stdout.strip())
    finally:
        _forget_worktree(cwd, path)
        shutil.rmtree(tmp, ignore_errors=True)


def verdict(cwd, trunk_ref, branch):
    """Is this branch finished? merge-tree where git has it, else the fallback."""
    if has_merge_tree():
        return _merge_tree(cwd, trunk_ref, branch)
    if fast_is_landed(cwd, trunk_ref, branch):
        return Verdict("landed", "adds nothing to trunk")
    return _worktree_merge(cwd, trunk_ref, branch)
