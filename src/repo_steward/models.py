"""Validated domain models used at API and service boundaries."""

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Category(StrEnum):
    DOCUMENTATION = "documentation"
    COMMUNITY = "community"
    AUTOMATION = "automation"
    METADATA = "metadata"
    LIFECYCLE = "lifecycle"


Topic = Annotated[str, Field(min_length=1, max_length=50)]
FilePath = Annotated[str, Field(min_length=1, max_length=1024)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepositorySnapshot(StrictModel):
    """Facts required for deterministic analysis, independent of GitHub."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    owner: str = Field(
        min_length=1, max_length=39, pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$"
    )
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    default_branch: str = Field(default="main", min_length=1, max_length=255)
    archived: bool = False
    private: bool = False
    fork: bool = False
    description: str | None = Field(default=None, max_length=500)
    license: str | None = Field(default=None, max_length=100)
    topics: tuple[Topic, ...] = Field(default=(), max_length=20)
    file_paths: tuple[FilePath, ...] = Field(default=(), max_length=100_000)

    @field_validator("name")
    @classmethod
    def reject_dot_names(cls, value: str) -> str:
        if value in {".", ".."}:
            raise ValueError("invalid repository name")
        return value

    @field_validator("description")
    @classmethod
    def empty_description_is_none(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @field_validator("topics")
    @classmethod
    def normalize_topics(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted({topic.strip().lower() for topic in value if topic.strip()}))

    @field_validator("file_paths")
    @classmethod
    def normalize_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: set[str] = set()
        for raw_path in value:
            path = raw_path.strip().replace("\\", "/")
            while path.startswith("./"):
                path = path[2:]
            parts = PurePosixPath(path).parts
            normalized_path = str(PurePosixPath(*parts))
            if not path or ".." in parts or path.startswith("/") or normalized_path == ".":
                raise ValueError(f"invalid repository-relative path: {raw_path!r}")
            normalized.add(normalized_path)
        return tuple(sorted(normalized, key=str.casefold))


class Finding(StrictModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    title: str
    category: Category
    severity: Severity
    evidence: str
    recommendation: str
    source: Literal["deterministic"] = "deterministic"
    can_autofix: bool = False


class CategoryScore(StrictModel):
    score: int = Field(ge=0, le=100)
    deductions: int = Field(ge=0)


class HealthReport(StrictModel):
    repository: str
    archived: bool
    scored: bool
    category_scores: dict[Category, CategoryScore]
    total_score: int | None = Field(default=None, ge=0, le=100)
    findings: tuple[Finding, ...]


class InventorySummary(StrictModel):
    total: int
    originals: int
    forks: int
    archived: int
    private: int
    public: int
    no_description: int
    no_license: int


class InventoryRequest(StrictModel):
    snapshots: tuple[RepositorySnapshot, ...] = Field(max_length=1000)


class OwnerAnalysis(StrictModel):
    owner: str
    reports: tuple[HealthReport, ...]
