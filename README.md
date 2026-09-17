<div align="center">

<img src="assets/logo.svg" alt="gitview - which branches are finished and safe to delete, by DBHQ" width="420">

# gitview

**Which branches are finished, and which only look like they are**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude_Code-Plugin-blueviolet)](https://code.claude.com/docs/en/plugins)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20WSL-lightgrey)]()

A free, open-source tool by [DBHQ](https://dbhq.uk)

</div>

---

One table: worktree, branch, open pull request, ahead, behind, unpushed, and
whether the branch is safe to delete.

The last column is the one that is hard. A branch merged by squash stays ahead of
the trunk forever while contributing nothing, so commit counts cannot answer it
and `git branch --merged` never sees it. gitview merges the trunk into a
throwaway copy of each branch and compares the resulting tree against the
trunk's. If they match, the branch adds nothing and can go.

Both cheap checks fail **silently**, which is the worst failure mode available:
the answer looks right. That is the whole reason this skill exists.

## Install

### Any agent (Claude Code, Codex, Cursor, Copilot, Windsurf, Gemini, Cline and more)

```bash
npx skills add dbhq-uk/gitview-skill
```

The [skills.sh](https://skills.sh) CLI installs into whichever agent directories
it finds.

### Claude Code plugin

```bash
/plugin marketplace add dbhq-uk/marketplace
/plugin install gitview@dbhq
```

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

## Use

Talk to your agent: "survey the branches in this repo", "what can I delete",
"which of these are actually finished".

It shows the table first, then offers deletions, and asks before each one. It
will not delete a branch that has a worktree or an open pull request, it
re-verifies each branch immediately before it goes, and it prints the commit SHA
so a wrong call can be undone.

**gitview itself deletes nothing.** `gitview.py` is read only - it never deletes,
pushes, merges, or checks out an existing branch. The deletions are run by the
agent in your session, where you can see them and your own tool permissions
apply.

## How the safe-to-delete check works

Read [`skills/gitview/references/safe-to-delete.md`](skills/gitview/references/safe-to-delete.md)
before changing anything in that logic.

In short: for each branch, gitview creates a throwaway git index and a detached
worktree outside your repository, merges the trunk into a copy of the branch, and
compares the resulting tree to the trunk's. Identical trees mean the branch
contributes nothing, whatever its ahead count says. Both temporary artefacts are
removed when the check finishes; your working tree and your index are never
touched.

Design: [docs/superpowers/specs/2026-09-10-gitview-design.md](docs/superpowers/specs/2026-09-10-gitview-design.md)

## Also from DBHQ

[jira](https://github.com/dbhq-uk/jira-skill) - create and read Jira Cloud issues
over the REST API. The two shipped together as `devskills` until 17 September
2026; they were split because they share no API, no credential and no subject.

The rest of the skills are at [dbhq.uk/skills](https://dbhq.uk/skills/).

## Licence

MIT. See [LICENSE](LICENSE).
