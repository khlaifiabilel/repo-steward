import asyncio
from collections.abc import Awaitable, Callable

import httpx
import pytest

from repo_steward.github import (
    GitHubAPIError,
    GitHubClient,
    GitHubLimitError,
    GitHubProtocolError,
    GitHubTimeoutError,
    GitHubTransportError,
    GitHubTraversalLimitError,
    validate_owner,
    validate_repo,
)

Handler = Callable[[httpx.Request], httpx.Response]


def run(coroutine: Awaitable[object]) -> object:
    return asyncio.run(coroutine)


async def with_client(
    handler: Handler, action: Callable[[GitHubClient], Awaitable[object]], **kwargs: object
) -> object:
    async with GitHubClient(
        "generated-test-token", transport=httpx.MockTransport(handler), **kwargs
    ) as client:
        return await action(client)


def test_owner_repository_pagination_and_headers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = request.url.params["page"]
        payload = (
            [{"name": f"repo-{index}"} for index in range(100)]
            if page == "1"
            else [{"name": "last"}]
        )
        return httpx.Response(200, json=payload)

    repositories = run(with_client(handler, lambda client: client.fetch_owner_repositories("acme")))
    assert isinstance(repositories, tuple)
    assert len(repositories) == 101
    assert len(requests) == 2
    assert requests[0].headers["Authorization"] == "Bearer generated-test-token"
    assert requests[0].headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert requests[0].headers["User-Agent"].startswith("repo-steward/")


def test_recursive_tree_returns_blob_paths() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["recursive"] == "1"
        return httpx.Response(
            200,
            json={
                "truncated": False,
                "tree": [
                    {"path": "src", "type": "tree", "sha": "tree-sha"},
                    {"path": "README.md", "type": "blob", "sha": "blob-sha"},
                ],
            },
        )

    paths = run(
        with_client(handler, lambda client: client.repository_file_paths("acme", "widget", "main"))
    )
    assert paths == ("README.md",)


def test_truncated_tree_falls_back_to_bounded_non_recursive_walk() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.params.get("recursive") == "1":
            return httpx.Response(200, json={"truncated": True, "tree": []})
        if request.url.path.endswith("/main"):
            return httpx.Response(
                200,
                json={
                    "tree": [
                        {"path": "README.md", "type": "blob", "sha": "blob"},
                        {"path": "src", "type": "tree", "sha": "src-sha"},
                    ]
                },
            )
        assert request.url.path.endswith("/src-sha")
        return httpx.Response(
            200, json={"tree": [{"path": "app.py", "type": "blob", "sha": "app-sha"}]}
        )

    paths = run(
        with_client(handler, lambda client: client.repository_file_paths("acme", "widget", "main"))
    )
    assert paths == ("README.md", "src/app.py")
    assert len(requests) == 3


def test_tree_walk_limit_is_enforced() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("recursive") == "1":
            return httpx.Response(200, json={"truncated": True, "tree": []})
        return httpx.Response(
            200, json={"tree": [{"path": "child", "type": "tree", "sha": "next"}]}
        )

    with pytest.raises(GitHubTraversalLimitError, match="tree request"):
        run(
            with_client(
                handler,
                lambda client: client.repository_file_paths("acme", "widget", "main"),
                max_tree_requests=1,
            )
        )


def test_api_error_is_typed_and_does_not_include_token() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "rate limit exceeded"})

    with pytest.raises(GitHubAPIError, match=r"request failed \(403\)") as caught:
        run(with_client(handler, lambda client: client.fetch_owner_repositories("acme")))
    assert "generated-test-token" not in str(caught.value)


def test_non_json_and_invalid_shapes_are_protocol_errors() -> None:
    def non_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not JSON")

    with pytest.raises(GitHubProtocolError, match="non-JSON"):
        run(with_client(non_json, lambda client: client.fetch_owner_repositories("acme")))

    def object_response(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(GitHubProtocolError, match="paginated list"):
        run(with_client(object_response, lambda client: client.fetch_owner_repositories("acme")))


def test_owner_snapshots_map_repository_metadata_and_paths() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/users/acme/repos":
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "widget",
                        "default_branch": "feature/readme",
                        "archived": False,
                        "private": True,
                        "fork": False,
                        "description": "Widget",
                        "license": {"spdx_id": "MIT"},
                        "topics": ["python"],
                    }
                ],
            )
        assert request.url.path.endswith("/feature/readme")
        return httpx.Response(
            200, json={"truncated": False, "tree": [{"path": "README.md", "type": "blob"}]}
        )

    snapshots = run(with_client(handler, lambda client: client.owner_snapshots("acme")))
    assert isinstance(snapshots, tuple)
    assert snapshots[0].name == "widget"
    assert snapshots[0].private is True
    assert snapshots[0].license == "MIT"
    assert snapshots[0].file_paths == ("README.md",)


def test_installation_snapshots_use_only_installation_repositories() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/installation/repositories":
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "repositories": [
                        {
                            "owner": {"login": "acme"},
                            "name": "private-widget",
                            "default_branch": "main",
                            "private": True,
                            "license": {"spdx_id": "Apache-2.0"},
                            "topics": ["python"],
                        }
                    ],
                },
            )
        assert request.url.path == "/repos/acme/private-widget/git/trees/main"
        return httpx.Response(
            200, json={"truncated": False, "tree": [{"path": "README.md", "type": "blob"}]}
        )

    snapshots = run(with_client(handler, lambda client: client.installation_snapshots()))
    assert isinstance(snapshots, tuple)
    assert len(snapshots) == 1
    assert snapshots[0].owner == "acme"
    assert snapshots[0].name == "private-widget"
    assert snapshots[0].private is True
    assert snapshots[0].license == "Apache-2.0"
    assert requests == [
        "/installation/repositories",
        "/repos/acme/private-widget/git/trees/main",
    ]


