"""Finds open pull requests, when the host is one we understand.

This column always degrades rather than fails. A status table that refuses to
render because a remote API was unreachable is useless exactly when it is most
wanted, which is usually when something is already wrong.
"""
import json
import shutil
import subprocess

_TIMEOUT = 30

_AZURE_QUERY = "[].{pullRequestId:pullRequestId,sourceRefName:sourceRefName,mergeStatus:mergeStatus}"

_COMMANDS = {
    "azure": ["az", "repos", "pr", "list", "--status", "active", "--query", _AZURE_QUERY, "-o", "json"],
    "github": ["gh", "pr", "list", "--state", "open", "--limit", "200",
               "--json", "number,headRefName,mergeable,isCrossRepository"],
}

_TOOLS = {"azure": "az", "github": "gh"}

# Merged pull requests, keyed by the exact commit that was their head.
_MERGED_AZURE_QUERY = "[].{pullRequestId:pullRequestId,head:lastMergeSourceCommit.commitId}"

_MERGED_COMMANDS = {
    "azure": ["az", "repos", "pr", "list", "--status", "completed", "--top", "200",
              "--query", _MERGED_AZURE_QUERY, "-o", "json"],
    "github": ["gh", "pr", "list", "--state", "merged", "--limit", "200",
               "--json", "number,headRefOid"],
}


def detect(url):
    """Which forge, from the origin URL. None means do not guess."""
    if not url:
        return None
    lowered = url.lower()
    if "dev.azure.com" in lowered or "visualstudio.com" in lowered:
        return "azure"
    if "github.com" in lowered:
        return "github"
    return None


def host(url):
    """The host a remote URL names, so a host gitview cannot query can be named.

    Handles `scheme://user@host:port/path` and the scp-like `user@host:path`.
    An SSH host alias comes back as the alias, which is what the user wrote.
    """
    if "://" in url:
        authority = url.split("://", 1)[1].split("/", 1)[0]
    else:
        authority = url.split(":", 1)[0]
    return authority.rsplit("@", 1)[-1]


def unrecognised(url):
    """A note for a hosted remote gitview has no pull request lookup for, or None.

    None for no remote, one on this machine, and a host it knows. Otherwise the
    lookup is skipped, and saying so is the difference between "no pull
    requests" and "could not look".
    """
    if not url or detect(url) or is_local(url):
        return None
    return (
        f"origin is on {host(url)}, which gitview cannot query. "
        "It looks up pull requests on github.com and Azure DevOps only"
    )


def is_local(url):
    """A remote on this machine, a path or a file:// URL. It has no pull requests."""
    if url.startswith("file://"):
        return True
    if "://" in url:
        return False
    # scp-like syntax, user@host:path, has a colon before the first slash.
    return ":" not in url.split("/", 1)[0]


def parse_azure(raw):
    found = {}
    for item in json.loads(raw or "[]"):
        branch = (item.get("sourceRefName") or "").replace("refs/heads/", "")
        if branch:
            found[branch] = f"{item.get('pullRequestId')} {item.get('mergeStatus') or ''}".strip()
    return found


def parse_github(raw):
    """Open pull requests from this repository's own branches, by branch name.

    A pull request from a fork is skipped. Its head is a branch in somebody
    else's repository, and a fork's `main` would otherwise label the trunk row
    here, and block deleting a local branch that only shares its name.
    """
    found = {}
    for item in json.loads(raw or "[]"):
        branch = item.get("headRefName")
        if not branch or item.get("isCrossRepository"):
            continue
        state = {"CONFLICTING": "conflicts", "MERGEABLE": "mergeable"}.get(
            item.get("mergeable") or "", "open"
        )
        found[branch] = f"{item.get('number')} {state}"
    return found


def parse_merged_azure(raw):
    return {
        item["head"]: str(item.get("pullRequestId"))
        for item in json.loads(raw or "[]")
        if item.get("head")
    }


def parse_merged_github(raw):
    return {
        item["headRefOid"]: str(item.get("number"))
        for item in json.loads(raw or "[]")
        if item.get("headRefOid")
    }


_PARSERS = {"azure": parse_azure, "github": parse_github}
_MERGED_PARSERS = {"azure": parse_merged_azure, "github": parse_merged_github}


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=_TIMEOUT)


def _lookup(kind, cwd, commands, parsers):
    if kind is None:
        return {}, None
    tool = _TOOLS[kind]
    if shutil.which(tool) is None:
        return {}, f"{tool} is not installed"
    try:
        result = _run(commands[kind], cwd)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {}, f"{tool} lookup failed: {exc}"
    if result.returncode != 0:
        first = (result.stderr or "").strip().split("\n")[0][:120]
        return {}, f"{tool} lookup failed: {first or 'non-zero exit'}"
    try:
        return parsers[kind](result.stdout), None
    except (ValueError, KeyError, TypeError) as exc:
        return {}, f"{tool} returned output we could not read: {exc}"


def list_prs(kind, cwd):
    """Return (branch name -> label, reason skipped).

    One call lists every open pull request and branches are matched against it
    in memory. Never one call per branch.
    """
    return _lookup(kind, cwd, _COMMANDS, _PARSERS)


def list_merged(kind, cwd):
    """Return (head commit SHA -> pull request number, reason skipped).

    Keyed by SHA, never by branch name. A name is reused: one branch can have
    several merged pull requests and new work nobody has merged, and matching
    on the name would call that new work landed.
    """
    return _lookup(kind, cwd, _MERGED_COMMANDS, _MERGED_PARSERS)


class MergedHeads:
    """The merged pull request lookup, made once and only if something needs it."""

    def __init__(self, kind, cwd):
        self._kind, self._cwd = kind, cwd
        self._heads, self.reason = None, None

    def number(self, sha):
        if self._heads is None:
            self._heads, self.reason = list_merged(self._kind, self._cwd)
        return self._heads.get(sha) if sha else None
