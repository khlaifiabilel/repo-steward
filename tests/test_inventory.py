from repo_steward.models import RepositorySnapshot
from repo_steward.services import inventory


def test_inventory_aggregates_all_required_counts() -> None:
    snapshots = (
        RepositorySnapshot(
            owner="acme", name="one", description="One", license="MIT", private=True
        ),
        RepositorySnapshot(owner="acme", name="two", fork=True, archived=True),
        RepositorySnapshot(owner="acme", name="three", fork=True, license="Apache-2.0"),
    )
    summary = inventory(snapshots)
    assert summary.model_dump() == {
        "total": 3,
        "originals": 1,
        "forks": 2,
        "archived": 1,
        "private": 1,
        "public": 2,
        "no_description": 2,
        "no_license": 1,
    }


def test_empty_inventory_has_zero_counts() -> None:
    assert set(inventory(()).model_dump().values()) == {0}


def test_license_file_and_declared_spdx_use_the_same_presence_rule() -> None:
    snapshots = (
        RepositorySnapshot(owner="acme", name="declared", license="MIT"),
        RepositorySnapshot(owner="acme", name="file", file_paths=("COPYING",)),
        RepositorySnapshot(owner="acme", name="missing"),
    )
    assert inventory(snapshots).no_license == 1
