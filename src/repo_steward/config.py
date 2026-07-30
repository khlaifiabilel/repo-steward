"""Environment-backed application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Secret values are represented by secret types."""

    model_config = SettingsConfigDict(env_prefix="REPO_STEWARD_", env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"
    api_key: SecretStr | None = None
    max_request_body_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    github_token: SecretStr | None = None
    github_api_url: str = "https://api.github.com"
    github_allowed_owners: Annotated[tuple[str, ...], NoDecode] = ()
    github_app_id: int | None = Field(default=None, gt=0)
    github_private_key: SecretStr | None = None
    github_private_key_path: Path | None = None
    github_webhook_secret: SecretStr | None = None
    github_request_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    github_owner_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    github_max_pages: int = Field(default=20, ge=1, le=100)
    github_max_tree_requests: int = Field(default=500, ge=1, le=5000)
    github_max_repositories: int = Field(default=500, ge=1, le=5000)
    github_max_requests: int = Field(default=2000, ge=1, le=10000)
    github_max_response_bytes: int = Field(default=2_097_152, ge=1024, le=16_777_216)
    github_max_tree_entries: int = Field(default=100_000, ge=1, le=1_000_000)
    github_max_queued_trees: int = Field(default=10_000, ge=1, le=100_000)
    github_max_retained_paths: int = Field(default=100_000, ge=1, le=1_000_000)

    @field_validator("github_allowed_owners", mode="before")
    @classmethod
    def parse_allowed_owners(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @model_validator(mode="after")
    def validate_private_key_sources(self) -> "Settings":
        if self.github_private_key and self.github_private_key_path:
            raise ValueError("configure only one GitHub private key source")
        from repo_steward.github import validate_base_url, validate_owner

        self.github_api_url = validate_base_url(
            self.github_api_url, allow_localhost_http=self.environment.casefold() == "test"
        )
        self.github_allowed_owners = tuple(
            sorted({validate_owner(owner).casefold() for owner in self.github_allowed_owners})
        )
        if self.environment.casefold() == "production":
            if self.api_key is None or len(self.api_key.get_secret_value()) < 32:
                raise ValueError(
                    "production API key must be configured with at least 32 characters"
                )
            if (
                self.github_webhook_secret is not None
                and len(self.github_webhook_secret.get_secret_value()) < 32
            ):
                raise ValueError("production webhook secret must contain at least 32 characters")
        return self

    def load_private_key(self) -> str | None:
        """Load an App key without logging or retaining additional copies."""
        if self.github_private_key:
            return self.github_private_key.get_secret_value().replace("\\n", "\n")
        if self.github_private_key_path:
            return self.github_private_key_path.read_text(encoding="utf-8")
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
