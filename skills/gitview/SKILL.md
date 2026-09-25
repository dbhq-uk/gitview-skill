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

## How to read it

**Safe to delete is the column that answers the question.** It is computed by merging the trunk into a throwaway copy of the branch and comparing trees. `YES` means the branch adds nothing to the trunk.

**Ahead is a commit count, not a measure of unlanded work.** A branch merged by squash stays ahead of the trunk forever while contributing nothing. Never tell someone a branch has unlanded work because its ahead number is large. [references/safe-to-delete.md](references/safe-to-delete.md) explains why, and why the two obvious cheaper checks are both wrong.

**Unpushed reading `no remote` is the urgent one.** That work exists on one machine and nothing is backing it up.

**The worktree column is a directory basename, not a branch name.** When the two disagree, say so. A directory named after a branch deleted weeks ago misleads whoever opens it next.

## What to say

Lead with whatever is at risk of being lost, then what is finished, then what is in flight. Unpushed commits and branches with no remote come first, always.

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

   Exit code 0 means finished. Anything else means do not delete it, and say why.

2. **Print the commit SHA first**, so the branch can be restored if the call was wrong.
3. **Refuse any branch that has a worktree or an open pull request**, and say so out loud rather than skipping it silently.

```bash
git rev-parse BRANCH                      # record this first
git branch -D BRANCH
git push origin --delete BRANCH
```

### Pushing unpushed work

Offer it whenever any branch has unpushed commits or no upstream at all.

```bash
git -C WORKTREE push                      # has an upstream
git -C WORKTREE push -u origin BRANCH     # no upstream yet
```

### What it never does

No merging, no completing pull requests, no rebasing, no resolving conflicts, no checking out an existing branch. Those are decisions, not housekeeping.

## Requirements

- `git`.
- `az` for Azure DevOps pull requests, or `gh` for GitHub. Neither is required. Without them the pull request column shows dashes and the reason is printed once under the table.

The script is read only. It never writes to the repository it surveys.
