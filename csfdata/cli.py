"""Command-line interface for inspecting simulation grids."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from csfdata.adapters.dcaf import DcafAdapter
from csfdata.discovery.local import LocalGridDiscoverer
from csfdata.discovery.report import DiscoveryReport


def main(argv: str = None) -> int:
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

    args = parser.parse_args(argv)
    if args.command == "discover":
        try:
            report = LocalGridDiscoverer(args.root, DcafAdapter).discover()
        except NotADirectoryError as error:
            parser.error(str(error))
        _print_discovery_report(report)
        return 0

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


if __name__ == "__main__":
    raise SystemExit(main())
