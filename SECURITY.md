# Security

## Reporting a vulnerability

Email <dan@dbhq.uk> rather than opening a public issue. Include what you found,
how to reproduce it, and what an attacker could do with it. You will get a first
response within 48 hours.

## What this skill does

### Network

**Only the pull request lookup, and only through a tool you already trust.**
gitview shells out to `gh pr list` on GitHub and `az repos pr list` on Azure
DevOps, using whatever credential those CLIs already hold. It lists open pull
requests, and, only when a branch cannot be proved landed from the repository
alone, recently merged ones. It never handles a token itself and never makes an
HTTP request of its own. `--no-pr` skips both lookups and the skill then works
offline.

### On disk

`scripts/gitview.py` never deletes, pushes, merges or checks out a branch, and
it never writes to your working tree, your index or any ref. It is not strictly
read only, and this is exactly what it writes:

- **On git 2.38 or later**, the test merge is `git merge-tree --write-tree`. That
  writes the merged trees and blobs into the object store, and nothing else. No
  worktree, no index, no commit. It runs no hooks and ignores your commit and
  signing settings. Nothing refers to those objects, so `git gc` removes them in
  due course.
- **On older git**, which has no `merge-tree --write-tree`, it falls back to a
  temporary git index under `tempfile.mkstemp`, then a detached worktree under
  `tempfile.mkdtemp` where it merges with `--no-commit`. That run has hooks
  switched off (`core.hooksPath=/dev/null`), signing and signature checks off,
  rerere off and a fixed identity. The worktree is removed with
  `git worktree remove --force`, and only that worktree. It never runs
  `git worktree prune`, which would act on every worktree in the repository.

That test merge is the whole reason the "safe to delete" column can be trusted
where a repository squashes on merge, and it is why the work never happens in
your checkout.

### The deletions

**gitview does not delete anything. The agent does, and only after you agree.**
This is the part worth reading twice, because the skill's job is to make a
destructive suggestion.

`SKILL.md` instructs the agent to offer deletions only after showing the table,
to ask first, and before each delete to re-verify the branch with
`gitview.py --verify BRANCH`.

`--verify` enforces the gates in code. It exits non-zero, and says why, for the
trunk, for a branch that adds anything to the trunk, for a branch whose remote
copy carries commits that have not landed, for a branch checked out in any
worktree, and for a branch with an open pull request. If it cannot check for an
open pull request it refuses rather than passes.

On a pass it prints the local and remote SHAs, the undo commands, and the delete
commands. The remote delete is `git push --force-with-lease=<branch>:<sha>`
against the upstream's own remote and branch name, so if anybody pushes to that
branch after the check, the delete is rejected instead of destroying their
commit. The `git branch -D` and the push are run by the agent in your session,
so they are visible to you and subject to your own tool permissions.

A skill is instructions, not a sandbox. If you do not want an agent proposing
branch deletions at all, do not install this one.

### Credentials

None of its own.

## Third-party code

None. No packages are installed and no dependencies are pulled at runtime. It is
Python standard library and shells out to `git`.
