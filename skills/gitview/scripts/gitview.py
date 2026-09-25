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
    it is already on the trunk.
    """
    if row.safe.startswith("YES"):
        return False
    if row.unpushed in ("gone", "no remote", "?"):
        return True
    return row.unpushed.isdigit() and int(row.unpushed) > 0


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

    checkouts = gitrepo.worktrees(cwd)
    rows = []
    for branch in gitrepo.branches(cwd):
        name = branch.name
        ref = f"refs/heads/{name}"

        if name == trunk_name:
            safe = "no, trunk"
        else:
            result = _judge(cwd, trunk_ref, ref, merged)
            safe = _safe_label(result)
            if result.state == "landed" and _upstream_has_unlanded_work(
                cwd, trunk_name, trunk_ref, name, merged
            ):
                safe = "no, upstream has unlanded commits"

        ahead = gitrepo.count(cwd, f"{trunk_ref}..{ref}")
        behind = gitrepo.count(cwd, f"{ref}..{trunk_ref}")
        rows.append(
            table.Row(
                worktree=checkouts.get(name, "-"),
                branch=name,
                pr=prs.get(name, "-"),
                ahead="?" if ahead is None else ahead,
                behind="?" if behind is None else behind,
                unpushed=_unpushed(cwd, branch),
                safe=safe,
            )
        )

    risky = [row for row in table.order(rows) if at_risk(row)]
    if risky:
        listed = ", ".join(f"`{row.branch}` ({_risk_reason(row.unpushed)})" for row in risky)
        notes.insert(0, f"At risk of being lost: {listed}.")

    fetched = _fetch_note(cwd)
    if fetched:
        notes.append(fetched)
    stashes = gitrepo.stash_count(cwd)
    if stashes:
        entries = "1 stash entry exists" if stashes == 1 else f"{stashes} stash entries exist"
        notes.append(f"{entries} in this clone. Stashes are local only and are not in the table.")
    return rows, notes


def _risk_reason(unpushed):
    if unpushed == "gone":
        return "its upstream was deleted on the remote"
    if unpushed == "no remote":
        return "no remote holds it"
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


def _verify(cwd, branch, want_prs=True):
    """Exit 0 only when every deletion gate passes. Run it right before deleting.

    The gates: the branch is not the trunk, it adds nothing to the trunk, its
    upstream adds nothing either, no worktree has it checked out, and it has no
    open pull request. On a pass it prints the local and remote SHAs and the
    exact delete commands, with the remote delete leased to the SHA it checked,
    so a push that lands after this check makes the delete fail rather than
    destroy somebody's commit.
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

    checked_out = gitrepo.worktree_paths(cwd).get(branch)
    if checked_out:
        refusals.append(f"it is checked out in the worktree at {checked_out}")

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
