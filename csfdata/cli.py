"""Command-line interface for inspecting simulation grids."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import socket
import sys

import yaml

from csfdata.adapters.dcaf import DcafAdapter
from csfdata.catalogue.collection import read_collection_configuration
from csfdata.discovery.local import LocalGridDiscoverer
from csfdata.importer.local import import_manifest
from csfdata.importer.manifest import create_import_manifest
from csfdata.importer.validation import read_validation_report


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
    import_parser = subparsers.add_parser(
        "import",
        help="Import a reviewed D-CAF manifest into a local catalogue.",
    )
    import_parser.add_argument("root", type=Path, help="Existing catalogue root directory.")
    import_parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Reviewed YAML validation report.",
    )
    import_parser.add_argument(
        "--collection",
        type=Path,
        required=True,
        help="YAML collection configuration.",
    )
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check the import without changing the catalogue.",
    )

    args = parser.parse_args(argv)
    if args.command == "validate":
        return validate_grid(args.root, args.report, parser=validate_parser)
    return import_collection(
        args.root,
        args.report,
        args.collection,
        parser=import_parser,
        dry_run=args.dry_run,
    )


def validate_grid(
    root: Path,
    report_path: Path,
    parser: argparse.ArgumentParser | None = None,
) -> int:
    """Validate a grid in stages and write a persistent YAML report.

    Args:
        root: Grid directory to scan and validate.
        report_path: Destination path for the portable validation report.
        parser: Optional CLI parser used to present filesystem errors. Omit it
            when calling this function from Python.

    Returns:
        Zero after successfully writing the validation report.

    Raises:
        NotADirectoryError: If ``root`` is not a directory and no ``parser``
            is provided.
        OSError: If the report cannot be written and no ``parser`` is provided.
    """
    try:
        discovery_report = LocalGridDiscoverer(root, DcafAdapter).discover()
    except NotADirectoryError as error:
        if parser is None:
            raise
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
                validation_report_data(root, results),
                allow_unicode=False,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    except OSError as error:
        if parser is None:
            raise
        parser.error(f"Cannot write report {report_path}: {error}")
    issue_count = sum(bool(issues) for _, issues in results)
    print(f"Validated: {len(results)} simulations")
    print(f"Valid for transfer: {len(results) - issue_count}")
    print(f"With issues: {issue_count}")
    print(f"Report saved: {report_path}")
    return 0


def validation_report_data(
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
        "summary": {
            "total_simulations": len(results),
            "valid_simulations": len(valid_simulations),
            "simulations_with_issues": len(simulations_with_issues),
        },
        "valid_simulations": valid_simulations,
        "simulations_with_issues": simulations_with_issues,
    }


def import_collection(
    catalogue_root: Path,
    report_path: Path,
    collection_path: Path,
    parser: argparse.ArgumentParser | None = None,
    dry_run: bool = False,
) -> int:
    """Import one reviewed D-CAF manifest into a local catalogue.

    Args:
        catalogue_root: Existing root directory of the destination catalogue.
        report_path: Reviewed YAML validation report path.
        collection_path: YAML collection configuration path.
        parser: Optional CLI parser used to present errors. Omit it when
            calling this function from Python.
        dry_run: Whether to stop after preflight without changing the catalogue.

    Returns:
        Zero after every manifest item has been imported.

    Raises:
        OSError: If an input cannot be read or an import filesystem operation
            fails and no ``parser`` is provided.
        ValueError: If an input is invalid, the collection is not D-CAF, or
            import preflight fails and no ``parser`` is provided.
        yaml.YAMLError: If an input YAML file is invalid and no ``parser`` is
            provided.
    """
    try:
        validated_source = read_validation_report(report_path)
        collection = read_collection_configuration(collection_path)
        if collection.importer != "dcaf":
            raise ValueError(
                "The import command currently supports only collection importer: dcaf."
            )
        manifest = create_import_manifest(validated_source, collection.collection_id)
        destinations = import_manifest(
            manifest,
            catalogue_root,
            collection_path,
            DcafAdapter,
            dry_run=dry_run,
        )
    except (OSError, ValueError, yaml.YAMLError) as error:
        if parser is None:
            raise
        parser.error(str(error))

    if dry_run:
        print(f"Dry run: {len(destinations)} simulations ready to import")
    else:
        print(f"Imported: {len(destinations)} simulations")
    print(f"Collection: {collection.collection_id}")
    print(f"Catalogue root: {catalogue_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
