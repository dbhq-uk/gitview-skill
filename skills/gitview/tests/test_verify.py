"""`--verify` is the last thing between the agent and a delete, so every gate
the skill promises is enforced here in code rather than left to SKILL.md.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import forge
import gitrepo
import gitview
from fixture import build, colleague_pushes, git


def _verify(capsys, repo, branch, *flags):
    code = gitview.main(["--verify", branch, *flags, repo])
    return code, capsys.readouterr().out


def _delete_commands(out):
    lines = out.splitlines()
    start = lines.index("Every gate passed. Delete with exactly these commands:") + 1
    end = lines.index("To undo:")
    return [line.strip() for line in lines[start:end]]


def _run(command):
    return subprocess.run(["bash", "-c", command], capture_output=True, text=True)


def _remote_sha(repo, branch):
    out = git(repo, "ls-remote", "origin", f"refs/heads/{branch}")
    return out.split()[0] if out else None


def test_a_push_after_the_squash_merge_is_refused(capsys):
    """Somebody pushes a follow-up to a branch that was already squash-merged.

    The local branch still adds nothing and Unpushed reads 0, so a check of the
    local branch alone passes, and deleting the remote would take their commit.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        theirs = colleague_pushes(tmp, "landed-squash")
        git(repo, "fetch", "-q", "origin")
        code, out = _verify(capsys, repo, "landed-squash", "--no-pr")
        assert code == 1
        assert "Refused: the remote branch has commits that have not landed" in out
        assert theirs in out, "the remote SHA must be printed"
        assert "--delete" not in out


def test_the_survey_does_not_call_it_yes_when_the_upstream_has_new_work():
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        colleague_pushes(tmp, "landed-squash")
        git(repo, "fetch", "-q", "origin")
        rows, _ = gitview.survey(repo, want_prs=False)
        row = next(r for r in rows if r.branch == "landed-squash")
        assert row.safe == "no, upstream has unlanded commits"


def test_a_branch_checked_out_in_a_worktree_is_refused(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        path = os.path.join(tmp, "checkout-finished")
        git(repo, "worktree", "add", "-q", path, "trunk-only")
        code, out = _verify(capsys, repo, "trunk-only", "--no-pr")
        assert code == 1
        assert f"Refused: it is checked out in the worktree at {path}" in out


def test_a_branch_with_an_open_pull_request_is_refused(capsys, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "remote", "set-url", "origin", "https://github.com/owner/repo.git")
        monkeypatch.setattr(forge, "list_prs", lambda _kind, _cwd: ({"landed-squash": "12 open"}, None))
        code, out = _verify(capsys, repo, "landed-squash")
        assert code == 1
        assert "Refused: it has an open pull request: 12 open" in out


def test_a_pull_request_lookup_that_cannot_run_is_a_refusal_not_a_pass(capsys, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "remote", "set-url", "origin", "https://github.com/owner/repo.git")
        monkeypatch.setattr(forge, "list_prs", lambda _kind, _cwd: ({}, "gh is not installed"))
        code, out = _verify(capsys, repo, "landed-squash")
        assert code == 1
        assert "could not check for an open pull request: gh is not installed" in out


def test_a_host_gitview_cannot_query_is_a_refusal_not_a_pass(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "remote", "set-url", "origin", "https://git.example.com/owner/repo.git")
        code, out = _verify(capsys, repo, "landed-squash")
        assert code == 1
        assert "could not check for an open pull request: origin is on git.example.com" in out


def test_no_pr_skips_only_the_pull_request_gate(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "remote", "set-url", "origin", "https://git.example.com/owner/repo.git")
        code, _ = _verify(capsys, repo, "landed-squash", "--no-pr")
        assert code == 0
        code, _ = _verify(capsys, repo, "live-work", "--no-pr")
        assert code == 1


def test_a_tag_of_the_same_name_is_not_what_gets_checked(capsys):
    """A bare name resolves refs/tags/ before refs/heads/."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "tag", "no-upstream", "trunk")
        code, out = _verify(capsys, repo, "no-upstream", "--no-pr")
        assert code == 1
        assert "Refused: the branch has work that has not landed" in out


def test_the_printed_commands_delete_the_local_and_the_remote_branch(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        local = gitrepo.local_sha(repo, "landed-squash")
        remote = _remote_sha(repo, "landed-squash")
        code, out = _verify(capsys, repo, "landed-squash", "--no-pr")
        assert code == 0
        assert f"local:  refs/heads/landed-squash at {local}" in out
        assert f"remote: origin refs/heads/landed-squash at {remote}" in out

        commands = _delete_commands(out)
        assert any("--force-with-lease=refs/heads/landed-squash:" + remote in c for c in commands)
        for command in commands:
            ran = _run(command)
            assert ran.returncode == 0, ran.stderr
        assert gitrepo.local_sha(repo, "landed-squash") is None
        assert _remote_sha(repo, "landed-squash") is None


def test_the_lease_saves_a_push_that_lands_after_the_check(capsys):
    """The table and the check are both snapshots. The lease is not."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        code, out = _verify(capsys, repo, "landed-squash", "--no-pr")
        assert code == 0
        theirs = colleague_pushes(tmp, "landed-squash")

        push = next(c for c in _delete_commands(out) if " push " in c)
        ran = _run(push)
        assert ran.returncode != 0, "the leased delete must be rejected"
        assert _remote_sha(repo, "landed-squash") == theirs


def test_the_remote_delete_uses_the_upstream_name_not_the_local_one(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "branch", "short", "landed-squash")
        git(repo, "push", "-q", "-u", "origin", "short:feature/longer-name")
        code, out = _verify(capsys, repo, "short", "--no-pr")
        assert code == 0
        push = next(c for c in _delete_commands(out) if " push " in c)
        assert "--delete refs/heads/feature/longer-name" in push
        assert _run(push).returncode == 0
        assert _remote_sha(repo, "feature/longer-name") is None


def test_a_branch_that_tracks_the_trunk_never_gets_a_remote_delete(capsys):
    """`git switch -c x origin/trunk` makes the trunk the upstream."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        git(repo, "branch", "--track", "tracks-trunk", "origin/trunk")
        code, out = _verify(capsys, repo, "tracks-trunk", "--no-pr")
        assert code == 0
        assert "--delete" not in out
        assert "which gitview never deletes" in out


def test_a_branch_name_with_shell_characters_is_quoted(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        name = "odd;name$x"
        git(repo, "branch", name, "trunk")
        git(repo, "push", "-q", "-u", "origin", name)
        code, out = _verify(capsys, repo, name, "--no-pr")
        assert code == 0
        for command in _delete_commands(out):
            assert _run(command).returncode == 0
        assert gitrepo.local_sha(repo, name) is None
        assert _remote_sha(repo, name) is None
        assert gitrepo.local_sha(repo, "trunk") is not None


def test_a_missing_branch_is_an_error_not_a_refusal(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = build(tmp)
        assert gitview.main(["--verify", "no-such-branch", "--no-pr", repo]) == 2
