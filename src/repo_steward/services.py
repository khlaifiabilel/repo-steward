"""Application services over pure domain inputs."""

from repo_steward.models import (
    CategoryScore,
    HealthReport,
    InventorySummary,
    RepositorySnapshot,
)
from repo_steward.rules import ARCHIVED_FINDING, CATEGORY_WEIGHTS, RULES, has_license


def analyze(snapshot: RepositorySnapshot) -> HealthReport:
    """Apply fixed rules. Archived repositories are reported but not penalized."""
    if snapshot.archived:
        return HealthReport(
            repository=f"{snapshot.owner}/{snapshot.name}",
            archived=True,
            scored=False,
            category_scores={},
            total_score=None,
            findings=(ARCHIVED_FINDING,),
        )

    paths = {path.casefold() for path in snapshot.file_paths}
    findings = tuple(finding for rule in RULES if (finding := rule.evaluate(snapshot, paths)))
    deductions = {
        category: sum(
            rule.deduction
            for rule in RULES
            if rule.category == category and any(item.rule_id == rule.rule_id for item in findings)
        )
        for category in CATEGORY_WEIGHTS
    }
    scores = {
        category: CategoryScore(score=max(0, 100 - deduction), deductions=deduction)
        for category, deduction in deductions.items()
    }
    total = round(
        sum(scores[category].score * weight for category, weight in CATEGORY_WEIGHTS.items()) / 100
    )
    return HealthReport(
        repository=f"{snapshot.owner}/{snapshot.name}",
        archived=False,
        scored=True,
        category_scores=scores,
        total_score=max(0, min(100, total)),
        findings=findings,
    )


def inventory(snapshots: tuple[RepositorySnapshot, ...]) -> InventorySummary:
    return InventorySummary(
        total=len(snapshots),
        originals=sum(not item.fork for item in snapshots),
        forks=sum(item.fork for item in snapshots),
        archived=sum(item.archived for item in snapshots),
        private=sum(item.private for item in snapshots),
        public=sum(not item.private for item in snapshots),
        no_description=sum(item.description is None for item in snapshots),
        no_license=sum(
            not has_license(item, {path.casefold() for path in item.file_paths})
            for item in snapshots
        ),
    )