@pytest.mark.parametrize(
    "payload",
    (
        [],
        {"total_count": 1, "repositories": "invalid"},
        {"total_count": 1, "repositories": ["invalid"]},
        {"total_count": True, "repositories": []},
        {"total_count": 0, "repositories": [{"name": "unexpected"}]},
    ),
)
def test_installation_repository_shapes_are_validated(payload: object) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(GitHubProtocolError):
        run(with_client(handler, lambda client: client.fetch_installation_repositories()))


def test_installation_repository_limit_is_enforced() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "total_count": 2,
                "repositories": [{"name": "one"}, {"name": "two"}],
            },
        )

    with pytest.raises(GitHubLimitError, match="repository limit"):
        run(
            with_client(
                handler,
                lambda client: client.fetch_installation_repositories(),
                max_repositories=1,
            )
        )


def test_installation_snapshot_requires_repository_owner() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/installation/repositories"
        return httpx.Response(
            200,
            json={
                "total_count": 1,
                "repositories": [{"name": "widget", "default_branch": "main"}],
            },
        )

    with pytest.raises(GitHubProtocolError, match="owner"):
        run(with_client(handler, lambda client: client.installation_snapshots()))


@pytest.mark.parametrize("owner", ("bad/owner", "-starts", "ends-", "a" * 40))
def test_invalid_owners_are_rejected(owner: str) -> None:
    with pytest.raises(ValueError, match="owner"):
        validate_owner(owner)


@pytest.mark.parametrize("repo", ("bad/repo", ".", "..", "x" * 101))
def test_invalid_repositories_are_rejected(repo: str) -> None:
    with pytest.raises(ValueError, match="repository"):
        validate_repo(repo)


def test_pagination_limit_is_enforced() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"name": str(index)} for index in range(100)])

    with pytest.raises(GitHubTraversalLimitError, match="pagination"):
        run(
            with_client(
                handler, lambda client: client.fetch_owner_repositories("acme"), max_pages=1
            )
        )


def test_repository_and_total_request_limits_are_enforced() -> None:
    def repositories(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"name": "one"}, {"name": "two"}])

    with pytest.raises(GitHubLimitError, match="repository limit"):
        run(
            with_client(
                repositories,
                lambda client: client.fetch_owner_repositories("acme"),
                max_repositories=1,
            )
        )

    with pytest.raises(GitHubLimitError, match="request limit"):
        run(
            with_client(
                repositories,
                lambda client: client.owner_snapshots("acme"),
                max_requests=1,
            )
        )


def test_response_byte_limit_checks_content() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"[" + b" " * 1024 + b"]")

    with pytest.raises(GitHubLimitError, match="response byte"):
        run(
            with_client(
                handler,
                lambda client: client.fetch_owner_repositories("acme"),
                max_response_bytes=1024,
            )
        )


@pytest.mark.parametrize(
    ("option", "message"),
    [
        ({"max_tree_entries": 1}, "tree entry"),
        ({"max_retained_paths": 1}, "retained path"),
    ],
)
def test_tree_entry_and_retained_path_limits(option: dict[str, int], message: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "truncated": False,
                "tree": [
                    {"path": "one", "type": "blob"},
                    {"path": "two", "type": "blob"},
                ],
            },
        )

    with pytest.raises(GitHubTraversalLimitError, match=message):
        run(
            with_client(
                handler,
                lambda client: client.repository_file_paths("acme", "repo", "main"),
                **option,
            )
        )


def test_queued_tree_limit_and_initial_tree_request_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("recursive") == "1":
            return httpx.Response(200, json={"truncated": True, "tree": []})
        return httpx.Response(
            200,
            json={
                "tree": [
                    {"path": "one", "type": "tree", "sha": "one"},
                    {"path": "two", "type": "tree", "sha": "two"},
                ]
            },
        )

    with pytest.raises(GitHubTraversalLimitError, match="request limit"):
        run(
            with_client(
                handler,
                lambda client: client.repository_file_paths("acme", "repo", "main"),
                max_tree_requests=1,
            )
        )
    with pytest.raises(GitHubTraversalLimitError, match="queued Git tree"):
        run(
            with_client(
                handler,
                lambda client: client.repository_file_paths("acme", "repo", "main"),
                max_queued_trees=1,
            )
        )


def test_timeout_and_transport_failures_are_typed() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("unsafe detail", request=request)

    with pytest.raises(GitHubTimeoutError, match="timed out"):
        run(with_client(timeout, lambda client: client.fetch_owner_repositories("acme")))

    def transport(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unsafe detail", request=request)

    with pytest.raises(GitHubTransportError, match="transport failed"):
        run(with_client(transport, lambda client: client.fetch_owner_repositories("acme")))


@pytest.mark.parametrize(
    "kwargs",
    (
        {"max_pages": 0},
        {"max_tree_requests": 5001},
        {"max_repositories": 0},
        {"max_requests": 0},
        {"max_response_bytes": 0},
        {"max_tree_entries": 0},
        {"max_queued_trees": 0},
        {"max_retained_paths": 0},
        {"timeout": 0},
    ),
)
def test_constructor_bounds_are_validated(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        GitHubClient("token", **kwargs)


def test_constructor_rejects_empty_token_and_arbitrary_hosts() -> None:
    with pytest.raises(ValueError, match="token"):
        GitHubClient("")
    with pytest.raises(ValueError, match="host is not allowed"):
        GitHubClient("token", base_url="https://attacker.example")
