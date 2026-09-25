#!/usr/bin/env python3
"""Survey every branch and worktree in a repository.

Read only. It never deletes, pushes, merges or checks an existing branch out.
The actions live in SKILL.md so that nothing destructive sits in a script that
could be run unattended.
"""
import argparse
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forge  # noqa: E402
import gitrepo  # noqa: E402
import landed  # noqa: E402
import table  # noqa: E402


def _judge(cwd, trunk_ref, ref, merged):
    """landed.verdict, plus the third signal: a merged pull request whose head
    is exactly this commit. Matched on the SHA, never on the branch name.
    """
    result = landed.verdict(cwd, trunk_ref, ref)
    if result.state == "landed" or merged is None:
        return result
    sha = gitrepo.git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd, check=False)
    number = merged.number(sha)
    if number:
        return landed.Verdict("landed", f"merged in PR {number}")
    return result


def _safe_label(result):
    """YES names the signal that proved it. A no says why not."""
    if result.state == "landed":
        return f"YES, {result.detail}"
    return f"no, {result.detail}"


def _unpushed(cwd, branch):
    """How much of the branch exists only in this clone.

    A number counts commits not on its upstream. `gone` means the upstream was
    deleted on the remote. `on <ref>` means no upstream is set but a remote
    already holds the tip. `no remote` means no remote holds it at all.
    """
    if branch.gone:
        return "gone"
    if branch.upstream and branch.upstream.startswith("refs/remotes/"):
        unpushed = gitrepo.count(cwd, f"{branch.upstream}..refs/heads/{branch.name}")
        return "?" if unpushed is None else str(unpushed)
    holder = gitrepo.remote_holding(cwd, branch.name)
    return f"on {holder}" if holder else "no remote"


def at_risk(row):
    """Not landed, and some of it exists nowhere but here.

    A landed branch is never at risk, whatever its Unpushed says: everything in
    it is already on the trunk. That holds when its worktree stops it being a
    YES, too. Uncommitted edits are shown in Dirty, not here.
    """
    if row.landed or row.safe.startswith("YES"):
        return False
    if row.unpushed in ("gone", "no remote", "no branch", "?"):
        return True
    return row.unpushed.isdigit() and int(row.unpushed) > 0


def _worktree_label(tree):
    """The directory's basename, plus any state git records against it."""
    flags = []
    if tree.locked:
        flags.append("locked")
    if tree.prunable:
        flags.append("prunable")
    elif tree.missing:
        flags.append("missing")
    name = os.path.basename(tree.path)
    return f"{name} ({', '.join(flags)})" if flags else name


def _dirty_label(counts):
    if counts is None:
        return "?"
    changed, untracked = counts
    parts = []
    if changed:
        parts.append(f"{changed} changed")
    if untracked:
        parts.append(f"{untracked} untracked")
    return ", ".join(parts) or "no"


def _worktree_blocker(tree, counts):
    """What about a worktree stops its landed branch being a YES, or None.

    Uncommitted work is not on the trunk, whatever the branch's commits say.
    A missing directory may be a drive not mounted yet, so its contents are
    unknown rather than clean. A lock is somebody saying keep this.
    """
    if tree.prunable or tree.missing:
        return "directory is missing"
    if counts is None:
        return "could not be read"
    if any(counts):
        return "has uncommitted changes"
    if tree.locked:
        return "is locked"
    return None


def _detached_row(cwd, tree, counts, trunk_name, trunk_ref):
    """A worktree with no branch. Its commit is safe only while a ref holds it."""
    holder = gitrepo.holding_ref(cwd, tree.head, prefer=trunk_name)
    ahead = gitrepo.count(cwd, f"{trunk_ref}..{tree.head}")
    behind = gitrepo.count(cwd, f"{tree.head}..{trunk_ref}")
    return table.Row(
        worktree=_worktree_label(tree),
        dirty=_dirty_label(counts),
        branch=tree.head[:7],
        pr="-",
        ahead="?" if ahead is None else ahead,
        behind="?" if behind is None else behind,
        unpushed=f"on {holder}" if holder else "no branch",
        safe="-",
        detached=True,
    )


