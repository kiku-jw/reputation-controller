"""GitHub CLI adapter for the controller."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from .config import Secrets


CommandRunner = Callable[[list[str], dict[str, str]], str]
DEFAULT_GH_TIMEOUT_SECONDS = 60.0


@dataclass
class Issue:
    repo: str
    number: int
    title: str
    url: str
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    updated_at: str = ""
    state: str = "open"


@dataclass
class CheckRun:
    name: str
    state: str
    link: str = ""


@dataclass
class IssueComment:
    author: str
    body: str
    url: str = ""


@dataclass
class PullRequest:
    number: int
    title: str
    url: str
    author: str = ""


class GitHubClient:
    def __init__(
        self,
        *,
        secrets: Secrets,
        timeout_seconds: float = DEFAULT_GH_TIMEOUT_SECONDS,
        command_runner: CommandRunner | None = None,
    ):
        self.secrets = secrets
        self.timeout_seconds = timeout_seconds
        self.command_runner = command_runner or run_command

    def list_open_issues(self, repo_name: str, *, limit: int = 30) -> list[Issue]:
        command = [
            "gh",
            "issue",
            "list",
            "--repo",
            repo_name,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,url,labels,assignees,updatedAt",
        ]
        raw = self.command_runner(command, self._env())
        return [_issue_from_gh(repo_name, item) for item in json.loads(raw)]

    def issue(self, repo_name: str, issue_number: int) -> Issue:
        command = [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repo_name,
            "--json",
            "number,title,url,labels,assignees,updatedAt,state",
        ]
        raw = self.command_runner(command, self._env())
        return _issue_from_gh(repo_name, json.loads(raw))

    def pr_checks(self, repo_name: str, pr_number: int) -> list[CheckRun]:
        command = [
            "gh",
            "pr",
            "checks",
            str(pr_number),
            "--repo",
            repo_name,
            "--json",
            "name,state,link",
        ]
        raw = self.command_runner(command, self._env())
        return [
            CheckRun(
                name=item.get("name", ""),
                state=item.get("state", ""),
                link=item.get("link", ""),
            )
            for item in json.loads(raw)
        ]

    def issue_comments(self, repo_name: str, issue_number: int) -> list[IssueComment]:
        command = [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repo_name,
            "--json",
            "comments",
        ]
        raw = self.command_runner(command, self._env())
        data = json.loads(raw)
        return [_comment_from_gh(item) for item in data.get("comments", [])]

    def open_prs_for_issue(
        self,
        repo_name: str,
        issue_number: int,
    ) -> list[PullRequest]:
        command = [
            "gh",
            "pr",
            "list",
            "--repo",
            repo_name,
            "--state",
            "open",
            "--search",
            str(issue_number),
            "--json",
            "number,title,url,author",
        ]
        raw = self.command_runner(command, self._env())
        return [_pull_request_from_gh(item) for item in json.loads(raw)]

    def comment_issue(self, repo_name: str, issue_number: int, body: str) -> str:
        command = [
            "gh",
            "issue",
            "comment",
            str(issue_number),
            "--repo",
            repo_name,
            "--body",
            body,
        ]
        return self.command_runner(command, self._env()).strip()

    def create_pr(
        self,
        repo_name: str,
        *,
        title: str,
        body: str,
        base: str,
        head: str,
        draft: bool,
    ) -> str:
        command = [
            "gh",
            "pr",
            "create",
            "--repo",
            repo_name,
            "--title",
            title,
            "--body",
            body,
            "--base",
            base,
            "--head",
            head,
        ]
        if draft:
            command.append("--draft")
        return self.command_runner(command, self._env()).strip()

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.secrets.github_token:
            env["GH_TOKEN"] = self.secrets.github_token
        env["CONTROLLER_GH_TIMEOUT_SECONDS"] = str(self.timeout_seconds)
        return env


def run_command(command: list[str], env: dict[str, str]) -> str:
    timeout_seconds = _gh_timeout_seconds(env)
    try:
        completed = subprocess.run(
            command,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        timeout_label = _format_timeout_seconds(timeout_seconds)
        command_label = " ".join(command[:5])
        raise RuntimeError(
            f"gh command timed out after {timeout_label}s: {command_label}"
        ) from error
    return completed.stdout


def _gh_timeout_seconds(env: dict[str, str]) -> float:
    raw_value = env.get("CONTROLLER_GH_TIMEOUT_SECONDS", "")
    if not raw_value:
        return DEFAULT_GH_TIMEOUT_SECONDS
    try:
        timeout_seconds = float(raw_value)
    except ValueError:
        return DEFAULT_GH_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        return DEFAULT_GH_TIMEOUT_SECONDS
    return timeout_seconds


def _format_timeout_seconds(timeout_seconds: float) -> str:
    if timeout_seconds.is_integer():
        return str(int(timeout_seconds))
    return str(timeout_seconds)


def _issue_from_gh(repo_name: str, data: dict) -> Issue:
    labels = [
        item.get("name", "")
        for item in data.get("labels", [])
        if isinstance(item, dict)
    ]
    assignees = [
        item.get("login", "")
        for item in data.get("assignees", [])
        if isinstance(item, dict)
    ]
    return Issue(
        repo=repo_name,
        number=int(data["number"]),
        title=data["title"],
        url=data["url"],
        labels=labels,
        assignees=assignees,
        updated_at=data.get("updatedAt", ""),
        state=data.get("state", "open"),
    )


def _comment_from_gh(data: dict) -> IssueComment:
    author = data.get("author", {})
    login = ""
    if isinstance(author, dict):
        login = str(author.get("login", ""))
    return IssueComment(
        author=login,
        body=str(data.get("body", "")),
        url=str(data.get("url", "")),
    )


def _pull_request_from_gh(data: dict) -> PullRequest:
    author = data.get("author", {})
    login = ""
    if isinstance(author, dict):
        login = str(author.get("login", ""))
    return PullRequest(
        number=int(data["number"]),
        title=str(data.get("title", "")),
        url=str(data.get("url", "")),
        author=login,
    )
