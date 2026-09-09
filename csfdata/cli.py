"""Command-line interface for inspecting simulation grids."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import socket
import sys

import yaml

from csfdata.adapters.dcaf import DcafAdapter
from csfdata.discovery.local import LocalGridDiscoverer


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
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a D-CAF grid and save a YAML report.",
    )
    validate_parser.add_argument("root", type=Path, help="Grid directory to validate.")
    validate_parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path for the YAML validation report.",
    )

    args = parser.parse_args(argv)
    return _validate_grid(args.root, args.report, validate_parser)


def _validate_grid(root: Path, report_path: Path, parser: argparse.ArgumentParser) -> int:
    """Validate a grid in stages and write a persistent YAML report.

    Args:
        root: Grid directory to scan and validate.
        report_path: Destination path for the portable validation report.
        parser: Argument parser used to present filesystem errors.

    Returns:
        Zero after successfully writing the validation report.
    """
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
        report_path.write_text(
            yaml.safe_dump(
                _validation_report_data(root, results),
                allow_unicode=False,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    except OSError as error:
        parser.error(f"Cannot write report {report_path}: {error}")
    issue_count = sum(bool(issues) for _, issues in results)
    print(f"Validated: {len(results)} simulations")
    print(f"Valid for transfer: {len(results) - issue_count}")
    print(f"With issues: {issue_count}")
    print(f"Report saved: {report_path}")
    return 0


def _validation_report_data(
    root: Path,
    results: Sequence[tuple[Path, tuple[str, ...]]],
) -> dict[str, object]:
    """Create the minimal portable data structure for a validation report.

    Args:
        root: Grid root used for validation.
        results: Absolute or root-relative run paths paired with their issues.

    Returns:
        YAML-serializable report data with valid relative paths and invalid
        paths mapped to their human-readable validation issues.
    """
    valid_simulations: list[str] = []
    simulations_with_issues: dict[str, list[str]] = {}
    for run_root, issues in results:
        relative_path = str(run_root.relative_to(root))
        if not issues:
            valid_simulations.append(relative_path)
            continue
        simulations_with_issues[relative_path] = list(issues)

    return {
        "schema_version": 1,
        "source": {
            "hostname": socket.gethostname(),
            "root": str(root.resolve()),
        },
        "valid_simulations": valid_simulations,
        "simulations_with_issues": simulations_with_issues,
    }


if __name__ == "__main__":
    raise SystemExit(main())
