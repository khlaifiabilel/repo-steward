from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from repo_steward.app import create_app
from repo_steward.config import Settings
from repo_steward.models import RepositorySnapshot


@pytest.fixture
def healthy_snapshot() -> RepositorySnapshot:
    return RepositorySnapshot(
        owner="example",
        name="healthy",
        description="A useful repository",
        license="Apache-2.0",
        topics=("python",),
        file_paths=(
            "README.md",
            "LICENSE",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            ".github/ISSUE_TEMPLATE/bug.yml",
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/workflows/ci.yml",
        ),
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(
        github_webhook_secret="test-webhook-secret", github_allowed_owners=("acme",)
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client
