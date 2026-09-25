"""Every git subprocess call gitview makes. Nothing here writes to the repository."""
import os
import subprocess
from dataclasses import dataclass


class GitError(RuntimeError):
    pass


def git(args, cwd, check=True):
    """Run git and return stdout stripped. Raises GitError when check and it fails."""
    result = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    if result.returncode != 0:
        if check:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return ""
    return result.stdout.strip()


def is_repo(cwd):
    return git(["rev-parse", "--is-inside-work-tree"], cwd, check=False) == "true"


def trunk(cwd):
    """The repository's main line, discovered rather than assumed.

    origin/HEAD is the honest answer where it exists. Falling back to main then
    master covers a repository with no remote. None says plainly that nothing
    else in this table would mean anything.
    """
    head = git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], cwd, check=False)
    if head:
        return head.split("refs/remotes/origin/", 1)[-1]
    for name in ("main", "master"):
        if git(["rev-parse", "--verify", "--quiet", name], cwd, check=False):
            return name
    return None


def trunk_ref(cwd, name):
    """Prefer the remote-tracking trunk, because a local one can be stale."""
    remote = f"origin/{name}"
    if git(["rev-parse", "--verify", "--quiet", remote], cwd, check=False):
        return remote
    return name


def worktree_paths(cwd):
    """Map branch name to the full path of the worktree holding it."""
    out = git(["worktree", "list", "--porcelain"], cwd, check=False)
    found, path = {}, None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line.split(" ", 1)[1]
        elif line.startswith("branch refs/heads/") and path:
            found[line[len("branch refs/heads/"):]] = path
    return found


def worktrees(cwd):
    """Map branch name to the basename of the directory holding it.

    The basename often disagrees with the branch name, and seeing that is the
    point: a directory called after a branch deleted weeks ago misleads people.
    """
    return {name: os.path.basename(path) for name, path in worktree_paths(cwd).items()}


@dataclass
class Branch:
    name: str
    upstream: object  # str or None


def branches(cwd):
    out = git(["for-each-ref", "--format=%(refname:short)%09%(upstream:short)", "refs/heads/"], cwd)
    result = []
    for line in out.splitlines():
        name, _, upstream = line.partition("\t")
        if name:
            result.append(Branch(name=name, upstream=upstream or None))
    return result


@dataclass
class Upstream:
    ref: str  # refs/remotes/origin/x, or refs/heads/y when it tracks a local branch
    remote: str  # origin, or "." when it tracks a local branch
    remote_ref: str  # the branch's name on the remote, as refs/heads/x
    sha: object  # str, or None when the ref no longer exists

    @property
    def on_a_remote(self):
        return self.remote != "." and self.ref.startswith("refs/remotes/")


def local_sha(cwd, name):
    """The commit refs/heads/NAME points at, or None.

    Only refs/heads/ is looked at. A bare name would resolve a tag or a
    remote-tracking ref of the same name first, and then a check would be run
    against something other than the branch about to be deleted.
    """
    return git(["rev-parse", "--verify", "--quiet", f"refs/heads/{name}^{{commit}}"], cwd, check=False) or None


def upstream(cwd, name):
    """The branch's configured upstream, read from git rather than assumed.

    None when no upstream is configured. An Upstream with sha None when one is
    configured but its ref no longer exists, which is what `[gone]` means.
    """
    out = git(
        [
            "for-each-ref",
            "--format=%(refname)%09%(upstream)%09%(upstream:remotename)%09%(upstream:remoteref)",
            f"refs/heads/{name}",
        ],
        cwd,
        check=False,
    )
    for line in out.splitlines():
        refname, ref, remote, remote_ref = (line.split("\t") + ["", "", ""])[:4]
        if refname != f"refs/heads/{name}" or not ref:
            continue
        sha = git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd, check=False) or None
        return Upstream(ref=ref, remote=remote, remote_ref=remote_ref, sha=sha)
    return None


def remote_head(cwd, remote):
    """The ref a remote's HEAD points at, such as refs/remotes/origin/main."""
    return git(["symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD"], cwd, check=False) or None


def count(cwd, spec):
    out = git(["rev-list", "--count", spec], cwd, check=False)
    return int(out) if out.isdigit() else 0


def remote_url(cwd):
    return git(["remote", "get-url", "origin"], cwd, check=False) or None
