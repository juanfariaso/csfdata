from pathlib import Path

from csfdata.discovery.report import DiscoveredSimulation, DiscoveryReport


def test_discovery_report_groups_valid_and_invalid_simulations() -> None:
    valid = DiscoveredSimulation(run_root=Path("grid/valid"), validation_issues=())
    invalid = DiscoveredSimulation(
        run_root=Path("grid/invalid"),
        validation_issues=("No readable background-gas time records found.",),
    )
    report = DiscoveryReport(root=Path("grid"), simulations=(valid, invalid))

    assert valid.is_valid
    assert not invalid.is_valid
    assert report.valid_simulations == (valid,)
    assert report.invalid_simulations == (invalid,)
