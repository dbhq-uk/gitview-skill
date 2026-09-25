<div align="center">

<img src="assets/logo.svg" alt="gitview - which branches are finished and safe to delete, by DBHQ" width="560">

# gitview

**Which branches are finished, and which only look like they are**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude_Code-Plugin-blueviolet)](https://code.claude.com/docs/en/plugins)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20WSL-lightgrey)]()

A free, open-source tool by [DBHQ](https://dbhq.uk) - documented at [skills.dbhq.uk](https://skills.dbhq.uk/gitview/)

</div>

---

## What makes it different

One table: worktree, uncommitted changes, branch, open pull request, ahead,
behind, unpushed, and whether the branch is safe to delete.

The last column is the one that is hard. A branch merged by squash stays ahead of
the trunk forever while contributing nothing, so commit counts cannot answer it
and `git branch --merged` never sees it.

gitview computes the merge of the trunk into
each branch, without touching any checkout, and compares the resulting tree
against the trunk's. If they match, the branch adds nothing and can go.

Both cheap checks fail **silently**, which is the worst failure mode available:
the answer looks right. That is the whole reason this skill exists.

## Install

### As a Claude Code plugin (recommended)

```
/plugin marketplace add dbhq-uk/marketplace
/plugin install gitview@dbhq
```

### Any agent (Cursor, Copilot, Windsurf, Gemini, Cline and more)

```bash
npx skills add dbhq-uk/gitview-skill
```

The [skills.sh](https://skills.sh) CLI installs into whichever agent directories
it finds, so this works outside Claude Code and Codex too.

### Local install (Claude Code or Codex)

```bash
git clone https://github.com/dbhq-uk/gitview-skill.git
cd gitview-skill
./install.sh          # Claude Code: symlinks into ~/.claude/skills (edits are live)
./install-codex.sh    # Codex: installs into ~/.codex/skills
```

[`install.sh`](install.sh) and [`install-codex.sh`](install-codex.sh) are the
same install two ways: Claude Code substitutes `${CLAUDE_SKILL_DIR}`, so the
whole skill directory is symlinked untouched, while Codex does not, so its
`SKILL.md` is rewritten at install time. Re-run the Codex one after editing
`SKILL.md`.

### Requirements

Python 3 and `git`. Optionally `gh` or the Azure CLI, for the pull request
column.


## Requirements

Python 3, standard library only, and `git`. Nothing else: the safe-to-delete
check is answered from the repository in front of it rather than from a
forge API, which is why it works on a private remote you cannot query.

## Use

Talk to your agent: "survey the branches in this repo", "what can I delete",
"which of these are actually finished".

### What it looks like

Real output, from a real run against a repository built to have branches in
each of the states this exists to tell apart. The trunk took two of these
branches by **squash merge**, which is the case the obvious checks get wrong:
both still read as one commit ahead of the trunk, and `git branch --merged`
lists neither.

| Worktree | Dirty | Branch | PR | Ahead | Behind | Unpushed | Safe to delete |
|---|---|---|---|---|---|---|---|
| checkout-service | no | `main` | - | 0 | 0 | 0 | no, trunk |
| - | - | `chore/bump-sdk` | - | 1 | 1 | 0 | **YES**, adds nothing to trunk |
| - | - | `feat/vat-rounding` | - | 1 | 2 | 0 | **YES**, adds nothing to trunk |
| - | - | `fix/expired-card-retry` | - | 1 | 0 | 0 | no, 1 file changed, 1 insertion(+) |
| - | - | `spike/apple-pay` | - | 1 | 0 | no remote | no, 1 file changed, 1 insertion(+) |
| - | - | `wip/rename-basket` | - | 1 | 0 | no remote | no, 1 file changed, 1 insertion(+) |

At risk of being lost: `spike/apple-pay` (no remote holds it), `wip/rename-basket` (no remote holds it).
Trunk is `origin/main`.
To push the work that has not landed, run exactly: `git -C /tmp/gitview-demo/checkout-service push -u origin spike/apple-pay`, `git -C /tmp/gitview-demo/checkout-service push -u origin wip/rename-basket`.
No fetch is recorded in this clone, so the remote-tracking refs may be stale. `git fetch --prune` refreshes them.

Read the last column rather than the counts. `chore/bump-sdk` and
`feat/vat-rounding` are **YES** because merging the trunk into each produces a
tree identical to the trunk's - they add nothing, whatever their ahead count
says.

Every **YES** names the signal that proved it. "adds nothing to trunk" is that
tree check. "landed as abc1234" means a trunk commit carries exactly the
branch's whole diff, which is how a squash merge still shows once the trunk
has edited the same lines and the tree check conflicts. "merged in PR 12" means
a merged pull request's head is this exact commit. None of them ever matches
on a branch name.

The three refusals each name what would be lost: a real
diff against the trunk, and for two of them no remote holding a copy of it.
Those two are the at-risk note under the table: not landed, and nowhere but
here. A landed branch is never at risk, even with no remote, because its
content is already on the trunk.

The push commands cover only work that has not landed. gitview never offers to
push the trunk, a landed branch, or a branch behind its upstream. When the
local trunk has commits its upstream does not, it says so and leaves the call
to you.

Worktrees get the same care. Dirty counts uncommitted changes and untracked
files, and a landed branch whose worktree is dirty, locked or missing is never
**YES**: its commits are on the trunk, but the worktree may hold work that is
not. A detached worktree gets its own row, and is at risk when no branch holds
its commit. A bare repository is surveyed like any other.

It is a markdown table because your agent renders it. The table above is the
output pasted in, not a screenshot of one - so it stays selectable, searchable
and readable by a screen reader.

**Reproduce it rather than trust it.** The repository is built by
[`docs/build-demo-fixture.sh`](docs/build-demo-fixture.sh), which comments each
branch state as it creates it:

```bash
bash docs/build-demo-fixture.sh
python3 skills/gitview/scripts/gitview.py /tmp/gitview-demo/checkout-service
```

It shows the table first, then offers deletions, and asks before each one.
Immediately before each delete it runs `gitview.py --verify BRANCH`, which exits
non-zero, with the reason, for a branch that has a worktree, an open pull
request, or a remote copy somebody pushed to after it merged. It prints the
local and remote SHAs so a wrong call can be undone, and the remote delete is
leased to the SHA it checked, so a push that lands after the check makes the
delete fail rather than destroy that commit.

A finished branch still checked out in a clean worktree is refused until the
worktree goes. `--verify` then prints `git worktree remove` for it, never with
`--force`, and lists any ignored files the removal would take with it, such as
a local `.env`. The agent asks, removes it, and verifies again.

**gitview itself deletes nothing.** `gitview.py` never deletes, pushes, merges or
checks out a branch, and never writes to your working tree, your index or any
ref. The deletions are run by the agent in your session, where you can see them
and your own tool permissions apply.

## How the safe-to-delete check works

Read [`skills/gitview/references/safe-to-delete.md`](skills/gitview/references/safe-to-delete.md)
before changing anything in that logic.

In short: for each branch, gitview runs `git merge-tree --write-tree` to compute
what merging the trunk into it would produce, and compares that tree to the
trunk's. Identical trees mean the branch contributes nothing, whatever its ahead
count says.

`merge-tree` needs git 2.38 or later. It needs no worktree, runs no hooks and
makes no commit. The one thing it writes is the merged trees and blobs, into the
object store, where nothing refers to them and `git gc` removes them in due
course. Your working tree, your index and your refs are never touched.

On older git it falls back to a merge in a temporary worktree outside your
repository, with hooks and signing switched off, and removes only that worktree
afterwards. [SECURITY.md](SECURITY.md) lists exactly what each path writes.

Design: [docs/superpowers/specs/2026-09-10-gitview-design.md](docs/superpowers/specs/2026-09-10-gitview-design.md)

## Also from DBHQ

Every DBHQ agent skill is free, open source and installable from the same
marketplace, and all of them are documented at
**[skills.dbhq.uk](https://skills.dbhq.uk)**. The marketplace itself is
[dbhq-uk/marketplace](https://github.com/dbhq-uk/marketplace) - one
`/plugin marketplace add` and every one of them is available.

| Skill | What it does |
|---|---|
| [outlook](https://skills.dbhq.uk/outlook/) | Microsoft 365 mail and calendar, from the terminal |
| [trello](https://skills.dbhq.uk/trello/) | Your boards, run from your agent |
| [legwork](https://skills.dbhq.uk/legwork/) | Research that settles a decision, and says when it cannot |
| [dovetail](https://skills.dbhq.uk/dovetail/) | Checks whether your repository still agrees with itself |
| [verve](https://skills.dbhq.uk/verve/) | Strips AI tells from prose and puts a voice back |
| [vela](https://skills.dbhq.uk/vela/) | Compiler-exact code search, in any language you index |
| [garmin](https://skills.dbhq.uk/garmin/) | Your Garmin data, answered in the terminal |
| [imager](https://skills.dbhq.uk/imager/) | Images from GPT Image 2, costed before it spends |
| [atlassian](https://skills.dbhq.uk/atlassian/) | Jira issues and Confluence pages |
| [pennyblack](https://skills.dbhq.uk/pennyblack/) | A physical letter, posted from the terminal |
| [buildwork](https://skills.dbhq.uk/buildwork/) | Your open issues, run as parallel agents |
| [deskwork](https://skills.dbhq.uk/deskwork/) | What an agent noticed, tracked as real work |
| [groupwork](https://skills.dbhq.uk/groupwork/) | A second agent on the work, adversary or partner |
| [headwork](https://skills.dbhq.uk/headwork/) | One decision at a time, with a recommendation |

Plus [heliograph](https://skills.dbhq.uk/heliograph/), for a machine you cannot log into.

## Licence

MIT. See [LICENSE](LICENSE).
