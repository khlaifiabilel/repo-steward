import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from repo_steward.app import create_app
from repo_steward.config import Settings
from repo_steward.github import GitHubAPIError, GitHubTimeoutError
from repo_steward.models import InventoryRequest


def test_health(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Correlation-ID": "request-1"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Correlation-ID"] == "request-1"


def test_analyze_without_credentials(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyze",
        json={
            "owner": "acme",
            "name": "widget",
            "description": "Widget",
            "license": "MIT",
            "topics": ["python"],
            "file_paths": ["README.md", ".github/workflows/ci.yml"],
        },
    )
    assert response.status_code == 200
    assert response.json()["repository"] == "acme/widget"
    assert response.json()["total_score"] >= 0


def test_inventory_endpoint(client: TestClient) -> None:
    response = client.post(
        "/api/v1/inventory",
        json={
            "snapshots": [
                {"owner": "acme", "name": "public"},
                {"owner": "acme", "name": "fork", "fork": True},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["forks"] == 1


def test_owner_analysis_fails_clearly_without_credentials(client: TestClient) -> None:
    assert client.get("/api/v1/github/owners/acme/analyze").status_code == 405
    response = client.post("/api/v1/github/owners/acme/analyze")
    assert response.status_code == 503
    assert response.json() == {"detail": "GitHub credentials are not configured"}


def test_snapshot_validation_is_exposed(client: TestClient) -> None:
    response = client.post("/api/v1/analyze", json={"owner": "bad/owner", "name": "repo"})
    assert response.status_code == 422


def test_configured_api_key_protects_every_api_endpoint() -> None:
    with TestClient(create_app(Settings(api_key="a" * 32))) as protected:
        assert (
            protected.post("/api/v1/analyze", json={"owner": "acme", "name": "repo"}).status_code
            == 401
        )
        assert protected.post("/api/v1/inventory", json={"snapshots": []}).status_code == 401
        response = protected.post(
            "/api/v1/analyze",
            headers={"X-Repo-Steward-Key": "a" * 32},
            json={"owner": "acme", "name": "repo"},
        )
        assert response.status_code == 200
        assert protected.get("/healthz").status_code == 200


def test_owner_must_be_explicitly_allowed_and_have_credentials(client: TestClient) -> None:
    assert client.post("/api/v1/github/owners/other/analyze").status_code == 403


def test_owner_analysis_sanitizes_upstream_errors() -> None:
    settings = Settings(github_token="token", github_allowed_owners=("acme",))
    with (
        patch(
            "repo_steward.routes.GitHubClient.owner_snapshots",
            new=AsyncMock(side_effect=GitHubAPIError(403, "unsafe")),
        ),
        TestClient(create_app(settings)) as owner_client,
    ):
        response = owner_client.post("/api/v1/github/owners/acme/analyze")
    assert response.status_code == 502
    assert response.json() == {"detail": "GitHub request failed"}
    assert "unsafe" not in response.text


def test_owner_analysis_maps_timeout() -> None:
    settings = Settings(github_token="token", github_allowed_owners=("acme",))
    with (
        patch(
            "repo_steward.routes.GitHubClient.owner_snapshots",
            new=AsyncMock(side_effect=GitHubTimeoutError()),
        ),
        TestClient(create_app(settings)) as owner_client,
    ):
        response = owner_client.post("/api/v1/github/owners/acme/analyze")
    assert response.status_code == 504


def test_owner_analysis_has_aggregate_timeout() -> None:
    async def delayed(_client: object, _owner: str) -> tuple[object, ...]:
        await asyncio.sleep(1)
        return ()

    settings = Settings(
        github_token="token",
        github_allowed_owners=("acme",),
        github_owner_timeout_seconds=0.001,
    )
    with (
        patch("repo_steward.routes.GitHubClient.owner_snapshots", new=delayed),
        TestClient(create_app(settings)) as owner_client,
    ):
        response = owner_client.post("/api/v1/github/owners/acme/analyze")
    assert response.status_code == 504


def test_request_body_limit_covers_api_routes_and_chunked_stream() -> None:
    settings = Settings(max_request_body_bytes=128, github_webhook_secret="secret")
    with TestClient(create_app(settings)) as limited:
        analyze = limited.post("/api/v1/analyze", content=b"x" * 129)
        inventory = limited.post(
            "/api/v1/inventory", content=(part for part in [b"x" * 64, b"y" * 65])
        )
    assert analyze.status_code == 413
    assert inventory.status_code == 413
    assert analyze.headers["X-Correlation-ID"]


def test_inventory_snapshot_count_is_bounded() -> None:
    snapshots = tuple({"owner": "acme", "name": "repo"} for _ in range(1001))
    try:
        InventoryRequest(snapshots=snapshots)
    except ValueError as exc:
        assert "at most 1000 items" in str(exc)
    else:
        raise AssertionError("oversized inventory was accepted")


def test_unhandled_failures_are_sanitized_and_correlated() -> None:
    application = create_app(Settings())

    async def explode() -> None:
        raise RuntimeError("sensitive input must not escape")

    application.add_api_route("/explode", explode)
    with TestClient(application, raise_server_exceptions=False) as failing:
        response = failing.get("/explode", headers={"X-Correlation-ID": "safe-id"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers["X-Correlation-ID"] == "safe-id"
    assert "sensitive input" not in response.text
