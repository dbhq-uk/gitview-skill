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
