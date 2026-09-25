# Why "is this branch finished?" is harder than it looks

A branch is finished when merging the trunk into it produces the trunk's tree exactly. Then it contributes nothing, whatever its commit count says.

Two cheaper tests look right and are wrong. Both fail silently, which is what makes them dangerous. They do not error. They quietly report finished work as live, and a branch nobody dares delete sits there for weeks.

## `git branch --merged` misses every squash merge

Where a repository squashes on merge, the branch's commits never become ancestors of the trunk. A branch whose every line landed weeks ago still never appears as merged.

In a repository whose branch policy permits nothing but squash, and many do, this test is not merely unreliable. It is always wrong.

## Reverse-applying the branch's patch gives false negatives

Take the branch's diff against its merge base and try to apply it backwards to the trunk. If it applies cleanly the content must already be there.

The reasoning is sound and the test still fails, because applying a patch depends on context lines. The moment the trunk edits the same files after the branch landed, the surrounding lines no longer match and the patch will not reverse. The content is present. The check says it is missing.

This is not hypothetical. It is what sent one survey badly wrong: two branches were reported as thousands of insertions of live work when both had in fact landed days earlier. The error only surfaced because merging the trunk into one of them turned out to produce no change at all.

`tests/test_landed.py` asserts both failures against the fixture, so the suite proves the naive checks are wrong rather than assuming it.

## The test that works

Merge the trunk into the branch, and compare the resulting tree with the trunk's tree. Equal means the branch adds nothing.

### On git 2.38 or later: `git merge-tree --write-tree`

`git merge-tree --write-tree <branch> <trunk>` performs the full merge in memory and prints the resulting tree. Exit 1 means conflicts, and lists the conflicted paths. Otherwise the printed tree is compared with the trunk's.

It needs no worktree and no index, runs no hooks, makes no commit, and reads none of the user's commit, signing or fast-forward settings. The only thing it writes is the merged trees and blobs, into the object store, unreferenced. It takes milliseconds per branch.

That matters more than speed. A real `git merge` runs the repository's hooks, fails under a failing `commit.gpgsign`, `merge.ff=only` or no committer identity, and in any of those cases leaves a finished branch looking unlanded. `tests/test_isolation.py` asserts each of those against both paths.

### On older git: a guarded fallback

Git before 2.38 has no `merge-tree --write-tree`, so the check falls back to two tiers.

**Tier one: a trivial merge into a temporary index.** `git read-tree -m --aggressive <merge-base> <branch> <trunk>` against a temporary `GIT_INDEX_FILE`, then compare `git write-tree` with the trunk's tree. No checkout, no worktree, milliseconds.

It is definitive only when it says yes. If every path resolved to the trunk's version then for every path the branch either never touched it or agrees with it, which is exactly what contributing nothing means.

A no answer proves nothing. `read-tree` performs a trivial merge and refuses any file both sides edited, even where a real merge would combine two non-overlapping changes cleanly. Treating its no as an answer would report finished branches as conflicted.

**Tier two: a real merge in a throwaway worktree.** Run only for branches tier one could not prove finished. The worktree is created detached under a temporary directory, the merge is `--no-commit --no-ff`, and the tree is read from the index, so no commit, signature or identity is needed. Hooks are off (`core.hooksPath=/dev/null`), as are signature checks and rerere.

The worktree is removed in a `finally` block, including when the merge raises, and only that worktree is removed. Never `git worktree prune`: it acts on every worktree in the repository, and a worktree whose directory is briefly absent loses its registration, after which `git branch -D` will delete a branch still checked out there.

## What the columns cannot tell you

**Ahead is a commit count against the trunk.** A branch merged by squash stays ahead forever. Reading a large ahead number as "unlanded work" is the same mistake in a different form, and the table deliberately puts the safe-to-delete column last so it reads as the conclusion rather than as one number among several.

**Behind says nothing about whether a branch is finished.** A branch can be behind by fifty commits and still contribute nothing.
