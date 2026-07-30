"""Bounded, read-only GitHub REST client."""

import re
from collections import deque
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from repo_steward.models import RepositorySnapshot

_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class GitHubError(Exception):
    """Base error for expected GitHub failures."""


class GitHubAPIError(GitHubError):
    def __init__(self, status_code: int, operation: str = "request failed") -> None:
        super().__init__(f"GitHub API {operation} ({status_code})")
        self.status_code = status_code


class GitHubProtocolError(GitHubError):
    """GitHub returned an unexpected response shape."""


class GitHubLimitError(GitHubError):
    """A configured safety bound prevented further processing."""


class GitHubTraversalLimitError(GitHubLimitError):
    """A configured traversal bound prevented further traversal."""


class GitHubTimeoutError(GitHubError):
    """GitHub did not respond within the configured request timeout."""


class GitHubTransportError(GitHubError):
    """GitHub could not be reached through the configured transport."""


def validate_owner(owner: str) -> str:
    if not _OWNER_RE.fullmatch(owner):
        raise ValueError("invalid GitHub owner identifier")
    return owner


def validate_repo(repo: str) -> str:
    if not _REPO_RE.fullmatch(repo) or repo in {".", ".."}:
        raise ValueError("invalid GitHub repository identifier")
    return repo


def validate_base_url(base_url: str, *, allow_localhost_http: bool = False) -> str:
    parsed = urlsplit(base_url)
    localhost = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    valid_scheme = parsed.scheme == "https" or (
        allow_localhost_http and parsed.scheme == "http" and localhost
    )
    if (
        not valid_scheme
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("GitHub API URL must be HTTPS (test localhost may use HTTP)")
    if parsed.hostname != "api.github.com" and not (allow_localhost_http and localhost):
        raise ValueError("GitHub API URL host is not allowed")
    return base_url.rstrip("/")


def _bounded(name: str, value: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


class GitHubClient:
    """Minimal async REST client exposing only bounded read operations."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.github.com",
        timeout: float = 10.0,
        max_pages: int = 20,
        max_tree_requests: int = 500,
        max_repositories: int = 500,
        max_requests: int = 2000,
        max_response_bytes: int = 2_097_152,
        max_tree_entries: int = 100_000,
        max_queued_trees: int = 10_000,
        max_retained_paths: int = 100_000,
        allow_localhost_http: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not token:
            raise ValueError("GitHub token must not be empty")
        if not 0 < timeout <= 60:
            raise ValueError("timeout must be greater than zero and at most 60")
        self.max_pages = _bounded("max_pages", max_pages, 100)
        self.max_tree_requests = _bounded("max_tree_requests", max_tree_requests, 5000)
        self.max_repositories = _bounded("max_repositories", max_repositories, 5000)
        self.max_requests = _bounded("max_requests", max_requests, 10_000)
        self.max_response_bytes = _bounded("max_response_bytes", max_response_bytes, 16_777_216)
        self.max_tree_entries = _bounded("max_tree_entries", max_tree_entries, 1_000_000)
        self.max_queued_trees = _bounded("max_queued_trees", max_queued_trees, 100_000)
        self.max_retained_paths = _bounded("max_retained_paths", max_retained_paths, 1_000_000)
        self._request_count = 0
        self._tree_entry_count = 0
        self._client = httpx.AsyncClient(
            base_url=validate_base_url(base_url, allow_localhost_http=allow_localhost_http),
            timeout=httpx.Timeout(timeout),
            transport=transport,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "repo-steward/0.1.0",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, *, params: dict[str, str | int] | None = None) -> Any:
        if self._request_count >= self.max_requests:
            raise GitHubLimitError("GitHub request limit reached")
        self._request_count += 1
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise GitHubTimeoutError("GitHub request timed out") from exc
        except httpx.TransportError as exc:
            raise GitHubTransportError("GitHub transport failed") from exc
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_response_bytes:
                    raise GitHubLimitError("GitHub response byte limit reached")
            except ValueError as exc:
                raise GitHubProtocolError("GitHub returned invalid Content-Length") from exc
        if len(response.content) > self.max_response_bytes:
            raise GitHubLimitError("GitHub response byte limit reached")
        if response.is_error:
            raise GitHubAPIError(response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubProtocolError("GitHub returned non-JSON content") from exc

    async def _paginate(self, path: str) -> AsyncIterator[dict[str, Any]]:
        count = 0
        for page in range(1, self.max_pages + 1):
            payload = await self._get(path, params={"per_page": 100, "page": page})
            if not isinstance(payload, list):
                raise GitHubProtocolError("expected a paginated list")
            for item in payload:
                if not isinstance(item, dict):
                    raise GitHubProtocolError("expected an object in paginated response")
                count += 1
                if count > self.max_repositories:
                    raise GitHubLimitError("GitHub repository limit reached")
                yield item
            if len(payload) < 100:
                return
        raise GitHubTraversalLimitError("repository pagination limit reached")

    async def fetch_owner_repositories(self, owner: str) -> tuple[dict[str, Any], ...]:
        owner = validate_owner(owner)
        return tuple([item async for item in self._paginate(f"/users/{owner}/repos")])

    async def repository_file_paths(self, owner: str, repo: str, tree_ref: str) -> tuple[str, ...]:
        owner, repo = validate_owner(owner), validate_repo(repo)
        if (
            not tree_ref
            or len(tree_ref) > 255
            or tree_ref in {".", ".."}
            or ".." in tree_ref.split("/")
        ):
            raise ValueError("invalid Git tree reference")
        base = f"/repos/{owner}/{repo}/git/trees"
        encoded_ref = quote(tree_ref, safe="")
        payload = await self._get(f"{base}/{encoded_ref}", params={"recursive": "1"})
        tree = self._tree_entries(payload)
        tree_requests = 1
        if not payload.get("truncated", False):
            recursive_paths = {entry["path"] for entry in tree if entry.get("type") == "blob"}
            self._check_retained_paths(recursive_paths)
            return tuple(sorted(recursive_paths))

        paths: set[str] = set()
        queue: deque[tuple[str, str]] = deque([(encoded_ref, "")])
        while queue:
            if tree_requests >= self.max_tree_requests:
                raise GitHubTraversalLimitError("Git tree request limit reached")
            sha, prefix = queue.popleft()
            entries = self._tree_entries(await self._get(f"{base}/{sha}"))
            tree_requests += 1
            for entry in entries:
                path = entry.get("path")
                kind = entry.get("type")
                entry_sha = entry.get("sha")
                if not isinstance(path, str):
                    raise GitHubProtocolError("tree entry has no path")
                full_path = f"{prefix}/{path}" if prefix else path
                if kind == "blob":
                    paths.add(full_path)
                    self._check_retained_paths(paths)
                elif kind == "tree":
                    if not isinstance(entry_sha, str):
                        raise GitHubProtocolError("tree entry has no SHA")
                    if len(queue) >= self.max_queued_trees:
                        raise GitHubTraversalLimitError("queued Git tree limit reached")
                    queue.append((entry_sha, full_path))
        return tuple(sorted(paths))

    def _tree_entries(self, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("tree"), list):
            raise GitHubProtocolError("expected a Git tree response")
        entries = payload["tree"]
        if not all(isinstance(item, dict) for item in entries):
            raise GitHubProtocolError("invalid Git tree entry")
        self._tree_entry_count += len(entries)
        if self._tree_entry_count > self.max_tree_entries:
            raise GitHubTraversalLimitError("Git tree entry limit reached")
        return [dict(item) for item in entries]

    def _check_retained_paths(self, paths: set[str]) -> None:
        if len(paths) > self.max_retained_paths:
            raise GitHubTraversalLimitError("retained path limit reached")

    async def owner_snapshots(self, owner: str) -> tuple[RepositorySnapshot, ...]:
        repositories = await self.fetch_owner_repositories(owner)
        snapshots: list[RepositorySnapshot] = []
        for repository in repositories:
            name = repository.get("name")
            default_branch = repository.get("default_branch") or "main"
            if not isinstance(name, str) or not isinstance(default_branch, str):
                raise GitHubProtocolError("repository is missing its name or default branch")
            paths = await self.repository_file_paths(owner, name, default_branch)
            license_data = repository.get("license")
            license_name = license_data.get("spdx_id") if isinstance(license_data, dict) else None
            snapshots.append(
                RepositorySnapshot(
                    owner=owner,
                    name=name,
                    default_branch=default_branch,
                    archived=bool(repository.get("archived")),
                    private=bool(repository.get("private")),
                    fork=bool(repository.get("fork")),
                    description=repository.get("description")
                    if isinstance(repository.get("description"), str)
                    else None,
                    license=license_name if isinstance(license_name, str) else None,
                    topics=tuple(
                        topic for topic in repository.get("topics", []) if isinstance(topic, str)
                    ),
                    file_paths=paths,
                )
            )
        return tuple(snapshots)
