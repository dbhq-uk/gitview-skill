import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import forge


def test_detects_azure_devops_from_either_host():
    assert forge.detect("git@ssh.dev.azure.com:v3/org/proj/repo") == "azure"
    assert forge.detect("https://org.visualstudio.com/proj/_git/repo") == "azure"


def test_detects_github():
    assert forge.detect("git@github.com:owner/repo.git") == "github"
    assert forge.detect("https://github.com/owner/repo.git") == "github"


def test_an_unknown_host_is_not_guessed():
    assert forge.detect("https://git.example.com/owner/repo.git") is None
    assert forge.detect(None) is None


def test_a_missing_cli_skips_the_lookup_instead_of_failing(monkeypatch):
    monkeypatch.setattr(forge.shutil, "which", lambda _: None)
    prs, reason = forge.list_prs("github", ".")
    assert prs == {}
    assert "not installed" in reason


def test_no_forge_means_no_lookup_and_no_complaint():
    assert forge.list_prs(None, ".") == ({}, None)


def test_azure_output_is_parsed_into_branch_labels():
    raw = '[{"pullRequestId": 7, "sourceRefName": "refs/heads/feature/x", "mergeStatus": "succeeded"}]'
    assert forge.parse_azure(raw) == {"feature/x": "7 succeeded"}


def test_github_output_is_parsed_into_branch_labels():
    raw = '[{"number": 12, "headRefName": "fix/y", "mergeable": "CONFLICTING"}]'
    assert forge.parse_github(raw) == {"fix/y": "12 conflicts"}


def test_unreadable_output_degrades_to_a_reason_rather_than_an_exception(monkeypatch):
    class Result:
        returncode = 0
        stdout = "not json at all"
        stderr = ""

    monkeypatch.setattr(forge.shutil, "which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr(forge, "_run", lambda _cmd, _cwd: Result())
    prs, reason = forge.list_prs("github", ".")
    assert prs == {}
    assert "could not read" in reason


def test_a_failing_cli_reports_its_first_line_of_stderr(monkeypatch):
    class Result:
        returncode = 1
        stdout = ""
        stderr = "gh: not logged in\nrun gh auth login"

    monkeypatch.setattr(forge.shutil, "which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr(forge, "_run", lambda _cmd, _cwd: Result())
    prs, reason = forge.list_prs("github", ".")
    assert prs == {}
    assert "not logged in" in reason


def test_a_remote_on_this_machine_is_local_and_a_hosted_one_is_not():
    assert forge.is_local("/srv/git/repo.git")
    assert forge.is_local("../repo")
    assert forge.is_local("file:///srv/git/repo.git")
    assert not forge.is_local("git@github.com:owner/repo.git")
    assert not forge.is_local("https://git.example.com/owner/repo.git")
    assert not forge.is_local("ssh://git@git.example.com/owner/repo.git")


def test_merged_pull_requests_are_keyed_by_head_sha_not_name():
    raw = '[{"number": 12, "headRefName": "fix/y", "headRefOid": "abc123"}]'
    assert forge.parse_merged_github(raw) == {"abc123": "12"}
    raw = '[{"pullRequestId": 7, "head": "def456"}]'
    assert forge.parse_merged_azure(raw) == {"def456": "7"}


def test_the_merged_lookup_is_made_once_and_only_when_asked(monkeypatch):
    calls = []

    def lookup(kind, cwd):
        calls.append(kind)
        return {"abc123": "12"}, None

    monkeypatch.setattr(forge, "list_merged", lookup)
    heads = forge.MergedHeads("github", ".")
    assert calls == []
    assert heads.number("abc123") == "12"
    assert heads.number("other") is None
    assert calls == ["github"]


def test_a_pull_request_from_a_fork_is_skipped():
    """A fork's `main` must not label the trunk row, or block a local delete."""
    raw = (
        '[{"number": 3, "headRefName": "main", "mergeable": "MERGEABLE", "isCrossRepository": true},'
        ' {"number": 4, "headRefName": "fix/y", "mergeable": "MERGEABLE", "isCrossRepository": false}]'
    )
    assert forge.parse_github(raw) == {"fix/y": "4 mergeable"}


def test_the_github_lookup_asks_whether_a_pull_request_is_from_a_fork():
    fields = forge._COMMANDS["github"][forge._COMMANDS["github"].index("--json") + 1]
    assert "isCrossRepository" in fields.split(",")


def test_a_mergeable_github_pull_request_says_mergeable():
    """`succeeded` is Azure's word. GitHub says the pull request can merge."""
    raw = '[{"number": 12, "headRefName": "fix/y", "mergeable": "MERGEABLE"}]'
    assert forge.parse_github(raw) == {"fix/y": "12 mergeable"}


def test_the_host_is_read_from_every_url_form():
    assert forge.host("https://gitlab.example/owner/repo.git") == "gitlab.example"
    assert forge.host("ssh://git@git.example.com:2222/owner/repo.git") == "git.example.com:2222"
    assert forge.host("git@github-work:owner/repo.git") == "github-work"


def test_an_unrecognised_host_is_named_not_skipped_silently():
    note = forge.unrecognised("git@github-work:owner/repo.git")
    assert note.startswith("origin is on github-work, which gitview cannot query.")
    assert forge.unrecognised("https://github.com/owner/repo.git") is None
    assert forge.unrecognised("/srv/git/repo.git") is None
    assert forge.unrecognised(None) is None
