---
name: gitview
description: Survey every branch and worktree in a git repository - what is in flight, what is unpushed, and which branches are finished and safe to delete - then optionally clear them away. Trigger on phrases like "gitview", "where are we at with branches", "what branches can I delete", "branch status", "worktree status", "any old branches to tidy up", "what is safe to delete", "show me the branches", "which worktree is on what branch".
---

# gitview - the state of every branch and worktree

One table: worktree, branch, open pull request, ahead, behind, unpushed, and whether the branch is finished.

## Run it

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/gitview.py" [PATH]
```

`PATH` defaults to the current directory. Add `--no-pr` to skip the pull request lookup, which makes it work offline.

Print the table as it comes. Do not re-sort it, re-format it, or drop rows to make it shorter.

**It never fetches.** Unpushed and `gone` are only as fresh as the remote-tracking refs, and a note under the table says when this clone last fetched. If that is not recent, or no fetch is recorded, offer `git fetch --prune` and survey again before anyone relies on Unpushed or deletes anything.

## How to read it

**Safe to delete is the column that answers the question.** `YES` means the branch adds nothing to the trunk, and what follows it names the proof:

- `YES, adds nothing to trunk`: merging the trunk into the branch gives the trunk's tree. Computed with `git merge-tree`, which touches no checkout.
- `YES, landed as abc1234`: that trunk commit carries exactly the branch's whole diff. This is a squash merge the trunk has since edited, where the tree check conflicts.
- `YES, merged in PR 12`: a merged pull request's head is this exact commit. Matched on the SHA, never on the branch name.

**Ahead is a commit count, not a measure of unlanded work.** A branch merged by squash stays ahead of the trunk forever while contributing nothing. Never tell someone a branch has unlanded work because its ahead number is large. [references/safe-to-delete.md](references/safe-to-delete.md) explains why, and why the two obvious cheaper checks are both wrong.

**Unpushed says how much of the branch exists only in this clone.**

- A number counts commits not yet on its upstream.
- `gone` means its upstream was deleted on the remote.
- `on origin/x` means no upstream is set, but that remote-tracking ref already holds the tip.
- `no remote` means no remote holds the tip at all.
- `?` means git could not count. Treat it as unpushed.

**A branch is at risk only when it is not landed** (Safe to delete is not `YES`) **and** its Unpushed is `gone`, `no remote`, or above 0. A landed branch is never at risk, whatever its Unpushed says: everything in it is already on the trunk. The survey lists the at-risk branches in the first note under the table.

**The worktree column is a directory basename, not a branch name.** When the two disagree, say so. A directory named after a branch deleted weeks ago misleads whoever opens it next.

## What to say

Lead with the `At risk of being lost` note when there is one, then what is finished, then what is in flight. If the notes mention stash entries, say so: they are local-only work too, and the table does not show them.

Keep it short. The table is the answer; do not narrate every row back.

## Offering the actions

Only after the table has been shown, and only when there is something to offer. Ask before doing any of it.

### Deleting the finished branches

Offer local and remote together, because deleting only the local one leaves the remote to be rediscovered and puzzled over later.

Before each delete:

1. **Re-verify it.** A table is a snapshot, and a repository worked by several sessions moves underneath it.

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/gitview.py" --verify BRANCH [PATH]
   ```

   It exits 0 only when every gate passes: the branch is not the trunk, it adds nothing to the trunk, its upstream adds nothing either, no worktree has it checked out, and it has no open pull request.

   Anything else means do not delete it. Say which gate refused it, out loud rather than skipping it silently.

2. **Show the SHAs and the undo commands it printed**, local and remote, so the branch can be restored if the call was wrong.
3. **Run the delete commands it printed, exactly as printed.** They have this shape:

   ```bash
   git -C PATH branch -D BRANCH
   git -C PATH push --force-with-lease=REMOTE_BRANCH:REMOTE_SHA REMOTE --delete REMOTE_BRANCH
   ```

   The remote and its branch name come from the branch's upstream, not from `origin` and the local name. The lease makes the push fail if anybody pushed to the remote branch after the check. If it fails, stop and survey again. Never retry it without the lease.

If the pull request lookup could not run, `--verify` refuses rather than passes. Tell the user why, and re-run it with `--no-pr` only after they confirm there is no open pull request.

### Pushing unpushed work

Offer it whenever any branch has unpushed commits or no upstream at all.

```bash
git -C WORKTREE push                      # has an upstream
git -C WORKTREE push -u origin BRANCH     # no upstream yet
```

### What it never does

No merging, no completing pull requests, no rebasing, no resolving conflicts, no checking out an existing branch. Those are decisions, not housekeeping.

## Requirements

- `git`. On 2.38 or later the check uses `git merge-tree` and takes milliseconds per branch. Older git uses a slower fallback in a temporary worktree.
- `az` for Azure DevOps pull requests, or `gh` for GitHub. Neither is required. Without them the pull request column shows dashes and the reason is printed once under the table.

The script never changes a branch, a ref, the index or a working tree. On git 2.38 or later the only thing it writes is merge objects into the object store. On older git it also makes a temporary worktree, with hooks off, and removes it.
