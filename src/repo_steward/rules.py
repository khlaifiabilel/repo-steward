"""Explainable deterministic rules and transparent scoring."""

from collections.abc import Callable
from dataclasses import dataclass

from repo_steward.models import Category, Finding, RepositorySnapshot, Severity


@dataclass(frozen=True)
class Rule:
    rule_id: str
    title: str
    category: Category
    severity: Severity
    deduction: int
    evidence: str
    recommendation: str
    missing: Callable[[RepositorySnapshot, set[str]], bool]

    def evaluate(self, snapshot: RepositorySnapshot, paths: set[str]) -> Finding | None:
        if not self.missing(snapshot, paths):
            return None
        return Finding(
            rule_id=self.rule_id,
            title=self.title,
            category=self.category,
            severity=self.severity,
            evidence=self.evidence,
            recommendation=self.recommendation,
        )


def _root_file(*names: str) -> Callable[[RepositorySnapshot, set[str]], bool]:
    expected = {name.casefold() for name in names}
    return lambda _snapshot, paths: not bool(expected & paths)


def _prefix(prefix: str) -> Callable[[RepositorySnapshot, set[str]], bool]:
    folded = prefix.casefold()
    return lambda _snapshot, paths: not any(path.startswith(folded) for path in paths)


def has_license(snapshot: RepositorySnapshot, paths: set[str]) -> bool:
    """Return whether SPDX metadata or a recognized root license file is present."""
    return bool(snapshot.license) or bool(
        {"license", "license.md", "license.txt", "license.rst", "copying", "copying.md"} & paths
    )


RULES: tuple[Rule, ...] = (
    Rule(
        "DOC001",
        "Missing README",
        Category.DOCUMENTATION,
        Severity.HIGH,
        30,
        "No root README file was found.",
        "Add a root README describing purpose and usage.",
        _root_file("README", "README.md", "README.rst", "README.txt"),
    ),
    Rule(
        "DOC002",
        "Missing license",
        Category.DOCUMENTATION,
        Severity.HIGH,
        25,
        "No root license file or declared license was found.",
        "Declare a license and add its text in a root LICENSE file.",
        lambda snapshot, paths: not has_license(snapshot, paths),
    ),
    Rule(
        "COM001",
        "Missing security policy",
        Category.COMMUNITY,
        Severity.MEDIUM,
        15,
        "No SECURITY.md was found at the root, docs/, or .github/.",
        "Add SECURITY.md with private vulnerability reporting instructions.",
        _root_file("SECURITY.md", "docs/SECURITY.md", ".github/SECURITY.md"),
    ),
    Rule(
        "COM002",
        "Missing contributing guide",
        Category.COMMUNITY,
        Severity.LOW,
        10,
        "No CONTRIBUTING file was found at the root, docs/, or .github/.",
        "Add contribution setup, testing, and review guidance.",
        _root_file(
            "CONTRIBUTING", "CONTRIBUTING.md", "docs/CONTRIBUTING.md", ".github/CONTRIBUTING.md"
        ),
    ),
    Rule(
        "COM003",
        "Missing code of conduct",
        Category.COMMUNITY,
        Severity.LOW,
        10,
        "No CODE_OF_CONDUCT.md was found at the root, docs/, or .github/.",
        "Adopt and publish a code of conduct.",
        _root_file("CODE_OF_CONDUCT.md", "docs/CODE_OF_CONDUCT.md", ".github/CODE_OF_CONDUCT.md"),
    ),
    Rule(
        "COM004",
        "Missing issue templates",
        Category.COMMUNITY,
        Severity.LOW,
        10,
        "No files were found under .github/ISSUE_TEMPLATE/.",
        "Add focused issue forms or templates.",
        _prefix(".github/issue_template/"),
    ),
    Rule(
        "COM005",
        "Missing pull request template",
        Category.COMMUNITY,
        Severity.LOW,
        10,
        "No pull request template was found in a supported location.",
        "Add a pull request template with validation and context prompts.",
        _root_file(
            "PULL_REQUEST_TEMPLATE.md",
            ".github/PULL_REQUEST_TEMPLATE.md",
            "docs/PULL_REQUEST_TEMPLATE.md",
        ),
    ),
    Rule(
        "AUT001",
        "No CI workflow",
        Category.AUTOMATION,
        Severity.HIGH,
        30,
        "No YAML workflow was found under .github/workflows/.",
        "Add a CI workflow that runs the project's tests and checks.",
        lambda _snapshot, paths: (
            not any(
                path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))
                for path in paths
            )
        ),
    ),
    Rule(
        "META001",
        "Missing description",
        Category.METADATA,
        Severity.LOW,
        15,
        "Repository description is empty.",
        "Add a concise repository description.",
        lambda snapshot, _paths: snapshot.description is None,
    ),
    Rule(
        "META002",
        "No topics",
        Category.METADATA,
        Severity.LOW,
        10,
        "Repository has no topics.",
        "Add a small set of discoverability topics.",
        lambda snapshot, _paths: not snapshot.topics,
    ),
)

CATEGORY_WEIGHTS: dict[Category, int] = {
    Category.DOCUMENTATION: 30,
    Category.COMMUNITY: 30,
    Category.AUTOMATION: 25,
    Category.METADATA: 15,
}

ARCHIVED_FINDING = Finding(
    rule_id="LIFE001",
    title="Repository is archived",
    category=Category.LIFECYCLE,
    severity=Severity.INFO,
    evidence="Repository metadata marks it as archived.",
    recommendation="No action required; archived repositories are excluded from deductions.",
)
