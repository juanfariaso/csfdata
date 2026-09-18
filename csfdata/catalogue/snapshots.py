"""Maintain collection snapshot inventories and select cached raw snapshots.

One ``snapshot-times.yaml`` file belongs to each collection. It records the
time, size, and relative path of every usable primary snapshot, allowing full
and lite catalogues to select snapshots without reopening raw output files.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import socket

import yaml

from csfdata.adapters.dcaf import DcafAdapter
from csfdata.catalogue.collection import read_collection_configuration
from csfdata.catalogue.configuration import read_simulation_configuration
from csfdata.catalogue.lite import file_sha256, is_lite_catalogue, read_lite_source
from csfdata.catalogue.registry import find_simulations


@dataclass(frozen=True)
class SnapshotTime:
    """One usable primary snapshot recorded in a collection inventory.

    Args:
        path: Path relative to the simulation root, normally below ``raw/``.
        time_myr: Exact stored model time in canonical Myr.
        size_bytes: Source snapshot size in bytes at inventory-refresh time.
    """

    path: Path
    time_myr: float
    size_bytes: int


@dataclass(frozen=True)
class SnapshotTimeInventory:
    """The durable snapshot-time mapping for one collection.

    Args:
        collection_id: Stable ID of the represented collection.
        collection_sha256: Digest of the matching ``collection.yaml``.
        snapshots: Usable snapshots grouped by simulation ID.
        issues: Snapshot-reading failures grouped by simulation ID.
    """

    collection_id: str
    collection_sha256: str
    snapshots: Mapping[str, tuple[SnapshotTime, ...]]
    issues: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class SnapshotTimeRefreshReport:
    """Summary of one collection snapshot-inventory refresh.

    Args:
        inventory_path: Written ``snapshot-times.yaml`` path.
        simulation_count: Number of indexed simulations inspected.
        snapshot_count: Number of usable snapshots recorded.
        issues: Failures grouped by simulation ID.
    """

    inventory_path: Path
    simulation_count: int
    snapshot_count: int
    issues: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class SnapshotSelection:
    """Snapshot-selection result for one catalogue simulation.

    Args:
        simulation_id: Stable ID of the selected simulation.
        target_time_myr: Requested physical time after optional normalization.
        snapshot_time_myr: Stored snapshot time, or ``None`` when unmatched.
        tolerance_myr: Adaptive allowed time difference, or ``None`` when it
            cannot be determined.
        source_paths: Required paths relative to the source catalogue root.
        source_size_bytes: Total expected source-file size from the inventory.
        issue: Reason that no snapshot was selected, or ``None`` on success.
    """

    simulation_id: str
    target_time_myr: float
    snapshot_time_myr: float | None
    tolerance_myr: float | None
    source_paths: tuple[Path, ...]
    source_size_bytes: int
    issue: str | None


@dataclass(frozen=True)
class SnapshotListReport:
    """Selection results and provenance for one collection snapshot request.

    Args:
        source_catalogue: Full catalogue recorded as the raw-data source.
        source_hostname: Host recorded for the source catalogue.
        collection_id: Collection from which simulations were selected.
        collection_sha256: Digest of the source ``collection.yaml``.
        time_myr: Requested physical time, or multiplier when normalized.
        normalization: Optional Myr-valued configuration parameter name.
        filters: Indexed parameter filters used to select simulations.
        selections: One result for every simulation matched by ``filters``.
    """

    source_catalogue: Path
    source_hostname: str
    collection_id: str
    collection_sha256: str
    time_myr: float
    normalization: str | None
    filters: Mapping[str, str | int | float | bool | tuple[float | None, float | None]]
    selections: tuple[SnapshotSelection, ...]


@dataclass(frozen=True)
class SnapshotClearReport:
    """Summary of snapshot files deleted from one lite catalogue.

    Args:
        lite_catalogue: Lite catalogue from which snapshots were removed.
        deleted_paths: Snapshot files removed by the operation.
        reclaimed_size_bytes: Total byte size of files removed.
    """

    lite_catalogue: Path
    deleted_paths: tuple[Path, ...]
    reclaimed_size_bytes: int


def refresh_snapshot_times(
    catalogue_root: Path | str,
    collection_id: str,
) -> SnapshotTimeRefreshReport:
    """Read one full collection's raw snapshots and write its inventory.

    Args:
        catalogue_root: Indexed full catalogue root containing the raw data.
        collection_id: One collection ID to inspect and refresh.

    Returns:
        The written inventory path, counts, and any per-simulation read issues.

    Raises:
        FileNotFoundError: If the collection definition is absent.
        ValueError: If the collection uses an unsupported importer.
        OSError: If inventory data cannot be read or written.

    Notes:
        The inventory is always written, including usable entries from a
        partially unreadable collection. Callers should treat a non-empty
        ``issues`` mapping as an incomplete refresh.
    """
    root = Path(catalogue_root).resolve()
    collection_root = root / "collections" / collection_id
    collection_path = collection_root / "collection.yaml"
    if not collection_path.is_file():
        raise FileNotFoundError(f"Collection configuration is missing: {collection_path}")
    collection = read_collection_configuration(collection_path)
    if collection.importer != "dcaf":
        raise ValueError(f"Unsupported catalogue importer: {collection.importer}")

    snapshots: dict[str, tuple[SnapshotTime, ...]] = {}
    issues: dict[str, tuple[str, ...]] = {}
    simulations = find_simulations(root, collection_id)
    for simulation in simulations:
        adapter = DcafAdapter(simulation.path / "raw")
        try:
            times = adapter.snapshot_times()
            records = tuple(
                SnapshotTime(
                    Path("raw") / relative_path,
                    time_myr,
                    (adapter.run_root / relative_path).stat().st_size,
                )
                for relative_path, time_myr in times.items()
            )
        except (OSError, ValueError) as error:
            issues[simulation.simulation_id] = (str(error),)
            continue
        snapshots[simulation.simulation_id] = records

    inventory = SnapshotTimeInventory(
        collection_id,
        file_sha256(collection_path),
        snapshots,
        issues,
    )
    inventory_path = collection_root / "snapshot-times.yaml"
    inventory_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "collection_id": inventory.collection_id,
                "collection_sha256": inventory.collection_sha256,
                "summary": {
                    "simulations": len(simulations),
                    "snapshots": sum(len(records) for records in snapshots.values()),
                    "simulations_with_issues": len(issues),
                },
                "snapshot_times": {
                    simulation_id: [
                        {
                            "path": str(record.path),
                            "time_myr": record.time_myr,
                            "size_bytes": record.size_bytes,
                        }
                        for record in records
                    ]
                    for simulation_id, records in snapshots.items()
                },
                "issues": {
                    simulation_id: list(messages)
                    for simulation_id, messages in issues.items()
                },
            },
            allow_unicode=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return SnapshotTimeRefreshReport(
        inventory_path,
        len(simulations),
        sum(len(records) for records in snapshots.values()),
        issues,
    )


def read_snapshot_times(
    catalogue_root: Path | str,
    collection_id: str,
) -> SnapshotTimeInventory:
    """Read and validate one collection's durable snapshot inventory.

    Args:
        catalogue_root: Full or lite catalogue root containing the collection.
        collection_id: Expected collection ID.

    Returns:
        Parsed snapshot paths, times, sizes, and refresh issues.

    Raises:
        FileNotFoundError: If the inventory or collection definition is absent.
        ValueError: If the inventory schema, identity, or contents are invalid.
    """
    root = Path(catalogue_root).resolve()
    collection_root = root / "collections" / collection_id
    collection_path = collection_root / "collection.yaml"
    inventory_path = collection_root / "snapshot-times.yaml"
    if not collection_path.is_file():
        raise FileNotFoundError(f"Collection configuration is missing: {collection_path}")
    with inventory_path.open(encoding="utf-8") as stream:
        contents = yaml.safe_load(stream)
    if not isinstance(contents, dict) or contents.get("schema_version") != 1:
        raise ValueError("Snapshot inventory must use schema_version 1.")
    collection_sha256 = contents.get("collection_sha256")
    if contents.get("collection_id") != collection_id or not isinstance(collection_sha256, str):
        raise ValueError("Snapshot inventory has an invalid collection identity.")
    if collection_sha256 != file_sha256(collection_path):
        raise ValueError("Snapshot inventory does not match collection.yaml; refresh it first.")
    stored_snapshots = contents.get("snapshot_times")
    stored_issues = contents.get("issues")
    if not isinstance(stored_snapshots, dict) or not isinstance(stored_issues, dict):
        raise ValueError("Snapshot inventory must contain snapshot_times and issues mappings.")

    snapshots: dict[str, tuple[SnapshotTime, ...]] = {}
    for simulation_id, values in stored_snapshots.items():
        if not isinstance(simulation_id, str) or not isinstance(values, list):
            raise ValueError("Snapshot inventory has an invalid snapshot_times entry.")
        records: list[SnapshotTime] = []
        for value in values:
            if not isinstance(value, dict):
                raise ValueError("Snapshot inventory has an invalid snapshot record.")
            path = value.get("path")
            time_myr = value.get("time_myr")
            size_bytes = value.get("size_bytes")
            if (
                not isinstance(path, str)
                or not path.startswith("raw/")
                or Path(path).is_absolute()
                or ".." in Path(path).parts
                or not isinstance(time_myr, (int, float))
                or isinstance(time_myr, bool)
                or not isinstance(size_bytes, int)
                or isinstance(size_bytes, bool)
                or size_bytes < 0
            ):
                raise ValueError("Snapshot inventory has an invalid snapshot record.")
            records.append(SnapshotTime(Path(path), float(time_myr), size_bytes))
        snapshots[simulation_id] = tuple(records)
    issues: dict[str, tuple[str, ...]] = {}
    for simulation_id, messages in stored_issues.items():
        if (
            not isinstance(simulation_id, str)
            or not isinstance(messages, list)
            or not all(isinstance(message, str) for message in messages)
        ):
            raise ValueError("Snapshot inventory has an invalid issues entry.")
        issues[simulation_id] = tuple(messages)
    return SnapshotTimeInventory(collection_id, collection_sha256, snapshots, issues)


def list_snapshots(
    catalogue_root: Path | str,
    collection_id: str,
    time_myr: float,
    filters: Mapping[
        str,
        str | int | float | bool | tuple[float | None, float | None],
    ] | None = None,
    normalization: str | None = None,
) -> SnapshotListReport:
    """Select the closest valid inventory snapshot for every filtered simulation.

    Args:
        catalogue_root: Indexed full or lite catalogue root.
        collection_id: One collection ID to inspect.
        time_myr: Physical target time in Myr, or multiplier when normalized.
        filters: Exact or inclusive-range indexed configuration filters.
        normalization: Optional known canonical configuration parameter in Myr.

    Returns:
        Provenance plus one selected or unmatched result per filtered simulation.

    Raises:
        FileNotFoundError: If the catalogue, registry, or inventory is absent.
        ValueError: If the collection or inventory is incompatible.
    """
    selection_catalogue = Path(catalogue_root).resolve()
    source_catalogue = selection_catalogue
    source_hostname = socket.gethostname()
    if is_lite_catalogue(selection_catalogue):
        source = read_lite_source(selection_catalogue)
        if source.collection_id != collection_id:
            raise ValueError("Lite catalogue does not contain the requested collection.")
        source_catalogue, source_hostname = source.catalogue_root, source.hostname
    inventory = read_snapshot_times(selection_catalogue, collection_id)
    simulations = find_simulations(selection_catalogue, collection_id, filters)
    selections: list[SnapshotSelection] = []
    for simulation in simulations:
        target_time = float(time_myr)
        if normalization is not None:
            parameter = read_simulation_configuration(
                simulation.path / "config.yaml"
            ).parameter(normalization)
            if parameter is None or not parameter.is_known or parameter.unit != "Myr":
                selections.append(
                    SnapshotSelection(
                        simulation.simulation_id,
                        target_time,
                        None,
                        None,
                        (),
                        0,
                        f"Missing known Myr normalization parameter: {normalization}",
                    )
                )
                continue
            target_time *= float(parameter.value)
        if simulation.simulation_id in inventory.issues:
            selections.append(
                SnapshotSelection(
                    simulation.simulation_id,
                    target_time,
                    None,
                    None,
                    (),
                    0,
                    "; ".join(inventory.issues[simulation.simulation_id]),
                )
            )
            continue
        records = tuple(
            sorted(
                inventory.snapshots.get(simulation.simulation_id, ()),
                key=lambda record: record.time_myr,
            )
        )
        if not records:
            selections.append(
                SnapshotSelection(
                    simulation.simulation_id,
                    target_time,
                    None,
                    None,
                    (),
                    0,
                    "No readable snapshots are recorded in the inventory.",
                )
            )
            continue
        selected_index = min(
            range(len(records)),
            key=lambda index: abs(records[index].time_myr - target_time),
        )
        selected = records[selected_index]
        if len(records) == 1:
            tolerance = 0.0
        elif target_time < selected.time_myr and selected_index > 0:
            tolerance = (selected.time_myr - records[selected_index - 1].time_myr) / 2.0
        elif target_time > selected.time_myr and selected_index < len(records) - 1:
            tolerance = (records[selected_index + 1].time_myr - selected.time_myr) / 2.0
        elif selected_index == 0:
            tolerance = (records[1].time_myr - selected.time_myr) / 2.0
        else:
            tolerance = (selected.time_myr - records[selected_index - 1].time_myr) / 2.0
        if abs(selected.time_myr - target_time) > tolerance:
            selections.append(
                SnapshotSelection(
                    simulation.simulation_id,
                    target_time,
                    None,
                    tolerance,
                    (),
                    0,
                    "No snapshot is within the adaptive time tolerance.",
                )
            )
            continue
        source_path = (
            Path("collections")
            / collection_id
            / "simulations"
            / simulation.simulation_id
            / selected.path
        )
        selections.append(
            SnapshotSelection(
                simulation.simulation_id,
                target_time,
                selected.time_myr,
                tolerance,
                (source_path,),
                selected.size_bytes,
                None,
            )
        )
    return SnapshotListReport(
        source_catalogue,
        source_hostname,
        collection_id,
        inventory.collection_sha256,
        float(time_myr),
        normalization,
        dict(filters or {}),
        tuple(selections),
    )


def write_snapshot_manifest(report: SnapshotListReport, path: Path | str) -> Path:
    """Write a portable YAML manifest for one snapshot-selection report.

    Args:
        report: Results returned by ``list_snapshots``.
        path: New YAML path to create.

    Returns:
        Absolute path to the created manifest.

    Raises:
        FileExistsError: If the requested manifest path already exists.
    """
    manifest_path = Path(path).resolve()
    if manifest_path.exists():
        raise FileExistsError(f"Snapshot manifest already exists: {manifest_path}")
    selected: list[dict[str, object]] = []
    unmatched: list[dict[str, object]] = []
    for selection in report.selections:
        if selection.issue is not None:
            unmatched.append(
                {
                    "simulation_id": selection.simulation_id,
                    "target_time_myr": selection.target_time_myr,
                    "tolerance_myr": selection.tolerance_myr,
                    "issue": selection.issue,
                }
            )
            continue
        selected.append(
            {
                "simulation_id": selection.simulation_id,
                "target_time_myr": selection.target_time_myr,
                "snapshot_time_myr": selection.snapshot_time_myr,
                "time_offset_myr": selection.snapshot_time_myr
                - selection.target_time_myr,
                "tolerance_myr": selection.tolerance_myr,
                "source_paths": [
                    str(source_path) for source_path in selection.source_paths
                ],
            }
        )
    total_selected_size_bytes = sum(selection.source_size_bytes for selection in report.selections)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source": {
                    "catalogue_root": str(report.source_catalogue),
                    "hostname": report.source_hostname,
                    "collection_id": report.collection_id,
                    "collection_sha256": report.collection_sha256,
                },
                "selection": {
                    "time_myr": report.time_myr,
                    "normalization": report.normalization,
                    "method": "nearest_with_adaptive_tolerance",
                    "filters": dict(report.filters),
                },
                "summary": {
                    "matched_simulations": len(report.selections),
                    "selected_snapshots": len(selected),
                    "unmatched_simulations": len(unmatched),
                },
                "selected_snapshots": selected,
                "unmatched_simulations": unmatched,
                "total_selected_size": (
                    f"{total_selected_size_bytes} B"
                    if total_selected_size_bytes < 1024
                    else f"{total_selected_size_bytes / 1024:.1f} KiB"
                    if total_selected_size_bytes < 1024**2
                    else f"{total_selected_size_bytes / 1024**2:.1f} MiB"
                    if total_selected_size_bytes < 1024**3
                    else f"{total_selected_size_bytes / 1024**3:.1f} GiB"
                ),
            },
            allow_unicode=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return manifest_path


def clear_snapshots(lite_catalogue: Path | str) -> SnapshotClearReport:
    """Remove every inventory-recorded snapshot file from a lite catalogue.

    Args:
        lite_catalogue: Root of the lite catalogue to clear.

    Returns:
        Paths removed and their total reclaimed size in bytes.

    Raises:
        ValueError: If the target is not a lite catalogue.
        FileNotFoundError: If the lite collection definition or inventory is absent.
        OSError: If a snapshot cannot be inspected or removed.

    Notes:
        This is intentionally non-interactive. It preserves metadata, canonical
        configuration, derived products, and raw support files such as
        ``background_gas*.dat``.
    """
    lite_root = Path(lite_catalogue).resolve()
    if not is_lite_catalogue(lite_root):
        raise ValueError(f"Snapshots may be cleared only from a lite catalogue: {lite_root}")
    source = read_lite_source(lite_root)
    inventory = read_snapshot_times(lite_root, source.collection_id)
    collection_root = lite_root / "collections" / source.collection_id
    deleted_paths: list[Path] = []
    reclaimed_size_bytes = 0
    for simulation_id, records in inventory.snapshots.items():
        for record in records:
            snapshot_path = collection_root / "simulations" / simulation_id / record.path
            if not snapshot_path.is_file():
                continue
            reclaimed_size_bytes += snapshot_path.stat().st_size
            snapshot_path.unlink()
            deleted_paths.append(snapshot_path)
    return SnapshotClearReport(lite_root, tuple(deleted_paths), reclaimed_size_bytes)
