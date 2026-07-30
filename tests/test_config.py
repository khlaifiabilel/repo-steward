from pathlib import Path

import pytest
from pydantic import ValidationError

from repo_steward.config import Settings


def test_private_key_can_be_loaded_from_file(tmp_path: Path) -> None:
    key_path = tmp_path / "app.pem"
    key_path.write_text("generated-test-key", encoding="utf-8")
    settings = Settings(github_private_key_path=key_path)
    assert settings.load_private_key() == "generated-test-key"
    assert "generated-test-key" not in repr(settings)


def test_private_key_environment_newlines_are_unescaped() -> None:
    settings = Settings(github_private_key="line-one\\nline-two")
    assert settings.load_private_key() == "line-one\nline-two"


def test_private_key_sources_are_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="only one GitHub private key source"):
        Settings(github_private_key="key", github_private_key_path=tmp_path / "key.pem")


def test_no_private_key_returns_none() -> None:
    assert Settings().load_private_key() is None


def test_production_requires_strong_api_key_and_rejects_weak_webhook_secret() -> None:
    with pytest.raises(ValidationError, match="production API key"):
        Settings(environment="production")
    with pytest.raises(ValidationError, match="production webhook secret"):
        Settings(environment="production", api_key="a" * 32, github_webhook_secret="weak")
    Settings(environment="production", api_key="a" * 32, github_webhook_secret="b" * 32)


def test_allowed_owners_parse_csv_and_api_url_is_restricted() -> None:
    assert Settings(github_allowed_owners="Acme, example").github_allowed_owners == (
        "acme",
        "example",
    )
    with pytest.raises(ValidationError, match="host is not allowed"):
        Settings(github_api_url="https://attacker.example")
    with pytest.raises(ValidationError, match="must be HTTPS"):
        Settings(github_api_url="http://api.github.com")
    assert (
        Settings(environment="test", github_api_url="http://localhost:8000").github_api_url
        == "http://localhost:8000"
    )
