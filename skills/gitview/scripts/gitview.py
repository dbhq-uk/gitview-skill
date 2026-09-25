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


def survey(cwd, want_prs=True):
    """Return (rows, notes). Notes are things the reader needs to know."""
    notes = []
    trunk_name = gitrepo.trunk(cwd)
    if trunk_name is None:
        raise gitrepo.GitError("no trunk found: looked for origin/HEAD, then main, then master")
    trunk_ref = gitrepo.trunk_ref(cwd, trunk_name)
    notes.append(f"Trunk is `{trunk_ref}`.")

    prs = {}
    if want_prs:
        prs, reason = forge.list_prs(forge.detect(gitrepo.remote_url(cwd)), cwd)
        if reason:
            notes.append(f"Pull request column skipped: {reason}.")

    checkouts = gitrepo.worktrees(cwd)
    rows = []
    for branch in gitrepo.branches(cwd):
        name = branch.name
        if branch.upstream:
            unpushed = str(gitrepo.count(cwd, f"{branch.upstream}..{name}"))
        else:
            unpushed = "no remote"

        if name == trunk_name:
            safe = "no, trunk"
        else:
            result = landed.verdict(cwd, trunk_ref, f"refs/heads/{name}")
            safe = "YES" if result.state == "landed" else f"no, {result.detail}"
            if safe == "YES" and _upstream_has_unlanded_work(cwd, trunk_name, trunk_ref, name):
                safe = "no, upstream has unlanded commits"

        rows.append(
            table.Row(
                worktree=checkouts.get(name, "-"),
                branch=name,
                pr=prs.get(name, "-"),
                ahead=gitrepo.count(cwd, f"{trunk_ref}..{name}"),
                behind=gitrepo.count(cwd, f"{name}..{trunk_ref}"),
                unpushed=unpushed,
                safe=safe,
            )
        )
    return rows, notes


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


def _upstream_has_unlanded_work(cwd, trunk_name, trunk_ref, name):
    """Somebody pushed to the remote copy after it landed, or never merged it."""
    up = gitrepo.upstream(cwd, name)
    if not _deletable_upstream(cwd, trunk_name, up):
        return False
    if up.sha == gitrepo.local_sha(cwd, name):
        return False
    return landed.verdict(cwd, trunk_ref, up.ref).state != "landed"


def _describe(result):
    if result.state == "landed":
        return "adds nothing to trunk"
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

    result = landed.verdict(cwd, trunk_ref, f"refs/heads/{branch}")
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
        up_result = landed.verdict(cwd, trunk_ref, up.ref)
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
