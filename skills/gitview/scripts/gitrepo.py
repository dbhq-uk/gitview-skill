"""Every git subprocess call gitview makes. Nothing here writes to the repository."""
import os
import subprocess
import time
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
    """A working tree, or a bare repository, which has branches but no checkout."""
    answers = git(["rev-parse", "--is-inside-work-tree", "--is-bare-repository"], cwd, check=False)
    return "true" in answers.split()


def is_bare(cwd):
    return git(["rev-parse", "--is-bare-repository"], cwd, check=False) == "true"


def trunk(cwd):
    """The repository's main line, discovered rather than assumed.

    origin/HEAD is the honest answer where it exists. In a bare repository
    HEAD is the default branch, the one a clone checks out. Falling back to
    main then master covers a repository with no remote. None says plainly
    that nothing else in this table would mean anything.
    """
    head = git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], cwd, check=False)
    if head:
        return head.split("refs/remotes/origin/", 1)[-1]
    if is_bare(cwd):
        head = git(["symbolic-ref", "--quiet", "HEAD"], cwd, check=False)
        if head.startswith("refs/heads/") and git(["rev-parse", "--verify", "--quiet", head], cwd, check=False):
            return head[len("refs/heads/"):]
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


@dataclass
class Worktree:
    path: str
    head: object = None  # the commit checked out, or None
    branch: object = None  # the branch checked out, or None when detached or bare
    bare: bool = False  # the bare repository itself, which has no checkout
    locked: bool = False
    prunable: bool = False  # git says its directory has gone
    main: bool = False  # the first worktree, which git will not remove

    @property
    def missing(self):
        return not os.path.isdir(self.path)


def worktree_list(cwd):
    """Every worktree git knows about, with the state git records for it."""
    out = git(["worktree", "list", "--porcelain"], cwd, check=False)
    found, current = [], None
    for line in out.splitlines():
        if line.startswith("worktree "):
            current = Worktree(path=line.split(" ", 1)[1], main=not found)
            found.append(current)
        elif current is None:
            continue
        elif line.startswith("HEAD "):
            current.head = line.split(" ", 1)[1]
        elif line.startswith("branch refs/heads/"):
            current.branch = line[len("branch refs/heads/"):]
        elif line == "bare":
            current.bare = True
        elif line.split(" ", 1)[0] == "locked":
            current.locked = True
        elif line.split(" ", 1)[0] == "prunable":
            current.prunable = True
    return found


def worktree_paths(cwd):
    """Map branch name to the full path of the worktree holding it."""
    return {tree.branch: tree.path for tree in worktree_list(cwd) if tree.branch}


