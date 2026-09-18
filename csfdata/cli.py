"""Command-line interface for inspecting simulation grids."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import csv
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
from typing import Callable

import yaml

from csfdata.adapters.dcaf import DcafAdapter
from csfdata.catalogue.collection import read_collection_configuration
from csfdata.catalogue.lite import import_lite_collection
from csfdata.catalogue.registry import (
    index_catalogue,
    missing_combinations,
    summarize_catalogue,
)
from csfdata.catalogue.snapshots import (
    clear_snapshots,
    list_snapshots,
    write_snapshot_manifest,
)
from csfdata.discovery.local import LocalGridDiscoverer
from csfdata.importer.local import import_manifest
from csfdata.importer.manifest import create_import_manifest
from csfdata.importer.validation import read_validation_report
from csfdata.analysis import load as load_analysis


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
        help="Import a reviewed D-CAF validation report into a local catalogue.",
        description=(
            "Import simulations approved by a validation report into a local "
            "catalogue. The collection.yaml id selects the destination "
            "collection; its directory is created on the first successful import."
        ),
        epilog=(
            "The catalogue root must already exist. Run with --dry-run first "
            "to check source files, collection requirements, and destination "
            "conflicts without creating catalogue files."
        ),
    )
    import_parser.add_argument(
        "root",
        type=Path,
        help="Existing catalogue root; collection folders are created below it.",
    )
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
        help="YAML collection configuration; its id names the destination collection.",
    )
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check the import without changing the catalogue.",
    )
    analysis_parser = subparsers.add_parser(
        "analysis",
        help="Run commands supplied by the installed CSFData analysis add-on.",
        description=(
            "Forward a command to the optional csfdata_analysis add-on. "
            "Install that package separately before using this command."
        ),
    )
    analysis_parser.add_argument(
        "arguments",
        nargs=argparse.REMAINDER,
        help="Analysis command and its arguments, for example: diagnostics.",
    )
    index_parser = subparsers.add_parser(
        "index-catalogue",
        help="Build or update the SQLite search index for a local catalogue.",
    )
    index_parser.add_argument(
        "root",
        type=Path,
        help="Existing catalogue root containing collections/.",
    )
    index_parser.add_argument(
        "--collection",
        help="Collection ID to update; omit to rebuild every collection.",
    )
    summary_parser = subparsers.add_parser(
        "catalogue-summary",
        help="Print indexed collection and parameter availability information.",
    )
    summary_parser.add_argument(
        "root",
        type=Path,
        help="Existing indexed catalogue root.",
    )
    summary_parser.add_argument(
        "--collection",
        help="Collection ID to summarize; omit to summarize every collection.",
    )
    missing_parser = subparsers.add_parser(
        "missing-combinations",
        help="Write declared but absent grid combinations to CSV.",
    )
    missing_parser.add_argument("root", type=Path, help="Existing indexed catalogue root.")
    missing_parser.add_argument(
        "--collection",
        required=True,
        help="Indexed collection ID that declares grid_axes.",
    )
    missing_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="CSV path to create or replace.",
    )
    import_lite_parser = subparsers.add_parser(
        "import-lite",
        help="Import one local or remote catalogue collection as a lite catalogue.",
    )
    import_lite_parser.add_argument(
        "source",
        help="Local catalogue path or remote HOST:/absolute/catalogue/path source.",
    )
    import_lite_parser.add_argument(
        "--collection",
        required=True,
        help="One collection ID to import into the lite catalogue.",
    )
    import_lite_parser.add_argument(
        "destination",
        type=Path,
        nargs="?",
        default=Path("."),
        help=(
            "Parent directory for the lite catalogue. Defaults to the current directory."
        ),
    )
    import_lite_parser.add_argument(
        "--root",
        default="catalogue",
        help="Lite catalogue root folder name below destination. Defaults to catalogue.",
    )
    import_lite_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing local lite files instead of copying only missing files.",
    )
    snapshots_parser = subparsers.add_parser(
        "list-snapshots",
        help="Select nearest raw snapshots and write a portable YAML manifest.",
    )
    snapshots_parser.add_argument(
        "root",
        type=Path,
        help="Indexed full catalogue or lite catalogue root.",
    )
    snapshots_parser.add_argument(
        "--collection",
        required=True,
        help="One indexed collection ID to inspect.",
    )
    snapshots_parser.add_argument(
        "--time",
        type=float,
        required=True,
        help="Target time in Myr, or multiplier when --normalization is used.",
    )
    snapshots_parser.add_argument(
        "--normalization",
        help="Optional Myr-valued configuration parameter used to normalize time.",
    )
    snapshots_parser.add_argument(
        "--filter",
        action="append",
        default=[],
        help="Repeatable NAME=VALUE or NAME=LOWER:UPPER parameter filter.",
    )
    snapshots_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New YAML snapshot manifest path.",
    )
    clear_parser = subparsers.add_parser(
        "clear",
        help="Remove locally cached data from a lite catalogue.",
    )
    clear_subparsers = clear_parser.add_subparsers(dest="clear_target", required=True)
    clear_snapshots_parser = clear_subparsers.add_parser(
        "snapshots",
        help="Remove all locally cached snapshot files from a lite catalogue.",
    )
    clear_snapshots_parser.add_argument(
        "root",
        type=Path,
        help="Lite catalogue root from which snapshots are removed.",
    )

    args = parser.parse_args(argv)
    if args.command == "validate":
        return validate_grid(args.root, args.report, parser=validate_parser)
    if args.command == "import":
        return import_collection(
            args.root,
            args.report,
            args.collection,
            parser=import_parser,
            dry_run=args.dry_run,
        )
    if args.command == "index-catalogue":
        return index_catalogue_command(args.root, args.collection, parser=index_parser)
    if args.command == "catalogue-summary":
        return catalogue_summary_command(args.root, args.collection, parser=summary_parser)
    if args.command == "missing-combinations":
        return missing_combinations_command(
            args.root,
            args.collection,
            args.output,
            parser=missing_parser,
        )
    if args.command == "import-lite":
        return import_lite_command(
            args.source,
            args.collection,
            args.destination,
            root_name=args.root,
            overwrite=args.overwrite,
            parser=import_lite_parser,
        )
    if args.command == "list-snapshots":
        return list_snapshots_command(
            args.root,
            args.collection,
            args.time,
            args.output,
            filters=args.filter,
            normalization=args.normalization,
            parser=snapshots_parser,
        )
    if args.command == "clear":
        return clear_snapshots_command(args.root, parser=clear_snapshots_parser)
    return run_analysis(args.arguments, parser=analysis_parser)


def import_lite_command(
    source_catalogue: Path | str,
    collection_id: str,
    destination: Path,
    root_name: str = "catalogue",
    overwrite: bool = False,
    parser: argparse.ArgumentParser | None = None,
) -> int:
    """Import one collection as a queryable lite catalogue.

    Args:
        source_catalogue: Local or remote full catalogue containing the collection.
        collection_id: ID of the one collection to import.
        destination: Parent directory for the lite catalogue root.
        root_name: Lite catalogue root folder name below ``destination``.
        overwrite: Whether existing local lite files may be replaced.
        parser: Optional CLI parser used to present filesystem errors.

    Returns:
        Zero after the lite catalogue and its registry are imported.

    Raises:
        OSError: If import files cannot be read or written and no parser is supplied.
        ValueError: If the source collection is invalid and no parser is supplied.
    """
    try:
        if (
            not root_name
            or Path(root_name).name != root_name
            or root_name in {".", ".."}
        ):
            raise ValueError("Lite catalogue name must be one safe directory name.")
        output_path = destination / root_name
        report = import_lite_collection(
            source_catalogue,
            collection_id,
            output_path,
            overwrite=overwrite,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        if parser is None:
            raise
        parser.error(str(error))
    print(f"Imported collection: {report.source.collection_id}")
    print(f"Simulations: {report.simulation_count}")
    print(f"Lite catalogue: {report.destination}")
    print(f"Source catalogue: {report.source.catalogue_root}")
    return 0


def list_snapshots_command(
    catalogue_root: Path,
    collection_id: str,
    time_myr: float,
    output_path: Path,
    filters: Sequence[str] = (),
    normalization: str | None = None,
    parser: argparse.ArgumentParser | None = None,
) -> int:
    """Select snapshots and write a transfer-ready YAML manifest.

    Args:
        catalogue_root: Indexed full or lite catalogue root.
        collection_id: One collection ID to inspect.
        time_myr: Physical target time in Myr, or normalized multiplier.
        output_path: New YAML manifest path to write.
        filters: Repeated ``NAME=VALUE`` or ``NAME=LOWER:UPPER`` filters.
        normalization: Optional Myr-valued parameter used to normalize time.
        parser: Optional CLI parser used to present selection errors.

    Returns:
        Zero after printing a summary and writing the manifest.

    Raises:
        FileNotFoundError: If the catalogue, registry, or lite source is absent
            and no parser is supplied.
        OSError: If a source file or manifest cannot be read or written and no
            parser is supplied.
        ValueError: If a filter, source, or simulation format is invalid and no
            parser is supplied.
    """
    try:
        parsed_filters: dict[str, str | float | bool | tuple[float | None, float | None]] = {}
        for filter_text in filters:
            if "=" not in filter_text:
                raise ValueError(f"Filter must use NAME=VALUE syntax: {filter_text}")
            name, value_text = filter_text.split("=", maxsplit=1)
            if not name or not value_text:
                raise ValueError(f"Filter must have a name and value: {filter_text}")
            if name in parsed_filters:
                raise ValueError(f"Filter may be specified only once: {name}")
            if ":" in value_text:
                lower_text, upper_text = value_text.split(":", maxsplit=1)
                lower = float(lower_text) if lower_text else None
                upper = float(upper_text) if upper_text else None
                if lower is not None and upper is not None and lower > upper:
                    raise ValueError(f"Range filter has a lower bound above its upper bound: {filter_text}")
                parsed_filters[name] = (lower, upper)
            elif value_text.lower() in {"true", "false"}:
                parsed_filters[name] = value_text.lower() == "true"
            else:
                try:
                    parsed_filters[name] = float(value_text)
                except ValueError:
                    parsed_filters[name] = value_text
        report = list_snapshots(
            catalogue_root,
            collection_id,
            time_myr,
            parsed_filters,
            normalization,
        )
        manifest_path = write_snapshot_manifest(report, output_path)
    except (FileExistsError, FileNotFoundError, OSError, ValueError) as error:
        if parser is None:
            raise
        parser.error(str(error))
    selected = tuple(selection for selection in report.selections if selection.issue is None)
    unmatched = tuple(selection for selection in report.selections if selection.issue is not None)
    print(f"Collection: {report.collection_id}")
    print(f"Requested time: {report.time_myr:g} Myr")
    if report.normalization is not None:
        print(f"Normalization: {report.normalization}")
    print(f"Matched simulations: {len(report.selections)}")
    print(f"Selected snapshots: {len(selected)}")
    print(f"Unmatched simulations: {len(unmatched)}")
    for selection in unmatched[:10]:
        print(f"  - {selection.simulation_id}: {selection.issue}")
    if len(unmatched) > 10:
        print(f"  ... {len(unmatched) - 10} additional unmatched simulations are in the manifest.")
    print(f"Manifest: {manifest_path}")
    return 0


def clear_snapshots_command(
    lite_catalogue: Path,
    parser: argparse.ArgumentParser | None = None,
) -> int:
    """Clear all cached snapshots from one lite catalogue.

    Args:
        lite_catalogue: Lite catalogue root from which snapshots are removed.
        parser: Optional CLI parser used to present clearing errors.

    Returns:
        Zero after deleting snapshot files and printing the reclaimed size.

    Raises:
        FileNotFoundError: If the lite collection is incomplete and no parser
            is supplied.
        OSError: If a snapshot cannot be deleted and no parser is supplied.
        ValueError: If the root is not a lite catalogue and no parser is supplied.
    """
    try:
        report = clear_snapshots(lite_catalogue)
    except (FileNotFoundError, OSError, ValueError) as error:
        if parser is None:
            raise
        parser.error(str(error))
    size = report.reclaimed_size_bytes
    if size < 1024:
        readable_size = f"{size} B"
    elif size < 1024**2:
        readable_size = f"{size / 1024:.1f} KiB"
    elif size < 1024**3:
        readable_size = f"{size / 1024**2:.1f} MiB"
    else:
        readable_size = f"{size / 1024**3:.1f} GiB"
    print(f"Lite catalogue: {report.lite_catalogue}")
    print(f"Deleted snapshots: {len(report.deleted_paths)}")
    print(f"Reclaimed size: {readable_size}")
    return 0


def run_analysis(
    arguments: Sequence[str],
    parser: argparse.ArgumentParser | None = None,
) -> int:
    """Run the default optional analysis add-on command-line interface.

    Args:
        arguments: Arguments to forward to the add-on, excluding
            ``csfdata analysis``.
        parser: Optional core CLI parser used to show a concise installation
            error. Omit it when calling this function from Python.

    Returns:
        int: Exit code returned by the analysis add-on.

    Raises:
        LookupError: If the add-on is unavailable and no ``parser`` is
            provided.
    """
    try:
        command: Callable[[Sequence[str] | None], int] = load_analysis("csfdata_analysis")
    except LookupError as error:
        message = (
            f"{error} Install the optional csfdata_analysis package to use "
            "the analysis command."
        )
        if parser is None:
            raise LookupError(message) from error
        parser.error(message)
    return command(arguments)


def index_catalogue_command(
    catalogue_root: Path,
    collection_id: str | None = None,
    parser: argparse.ArgumentParser | None = None,
) -> int:
    """Build or update the SQLite registry for a local catalogue.

    Args:
        catalogue_root: Existing catalogue root containing ``collections/``.
        collection_id: Optional collection ID to index. Omit it to rebuild the
            complete registry.
        parser: Optional CLI parser used to present indexing errors. Omit it
            when calling this function from Python.

    Returns:
        int: Zero after the registry has been updated.

    Raises:
        OSError: If catalogue files cannot be read or written and no ``parser``
            is provided.
        sqlite3.Error: If the registry cannot be created or updated and no
            ``parser`` is provided.
        ValueError: If catalogue records are inconsistent and no ``parser`` is
            provided.
    """
    try:
        report = index_catalogue(catalogue_root, collection_id)
    except (OSError, ValueError, sqlite3.Error) as error:
        if parser is None:
            raise
        parser.error(str(error))
    collections = ", ".join(report.collection_ids) or "none"
    print(f"Indexed collections: {collections}")
    print(f"Simulations: {report.simulation_count}")
    print(f"Parameters: {report.parameter_count}")
    print(f"Registry: {report.registry_path}")
    return 0


def catalogue_summary_command(
    catalogue_root: Path,
    collection_id: str | None = None,
    parser: argparse.ArgumentParser | None = None,
) -> int:
    """Print human-readable availability information from the catalogue index.

    Args:
        catalogue_root: Existing catalogue root containing ``registry.sqlite``.
        collection_id: Optional indexed collection ID to summarize.
        parser: Optional CLI parser used to present registry errors. Omit it
            when calling this function from Python.

    Returns:
        int: Zero after printing the summary.

    Raises:
        FileNotFoundError: If no registry exists and no ``parser`` is provided.
        ValueError: If the requested collection is not indexed and no ``parser``
            is provided.
        sqlite3.Error: If the registry cannot be read and no ``parser`` is
            provided.
    """
    try:
        print(summarize_catalogue(catalogue_root, collection_id))
    except (FileNotFoundError, ValueError, sqlite3.Error) as error:
        if parser is None:
            raise
        parser.error(str(error))
    return 0


def missing_combinations_command(
    catalogue_root: Path,
    collection_id: str,
    output_path: Path,
    parser: argparse.ArgumentParser | None = None,
) -> int:
    """Write missing declared grid combinations as a CSV file.

    Args:
        catalogue_root: Existing catalogue root containing ``registry.sqlite``.
        collection_id: Indexed collection ID that declares ``grid_axes``.
        output_path: CSV destination path. Existing files are replaced because
            this is a regenerated report.
        parser: Optional CLI parser used to present errors. Omit it when
            calling this function from Python.

    Returns:
        int: Zero after the CSV report has been written.

    Raises:
        FileNotFoundError: If the registry is absent and no ``parser`` is
            provided.
        ValueError: If the selected collection has no declared grid and no
            ``parser`` is provided.
        OSError: If the CSV cannot be written and no ``parser`` is provided.
        sqlite3.Error: If the registry cannot be read and no ``parser`` is
            provided.
    """
    try:
        combinations = missing_combinations(catalogue_root, collection_id)
        if combinations:
            fieldnames = tuple(combinations[0])
        else:
            collection = read_collection_configuration(
                catalogue_root / "collections" / collection_id / "collection.yaml"
            )
            fieldnames = tuple(name for name, _ in collection.grid_axes)
        with output_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(combinations)
    except (FileNotFoundError, OSError, ValueError, sqlite3.Error) as error:
        if parser is None:
            raise
        parser.error(str(error))
    print(f"Missing combinations: {len(combinations)}")
    print(f"Report: {output_path}")
    return 0


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
            show_progress=not dry_run,
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
