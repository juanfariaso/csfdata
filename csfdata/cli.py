"""Command-line interface for inspecting simulation grids."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from csfdata.adapters.dcaf import DcafAdapter
from csfdata.discovery.local import LocalGridDiscoverer
from csfdata.discovery.report import DiscoveryReport


def main(argv: Sequence[str] | None = None) -> int:
    """Run a csfdata command.

    Args:
        argv: Command arguments without the program name. When ``None``, read
            arguments from the command line.

    Returns:
        Zero after a successful command.
    """
    parser = argparse.ArgumentParser(prog="csfdata")
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover_parser = subparsers.add_parser(
        "discover",
        help="Report D-CAF simulations below a local directory.",
    )
    discover_parser.add_argument("root", type=Path, help="Grid directory to scan.")
    validate_parser = subparsers.add_parser(
        "validate",
        help="Perform detailed D-CAF validation and save a report.",
    )
    validate_parser.add_argument("root", type=Path, help="Grid directory to validate.")
    validate_parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path for the plain-text validation report.",
    )

    args = parser.parse_args(argv)
    if args.command == "discover":
        try:
            report = LocalGridDiscoverer(args.root, DcafAdapter).discover()
        except NotADirectoryError as error:
            parser.error(str(error))
        _print_discovery_report(report)
        return 0
    if args.command == "validate":
        return _validate_grid(args.root, args.report, parser)

    raise AssertionError(f"Unknown command: {args.command}")


def _print_discovery_report(report: DiscoveryReport) -> None:
    """Print a human-readable discovery report."""
    print(f"Grid: {report.root}")
    print(f"Simulations found: {len(report.simulations)}")
    print(f"Valid: {len(report.valid_simulations)}")
    print(f"Invalid: {len(report.invalid_simulations)}")

    if not report.invalid_simulations:
        return

    print("\nInvalid simulations:")
    for simulation in report.invalid_simulations:
        print(f"- {simulation.run_root}")
        for issue in simulation.validation_issues:
            print(f"  - {issue}")


def _validate_grid(root: Path, report_path: Path, parser: argparse.ArgumentParser) -> int:
    """Validate a grid in stages and write a persistent plain-text report."""
    try:
        discovery_report = LocalGridDiscoverer(root, DcafAdapter).discover()
    except NotADirectoryError as error:
        parser.error(str(error))

    results: list[tuple[Path, tuple[str, ...]]] = []
    total = len(discovery_report.simulations)
    interactive = sys.stdout.isatty()
    for index, discovered_simulation in enumerate(discovery_report.simulations, start=1):
        run_root = discovered_simulation.run_root
        if interactive:
            print(f"\r[{index:>4}/{total}] Checking {run_root} ...", end="", flush=True)

        issues = discovered_simulation.validation_issues
        if issues:
            # Open HDF5 snapshots only after the inexpensive structural screen flags a run.
            issues = DcafAdapter(run_root).validate_simulation(detailed=True)
        results.append((run_root, issues))
        prefix = "\r" if interactive else ""
        if issues:
            print(f"{prefix}[{index:>4}/{total}] ISSUE: {run_root} ({len(issues)} issues)          ")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"{prefix}[{index:>4}/{total}] OK: {run_root}          ")

    try:
        report_path.write_text(_validation_report_text(root, results), encoding="utf-8")
    except OSError as error:
        parser.error(f"Cannot write report {report_path}: {error}")
    print(f"Report saved: {report_path}")
    return 0


def _validation_report_text(
    root: Path,
    results: Sequence[tuple[Path, tuple[str, ...]]],
) -> str:
    """Format detailed-validation results as a stable plain-text report."""
    lines = [f"D-CAF validation report for: {root}", ""]
    for run_root, issues in results:
        if not issues:
            lines.append(f"OK: {run_root}")
            continue
        lines.append(f"ISSUE: {run_root}")
        lines.extend(f"  - {issue}" for issue in issues)

    issue_count = sum(bool(issues) for _, issues in results)
    lines.extend(
        (
            "",
            f"Checked: {len(results)}",
            f"No issues: {len(results) - issue_count}",
            f"With issues: {issue_count}",
            "",
        )
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
