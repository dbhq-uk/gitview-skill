# AGENTS.md

Guidance for AI agents (and people) working in this repository.

## What this is

**gitview** - an agent skill that surveys every branch and worktree in a
repository and says which branches are finished. It follows the
[Agent Skills](https://agentskills.io) layout (`skills/<name>/SKILL.md`) and
ships as a [Claude Code plugin](https://code.claude.com/docs/en/plugins).

## Layout

```
.claude-plugin/plugin.json        # plugin manifest
skills/gitview/SKILL.md           # the skill (agent-facing instructions)
skills/gitview/references/        # safe-to-delete: why the cheap checks are wrong
skills/gitview/scripts/           # Python, standard library only, shells out to git
skills/gitview/tests/             # pytest, with a fixture that builds real repositories
install.sh / install-codex.sh     # local symlink installers (Claude / Codex)
docs/superpowers/                 # the dated design and plan records
```

## The constraints that must not be broken

Everything else here is a preference. These are not.

**1. `gitview.py` is read only.** It never deletes, pushes, merges or checks out
an existing branch. Its docstring says so and that is a promise to the reader,
not a description of the current state. The test merge happens in a temporary
index and a detached temporary worktree, both outside the repository, both
cleaned up. If you need a write operation, it belongs in the agent's hands in the
user's session, not in the script.

**2. A destructive suggestion must be gated, and the gate is re-verified.** The
skill's most useful output is also its most dangerous: a list of branches
somebody is about to delete. So `SKILL.md` requires the table first, then the
offer, then a fresh `gitview.py --verify BRANCH` on each branch immediately
before it goes. `--verify` enforces every gate in code, not in prose: the trunk,
unlanded work on the branch or on its upstream, a worktree, and an open pull
request all refuse, and a pull request lookup that cannot run refuses too. It
prints the SHAs so a wrong call is recoverable, and the remote delete it prints
is leased to the upstream SHA it checked. A table is a snapshot and a repository
worked by several sessions moves underneath it. Do not weaken this into "the
table already said it was safe", and do not drop the lease.

**3. Safe to delete is computed, never inferred.** Read
[`skills/gitview/references/safe-to-delete.md`](skills/gitview/references/safe-to-delete.md)
before touching that logic. A branch merged by squash stays ahead of the trunk
forever while contributing nothing, so a commit count cannot answer the question
and `git branch --merged` never sees it. Both cheap checks fail silently, which
is the worst failure mode available: the answer looks right. Never tell somebody
a branch has unlanded work because its ahead number is large.

**4. No packages, no venv.** Python standard library plus `git`. Nothing is
installed at runtime, which is why there is nothing to keep patched.

## Conventions

- Any path `SKILL.md` names goes through `${CLAUDE_SKILL_DIR}`, which Claude Code
  substitutes for personal, project and plugin installs alike. **The braces are
  required**: Claude Code leaves the unbraced `$CLAUDE_SKILL_DIR` for the shell,
  where it is not set, and CI fails on it. **Never hardcode
  `~/.claude/skills/gitview` or any absolute path** - it is wrong under a Codex
  install and wrong under a plugin install. `install-codex.sh` rewrites the
  variable at install time because Codex does not substitute it.
- `SKILL.md` is the short half on purpose. The workflow, the constraints and the
  checks live there; the reasoning and the reference material live in
  `references/` and are read on demand.
- Shell scripts use `set -e`; errors go to stderr, output to stdout.
- Every example is generic: `owner/repo`, `feature/thing`. CI greps for anything
  that looks like a real ticket id, hostname, IP address or organisation.
- House style: British English, plain hyphens, **no em dashes** - CI fails on
  them. No trailing full stops on headings.

## Validating a change

```bash
bash -n install.sh install-codex.sh
jq empty .claude-plugin/plugin.json
python3 -m pytest skills/gitview/tests -q
```

CI runs those, the two prose checks, and a check that `SKILL.md` uses the
braced `${CLAUDE_SKILL_DIR}`. The tests are worth more than they look:
the fixture builds real git repositories, including the squash-merged-then-trunk-moved
case that defeats both naive checks, so a change that breaks the finished-branch
logic fails rather than quietly returning the wrong verdict.

## History

This repository was `devskills` until 17 September 2026, a pack of two skills.
It was split because its two skills shared no API, no credential and no subject -
this file used to say they had "nothing in common beyond being things a developer
needs mid-task", which is an argument for two repositories rather than one. The
other half is [jira](https://github.com/dbhq-uk/jira-skill). GitHub redirects the
old `dbhq-uk/devskills` URL here; the plugin is now `gitview@dbhq` rather than
`devskills@dbhq`.