def _status(path, *extra):
    """The NUL-separated fields of `git status --porcelain=v1 -z` at PATH, or None.

    `--no-optional-locks` stops status refreshing the index, which would be a
    write, and fsmonitor is off so no monitor script or daemon is started.
    Output is read as bytes because a file name can be in any encoding.
    """
    if not os.path.isdir(path):
        return None
    result = subprocess.run(
        [
            "git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", path,
            "status", "--porcelain=v1", "-z", "--untracked-files=normal", *extra,
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    fields, index = [], 0
    raw = result.stdout.split(b"\0")
    while index < len(raw):
        entry = raw[index]
        index += 1
        if len(entry) < 3:
            continue
        fields.append(entry)
        if b"R" in entry[:2] or b"C" in entry[:2]:
            index += 1  # a rename or copy is followed by the path it came from
    return fields


def changes(path):
    """(changed, untracked) in the worktree at PATH, or None when it cannot be read."""
    fields = _status(path)
    if fields is None:
        return None
    untracked = sum(1 for entry in fields if entry[:2] == b"??")
    return len(fields) - untracked, untracked


def ignored(path):
    """The ignored paths in the worktree at PATH, or None when it cannot be read.

    `git worktree remove` counts these as clean and deletes them with the
    directory, so a local `.env` or a build cache goes too. A directory that is
    ignored as a whole is one entry, with a trailing slash.
    """
    fields = _status(path, "--ignored")
    if fields is None:
        return None
    return [
        entry[3:].decode("utf-8", "replace")
        for entry in fields
        if entry[:2] == b"!!"
    ]


def holding_ref(cwd, sha, prefer=None):
    """A ref that contains SHA, as a short name, or None when nothing does.

    PREFER, a local branch name, wins when it holds the commit. After that a
    local branch, then a remote-tracking ref, then a tag. Any of them keeps
    the commit alive when the worktree holding it goes.
    """
    out = git(
        ["for-each-ref", "--contains", sha, "--format=%(refname)", "refs/heads/", "refs/remotes/", "refs/tags/"],
        cwd,
        check=False,
    )
    refs = [ref for ref in out.splitlines() if ref and not ref.endswith("/HEAD")]
    if prefer and f"refs/heads/{prefer}" in refs:
        return prefer
    for prefix, label in (("refs/heads/", ""), ("refs/remotes/", ""), ("refs/tags/", "tag ")):
        for ref in refs:
            if ref.startswith(prefix):
                return label + ref[len(prefix):]
    return None


def has_remote_tracking_refs(cwd):
    return bool(git(["for-each-ref", "--count=1", "--format=%(refname)", "refs/remotes/"], cwd, check=False))


def worktrees(cwd):
    """Map branch name to the basename of the directory holding it.

    The basename often disagrees with the branch name, and seeing that is the
    point: a directory called after a branch deleted weeks ago misleads people.
    """
    return {name: os.path.basename(path) for name, path in worktree_paths(cwd).items()}


@dataclass
class Branch:
    name: str
    upstream: object  # the full upstream ref, such as refs/remotes/origin/x, or None
    gone: bool = False  # an upstream is configured but its ref no longer exists


def branches(cwd):
    out = git(
        ["for-each-ref", "--format=%(refname)%09%(upstream)%09%(upstream:track)", "refs/heads/"],
        cwd,
    )
    result = []
    for line in out.splitlines():
        refname, upstream, track = (line.split("\t") + ["", ""])[:3]
        if refname.startswith("refs/heads/"):
            result.append(
                Branch(
                    name=refname[len("refs/heads/"):],
                    upstream=upstream or None,
                    gone=track == "[gone]",
                )
            )
    return result


def remote_holding(cwd, name):
    """A remote-tracking ref that already contains the branch's tip, or None.

    Prefers one with the branch's own name. A branch pushed without -u has no
    upstream, but its commits are no less backed up for that.
    """
    out = git(
        ["for-each-ref", "--contains", f"refs/heads/{name}", "--format=%(refname:short)", "refs/remotes/"],
        cwd,
        check=False,
    )
    holders = [ref for ref in out.splitlines() if ref and not ref.endswith("/HEAD")]
    for ref in holders:
        if ref.split("/", 1)[-1] == name:
            return ref
    return holders[0] if holders else None


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
    """Commits in a range, or None when git could not count them.

    Never 0 on failure. A range whose end has gone would otherwise read as
    "nothing unpushed", which is the one wrong answer that loses work.
    """
    out = git(["rev-list", "--count", spec], cwd, check=False)
    return int(out) if out.isdigit() else None


def stash_count(cwd):
    out = git(["stash", "list"], cwd, check=False)
    return len(out.splitlines()) if out else 0


def last_fetch(cwd):
    """Seconds since this clone last fetched, from any worktree, or None if never.

    Every worktree keeps its own FETCH_HEAD, so the newest of them is the
    freshest the remote-tracking refs can be.
    """
    common = git(["rev-parse", "--git-common-dir"], cwd, check=False)
    if not common:
        return None
    common = os.path.abspath(os.path.join(cwd, common))
    candidates = [os.path.join(common, "FETCH_HEAD")]
    admin = os.path.join(common, "worktrees")
    if os.path.isdir(admin):
        candidates += [os.path.join(admin, entry, "FETCH_HEAD") for entry in os.listdir(admin)]
    times = [os.path.getmtime(path) for path in candidates if os.path.isfile(path)]
    return time.time() - max(times) if times else None


def remote_url(cwd):
    return git(["remote", "get-url", "origin"], cwd, check=False) or None
