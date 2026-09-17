# Security

## Reporting a vulnerability

Email <dan@dbhq.uk> rather than opening a public issue. Include what you found,
how to reproduce it, and what an attacker could do with it. You will get a first
response within 48 hours.

## What this skill does

### Network

**Only the pull request lookup, and only through a tool you already trust.**
gitview shells out to `gh pr list` on GitHub and `az repos pr list` on Azure
DevOps, using whatever credential those CLIs already hold. It never handles a
token itself and never makes an HTTP request of its own. `--no-pr` skips the
lookup entirely and the skill then works offline.

### On disk

`scripts/gitview.py` is read only. It never deletes, pushes, merges, or checks
out an existing branch, and it never writes to your working tree or your index.

Two things it does create, both temporary and both outside the repository:

- A throwaway git index under `tempfile.mkstemp`, so the real one is untouched
- A detached worktree under `tempfile.mkdtemp`, used to test-merge the trunk into
  a copy of each branch and compare the resulting trees. It is removed with
  `git worktree remove --force` when the check finishes

That test merge is the whole reason the "safe to delete" column can be trusted
where a repository squashes on merge, and it is why the work happens in a copy
rather than in your checkout.

### The deletions

**gitview does not delete anything. The agent does, and only after you agree.**
This is the part worth reading twice, because the skill's job is to make a
destructive suggestion.

`SKILL.md` instructs the agent to offer deletions only after showing the table,
to ask first, and before each delete to re-verify the branch with
`gitview.py --verify BRANCH` (exit code 0 means finished, anything else means
stop), to print the commit SHA so a wrong call can be undone, and to refuse any
branch that has a worktree or an open pull request. The `git branch -D` and
`git push origin --delete` are run by the agent in your session, so they are
visible to you and subject to your own tool permissions.

A skill is instructions, not a sandbox. If you do not want an agent proposing
branch deletions at all, do not install this one.

### Credentials

None of its own.

## Third-party code

None. No packages are installed and no dependencies are pulled at runtime. It is
Python standard library and shells out to `git`.
