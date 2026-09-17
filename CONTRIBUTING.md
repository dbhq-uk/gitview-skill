# Contributing

Thanks for your interest - contributions are welcome.

## Ways to help

- Report a bug or request a feature via [issues](https://github.com/dbhq-uk/gitview-skill/issues)
- Sharpen the skill's instructions, add a forge to the pull request lookup, or improve an error message via a pull request

## Local development

```bash
git clone https://github.com/dbhq-uk/gitview-skill.git
cd gitview-skill
./install.sh          # symlinks the skill into ~/.claude/skills (edits are live)
./install-codex.sh    # the same for ~/.codex/skills
```

`install.sh` symlinks the whole skill directory, so edits - including to
`SKILL.md` and `references/` - are live immediately. For Codex, re-run
`./install-codex.sh` after editing a `SKILL.md`, since that file is rewritten at
install time rather than symlinked.

## Before opening a PR

```bash
bash -n install.sh install-codex.sh                 # the installers parse
jq empty .claude-plugin/plugin.json                 # the manifest is valid JSON
python3 -m pytest skills/gitview/tests -q           # the tests pass
```

CI runs those, plus two checks on the prose: no em dashes, and nothing that
looks client-specific. British English, plain hyphens, no trailing full stops on
headings.

## What we will not accept

**A claim about a branch being safe to delete that is not computed.** This is
the one that matters, and [`skills/gitview/references/safe-to-delete.md`](skills/gitview/references/safe-to-delete.md)
is the document to read before touching it. Both cheap ways to decide whether a
branch is finished are wrong wherever a repository squashes on merge, and both
fail **silently**: a commit count cannot answer it, and `git branch --merged`
never sees it. gitview test-merges the trunk into a throwaway copy and compares
trees because nothing cheaper is correct. A pull request that swaps that for a
faster check will be declined unless it comes with a repository where the faster
check demonstrably agrees.

**A real ticket id, hostname, IP address or organisation.** CI greps for them.
Every example in the docs is generic (`owner/repo`, `feature/thing`) and should
stay that way.

**A destructive operation inside a script.** `gitview.py` is read only and says
so in its own docstring. Deletions are offered by the agent, gated on
`--verify`, and run in the user's session where they can see them. Moving a
`git branch -D` into the script would take that away.

**Anything that needs a package.** gitview is Python standard library and shells
out to `git`. There is no `requirements.txt` and no venv, which is why there is
nothing to keep patched.

## Code of conduct

By taking part you agree to the [code of conduct](CODE_OF_CONDUCT.md).

## Licence

By contributing you agree your work is licensed under the [MIT licence](LICENSE).
