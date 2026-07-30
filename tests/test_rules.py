import pytest
from pydantic import ValidationError

from repo_steward.models import Category, RepositorySnapshot
from repo_steward.rules import RULES
from repo_steward.services import analyze


@pytest.mark.parametrize(
    ("rule_id", "snapshot_changes", "removed_path"),
    [
        ("DOC001", {}, "README.md"),
        ("DOC002", {"license": None}, "LICENSE"),
        ("COM001", {}, "SECURITY.md"),
        ("COM002", {}, "CONTRIBUTING.md"),
        ("COM003", {}, "CODE_OF_CONDUCT.md"),
        ("COM004", {}, ".github/ISSUE_TEMPLATE/bug.yml"),
        ("COM005", {}, ".github/PULL_REQUEST_TEMPLATE.md"),
        ("AUT001", {}, ".github/workflows/ci.yml"),
        ("META001", {"description": None}, None),
        ("META002", {"topics": ()}, None),
    ],
)
def test_each_rule_fires_only_for_its_missing_fact(
    healthy_snapshot: RepositorySnapshot,
    rule_id: str,
    snapshot_changes: dict[str, object],
    removed_path: str | None,
) -> None:
    paths = tuple(path for path in healthy_snapshot.file_paths if path != removed_path)
    snapshot = healthy_snapshot.model_copy(update={"file_paths": paths, **snapshot_changes})

    report = analyze(snapshot)

    assert [finding.rule_id for finding in report.findings] == [rule_id]
    finding = report.findings[0]
    assert finding.source == "deterministic"
    assert finding.can_autofix is False
    assert finding.evidence
    assert finding.recommendation


def test_complete_repository_scores_100(healthy_snapshot: RepositorySnapshot) -> None:
    report = analyze(healthy_snapshot)
    assert report.total_score == 100
    assert report.findings == ()
    assert all(score.score == 100 for score in report.category_scores.values())


def test_scoring_uses_fixed_deductions_and_weights(
    healthy_snapshot: RepositorySnapshot,
) -> None:
    snapshot = healthy_snapshot.model_copy(
        update={
            "file_paths": tuple(path for path in healthy_snapshot.file_paths if path != "README.md")
        }
    )
    report = analyze(snapshot)
    assert report.category_scores[Category.DOCUMENTATION].score == 70
    assert report.category_scores[Category.DOCUMENTATION].deductions == 30
    assert report.total_score == 91


def test_category_scores_have_zero_floor() -> None:
    report = analyze(RepositorySnapshot(owner="example", name="empty"))
    assert report.category_scores[Category.COMMUNITY].score == 45
    assert 0 <= report.total_score <= 100
    assert len(report.findings) == len(RULES)


def test_archived_repository_is_informational_and_not_penalized() -> None:
    report = analyze(RepositorySnapshot(owner="example", name="old", archived=True))
    assert report.archived is True
    assert report.scored is False
    assert report.total_score is None
    assert report.category_scores == {}
    assert [finding.rule_id for finding in report.findings] == ["LIFE001"]


def test_paths_and_topics_are_normalized() -> None:
    snapshot = RepositorySnapshot(
        owner="example",
        name="normal",
        topics=(" Python ", "python", "API"),
        file_paths=("./README.md", ".github\\workflows\\ci.yml", "README.md"),
    )
    assert snapshot.topics == ("api", "python")
    assert snapshot.file_paths == (".github/workflows/ci.yml", "README.md")


@pytest.mark.parametrize("path", ("../secret", "/etc/passwd", "a/../../secret", "", ".", "./"))
def test_invalid_repository_paths_are_rejected(path: str) -> None:
    with pytest.raises(ValueError, match=r"invalid repository-relative path|at least 1 character"):
        RepositorySnapshot(owner="example", name="bad", file_paths=(path,))


@pytest.mark.parametrize("name", (".", ".."))
def test_dot_repository_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="repository name"):
        RepositorySnapshot(owner="example", name=name)


def test_snapshot_collections_strings_and_extra_fields_are_bounded() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        RepositorySnapshot(owner="example", name="repo", unexpected=True)
    with pytest.raises(ValidationError, match="at most 20 items"):
        RepositorySnapshot(owner="example", name="repo", topics=tuple("x" for _ in range(21)))
    with pytest.raises(ValidationError, match="at most 50 characters"):
        RepositorySnapshot(owner="example", name="repo", topics=("x" * 51,))
    with pytest.raises(ValidationError, match="at most 1024 characters"):
        RepositorySnapshot(owner="example", name="repo", file_paths=("x" * 1025,))
    with pytest.raises(ValidationError, match="at most 500 characters"):
        RepositorySnapshot(owner="example", name="repo", description="x" * 501)