def _ago(seconds):
    minutes = int(seconds // 60)
    if minutes < 1:
        return "less than a minute ago"
    if minutes < 120:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hours ago"
    return f"{hours // 24} days ago"


def _fetch_note(cwd):
    if not gitrepo.git(["remote"], cwd, check=False):
        return None
    since = gitrepo.last_fetch(cwd)
    if since is None:
        return (
            "No fetch is recorded in this clone, so the remote-tracking refs may be stale. "
            "`git fetch --prune` refreshes them."
        )
    return (
        f"Remote-tracking refs were last fetched {_ago(since)}. "
        "`git fetch --prune` refreshes them."
    )


def survey(cwd, want_prs=True):
    """Return (rows, notes). Notes are things the reader needs to know."""
    notes = []
    trunk_name = gitrepo.trunk(cwd)
    if trunk_name is None:
        raise gitrepo.GitError("no trunk found: looked for origin/HEAD, then main, then master")
    trunk_ref = gitrepo.trunk_ref(cwd, trunk_name)
    notes.append(f"Trunk is `{trunk_ref}`.")

    prs, merged = {}, None
    if want_prs:
        kind = forge.detect(gitrepo.remote_url(cwd))
        prs, reason = forge.list_prs(kind, cwd)
        if reason:
            notes.append(f"Pull request column skipped: {reason}.")
        else:
            merged = forge.MergedHeads(kind, cwd)

    trees = [tree for tree in gitrepo.worktree_list(cwd) if not tree.bare]
    counts = {tree.path: gitrepo.changes(tree.path) for tree in trees}
    by_branch = {tree.branch: tree for tree in trees if tree.branch}
    push_to = _push_remote(cwd)
    rows, pushes, held = [], [], []
    for branch in gitrepo.branches(cwd):
        name = branch.name
        ref = f"refs/heads/{name}"

        finished = False
        if name == trunk_name:
            safe = "no, trunk"
        else:
            result = _judge(cwd, trunk_ref, ref, merged)
            safe = _safe_label(result)
            if result.state == "landed" and _upstream_has_unlanded_work(
                cwd, trunk_name, trunk_ref, name, merged
            ):
                safe = "no, upstream has unlanded commits"
            finished = safe.startswith("YES")

        tree = by_branch.get(name)
        if tree is not None and finished:
            blocker = _worktree_blocker(tree, counts[tree.path])
            if blocker:
                safe = f"no, landed but its worktree {blocker}"

        ahead = gitrepo.count(cwd, f"{trunk_ref}..{ref}")
        behind = gitrepo.count(cwd, f"{ref}..{trunk_ref}")
        row = table.Row(
            worktree=_worktree_label(tree) if tree else "-",
            dirty=_dirty_label(counts[tree.path]) if tree else "-",
            branch=name,
            pr=prs.get(name, "-"),
            ahead="?" if ahead is None else ahead,
            behind="?" if behind is None else behind,
            unpushed=_unpushed(cwd, branch),
            safe=safe,
            landed=finished,
        )
        rows.append(row)

        if name == trunk_name:
            diverged = _trunk_divergence(cwd, branch)
            if diverged:
                notes.append(diverged)
        else:
            command, reason = _push_offer(cwd, branch, row, push_to)
            if command:
                pushes.append(command)
            if reason:
                held.append(reason)

    for tree in trees:
        if tree.branch is None and tree.head:
            rows.append(_detached_row(cwd, tree, counts[tree.path], trunk_name, trunk_ref))

    risky = [row for row in table.order(rows) if at_risk(row)]
    if risky:
        listed = ", ".join(_risk_item(row) for row in risky)
        notes.insert(0, f"At risk of being lost: {listed}.")

    if pushes:
        listed = ", ".join(f"`{command}`" for command in pushes)
        notes.append(f"To push the work that has not landed, run exactly: {listed}.")
    if held:
        notes.append(f"Not offered for a push: {'; '.join(held)}.")

    if gitrepo.is_bare(cwd) and gitrepo.git(["remote"], cwd, check=False) and not gitrepo.has_remote_tracking_refs(cwd):
        notes.append(
            "This bare repository has no remote-tracking refs, so `no remote` means gitview "
            "cannot see a remote copy, not that none exists."
        )

    fetched = _fetch_note(cwd)
    if fetched:
        notes.append(fetched)
    stashes = gitrepo.stash_count(cwd)
    if stashes:
        entries = "1 stash entry exists" if stashes == 1 else f"{stashes} stash entries exist"
        notes.append(f"{entries} in this clone. Stashes are local only and are not in the table.")
    return rows, notes


def _push_remote(cwd):
    """The remote a branch with no upstream would be pushed to, or None.

    `origin` when there is one, or the only remote. With several and no
    `origin`, which one is meant is the user's call, not a guess.
    """
    remotes = gitrepo.git(["remote"], cwd, check=False).split()
    if "origin" in remotes:
        return "origin"
    return remotes[0] if len(remotes) == 1 else None


def _push_offer(cwd, branch, row, push_to):
    """(command, reason): the push worth offering for BRANCH, or why it is held back.

    Either may be None. Never a landed branch: everything in it is on the
    trunk already, so a push only makes a remote branch nobody needs. Never a
    branch behind its upstream: the remote would reject it. The trunk never
    gets here at all.
    """
    if row.landed or row.safe.startswith("YES"):
        return None, None
    git = f"git -C {shlex.quote(cwd)}"
    name = branch.name
    if row.unpushed == "no remote":
        if push_to is None:
            return None, None
        flag = "-u " if branch.upstream is None else ""
        return f"{git} push {flag}{shlex.quote(push_to)} {shlex.quote(name)}", None
    if not (row.unpushed.isdigit() and int(row.unpushed) > 0):
        return None, None
    up = gitrepo.upstream(cwd, name)
    if up is None or up.sha is None or not up.on_a_remote:
        return None, None
    behind = gitrepo.count(cwd, f"refs/heads/{name}..{up.ref}")
    if behind is None or behind > 0:
        count = "an unknown number of" if behind is None else str(behind)
        return None, (
            f"`{name}` is also {count} behind its upstream, so the remote would reject it. "
            "Pull or rebase first"
        )
    target = up.remote_ref[len("refs/heads/"):] if up.remote_ref.startswith("refs/heads/") else up.remote_ref
    refspec = shlex.quote(f"{name}:{target}")
    return f"{git} push {shlex.quote(up.remote)} {refspec}", None


def _trunk_divergence(cwd, branch):
    """A note when the local trunk has commits its upstream does not.

    gitview never offers to push the trunk. A diverged trunk would be
    rejected, and in many repositories a push to the trunk is a deploy. So it
    says what it found and leaves the call to the user.
    """
    up = gitrepo.upstream(cwd, branch.name)
    if up is None or up.sha is None or not up.on_a_remote:
        return None
    short = up.ref[len("refs/remotes/"):]
    ahead = gitrepo.count(cwd, f"{up.ref}..refs/heads/{branch.name}")
    behind = gitrepo.count(cwd, f"refs/heads/{branch.name}..{up.ref}")
    if not ahead:
        return None
    if behind:
        return (
            f"Local `{branch.name}` has diverged from `{short}`: {ahead} commit"
            f"{'s' if ahead != 1 else ''} only here, {behind} only there. A push would be "
            "rejected, and gitview never offers to push the trunk. Reconcile it by hand."
        )
    return (
        f"Local `{branch.name}` has {ahead} commit{'s' if ahead != 1 else ''} `{short}` "
        "does not. gitview never offers to push the trunk: that is your call."
    )


def _risk_item(row):
    if row.detached:
        where = row.worktree.split(" (", 1)[0]
        return f"detached `{row.branch}` in `{where}` ({_risk_reason(row.unpushed)})"
    return f"`{row.branch}` ({_risk_reason(row.unpushed)})"


def _risk_reason(unpushed):
    if unpushed == "gone":
        return "its upstream was deleted on the remote"
    if unpushed == "no remote":
        return "no remote holds it"
    if unpushed == "no branch":
        return "no branch holds it"
    if unpushed == "?":
        return "could not count its unpushed commits"
    return f"{unpushed} unpushed"


def _deletable_upstream(cwd, trunk_name, up):
    """True when the upstream is a remote branch gitview may offer to delete.

    Never a local branch, never the trunk under any remote, and never whatever
    a remote's HEAD points at. A branch created from origin/main tracks
    origin/main, and deleting "its upstream" would delete the trunk.
    """
    if up is None or up.sha is None or not up.on_a_remote:
        return False
    if up.remote_ref == f"refs/heads/{trunk_name}":
        return False
    return up.ref != gitrepo.remote_head(cwd, up.remote)


def _upstream_has_unlanded_work(cwd, trunk_name, trunk_ref, name, merged=None):
    """Somebody pushed to the remote copy after it landed, or never merged it."""
    up = gitrepo.upstream(cwd, name)
    if not _deletable_upstream(cwd, trunk_name, up):
        return False
    if up.sha == gitrepo.local_sha(cwd, name):
        return False
    return _judge(cwd, trunk_ref, up.ref, merged).state != "landed"


def _describe(result):
    if result.state == "landed":
        return result.detail
    if result.state == "conflicts":
        return f"conflicts with the trunk in {result.detail}"
    return result.detail


def _pr_gate(cwd, names):
    """Return a refusal reason, or None when no open pull request was found.

    An unanswerable lookup is a refusal, not a pass. The gate exists because
    deleting the head branch of an open pull request closes it, so a check
    that could not run must not read the same as a check that found nothing.
    """
    url = gitrepo.remote_url(cwd)
    if url is None or forge.is_local(url):
        return None
    kind = forge.detect(url)
    if kind is None:
        return (
            "could not check for an open pull request: gitview cannot query pull requests "
            "on the host of origin. Re-run with --no-pr only if you know there is none"
        )
    prs, reason = forge.list_prs(kind, cwd)
    if reason:
        return (
            f"could not check for an open pull request: {reason}. "
            "Re-run with --no-pr only if you know there is none"
        )
    for name in names:
        if name in prs:
            return f"it has an open pull request: {prs[name]}"
    return None


def _offer_removal(cwd, tree):
    """Print the command that removes a clean worktree, and what it takes with it.

    Never with --force. Without it git refuses a worktree that has changes or
    untracked files, so a worktree that gained an edit since this check stays.
    What git does not refuse is ignored files: they count as clean and go with
    the directory, so they are listed here before anybody agrees to it.
    """
    print("Nothing else refused and the worktree is clean. Remove it, then verify again:")
    print(f"  git -C {shlex.quote(cwd)} worktree remove {shlex.quote(tree.path)}")
    paths = gitrepo.ignored(tree.path)
    if paths is None:
        print("Could not list the ignored files in it. Look before removing it: they go with it.")
    elif paths:
        shown = ", ".join(paths[:5]) + (f" and {len(paths) - 5} more" if len(paths) > 5 else "")
        noun = "path" if len(paths) == 1 else "paths"
        print(f"It also deletes {len(paths)} ignored {noun} in that directory: {shown}.")


def _verify(cwd, branch, want_prs=True):
    """Exit 0 only when every deletion gate passes. Run it right before deleting.

    The gates: the branch is not the trunk, it adds nothing to the trunk, its
    upstream adds nothing either, no worktree has it checked out, and it has no
    open pull request. On a pass it prints the local and remote SHAs and the
    exact delete commands, with the remote delete leased to the SHA it checked,
    so a push that lands after this check makes the delete fail rather than
    destroy somebody's commit.

    When a worktree is the only gate that refused, and it is a linked worktree
    that is clean, unlocked and present, it prints the command that removes
    it, never with --force. Removing it and verifying again is the way to
    delete a finished branch that still has a worktree.
    """
    trunk_name = gitrepo.trunk(cwd)
    if trunk_name is None:
        print("no trunk found", file=sys.stderr)
        return 2
    if branch.startswith("refs/heads/"):
        branch = branch[len("refs/heads/"):]
    sha = gitrepo.local_sha(cwd, branch)
    if sha is None:
        print(f"no such branch: {branch}", file=sys.stderr)
        return 2
    if branch == trunk_name:
        print(f"Refused: {branch} is the trunk.")
        return 1

    trunk_ref = gitrepo.trunk_ref(cwd, trunk_name)
    refusals = []
    merged = None
    if want_prs:
        url = gitrepo.remote_url(cwd)
        kind = forge.detect(url) if url else None
        merged = forge.MergedHeads(kind, cwd) if kind else None

    result = _judge(cwd, trunk_ref, f"refs/heads/{branch}", merged)
    print(f"{branch}: {result.state} ({_describe(result)})")
    print(f"local:  refs/heads/{branch} at {sha}")
    if result.state != "landed":
        refusals.append(f"the branch has work that has not landed ({_describe(result)})")

    up = gitrepo.upstream(cwd, branch)
    remote = None
    if up is None:
        print("remote: no upstream is configured, so there is no remote branch to delete")
    elif up.sha is None:
        print(f"remote: {up.ref} is gone, so there is no remote branch to delete")
    elif not _deletable_upstream(cwd, trunk_name, up):
        print(f"remote: the upstream is {up.ref}, which gitview never deletes")
    else:
        up_result = _judge(cwd, trunk_ref, up.ref, merged)
        print(f"remote: {up.remote} {up.remote_ref} at {up.sha}, {_describe(up_result)}")
        if up_result.state != "landed":
            refusals.append(
                f"the remote branch has commits that have not landed ({_describe(up_result)}). "
                "Somebody may have pushed to it after it merged"
            )
        remote = up

    removable, worktree_refusal = None, None
    tree = next((t for t in gitrepo.worktree_list(cwd) if t.branch == branch and not t.bare), None)
    if tree is not None:
        blocker = _worktree_blocker(tree, gitrepo.changes(tree.path))
        if tree.main:
            worktree_refusal = f"it is checked out in the main worktree at {tree.path}, which git cannot remove"
        elif blocker:
            joiner = "whose" if blocker.startswith("directory") else "which"
            worktree_refusal = f"it is checked out in the worktree at {tree.path}, {joiner} {blocker}"
        else:
            worktree_refusal = f"it is checked out in the worktree at {tree.path}"
            removable = tree
        refusals.append(worktree_refusal)

    if want_prs:
        names = [branch]
        if up is not None and up.remote_ref.startswith("refs/heads/"):
            names.append(up.remote_ref[len("refs/heads/"):])
        refused = _pr_gate(cwd, names)
        if refused:
            refusals.append(refused)

    if refusals:
        for reason in refusals:
            print(f"Refused: {reason}.")
        if removable is not None and refusals == [worktree_refusal]:
            _offer_removal(cwd, removable)
        return 1

    git = f"git -C {shlex.quote(cwd)}"
    print("Every gate passed. Delete with exactly these commands:")
    print(f"  {git} branch -D {shlex.quote(branch)}")
    if remote is not None:
        lease = shlex.quote(f"--force-with-lease={remote.remote_ref}:{remote.sha}")
        print(
            f"  {git} push {lease} {shlex.quote(remote.remote)} "
            f"--delete {shlex.quote(remote.remote_ref)}"
        )
    print("To undo:")
    print(f"  {git} branch {shlex.quote(branch)} {sha}")
    if remote is not None:
        print(
            f"  {git} push {shlex.quote(remote.remote)} "
            f"{shlex.quote(f'{remote.sha}:{remote.remote_ref}')}"
        )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Survey branches and worktrees.")
    parser.add_argument("path", nargs="?", default=".", help="repository path")
    parser.add_argument(
        "--verify",
        metavar="BRANCH",
        help="exit 0 only if every deletion gate passes for BRANCH, and print the "
        "delete commands. Run this before deleting it",
    )
    parser.add_argument(
        "--no-pr",
        action="store_true",
        help="skip the pull request lookup. With --verify, skips the open pull request gate",
    )
    args = parser.parse_args(argv)

    cwd = os.path.abspath(args.path)
    if not gitrepo.is_repo(cwd):
        print(f"{cwd} is not a git repository", file=sys.stderr)
        return 2

    try:
        if args.verify:
            return _verify(cwd, args.verify, want_prs=not args.no_pr)
        rows, notes = survey(cwd, want_prs=not args.no_pr)
    except gitrepo.GitError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(table.render(rows))
    if notes:
        print()
        for note in notes:
            print(note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
