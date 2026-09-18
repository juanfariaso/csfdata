"""Select raw simulation snapshots and write portable selection manifests.

Selection is deliberately separate from transfer. This module inspects raw
data that are accessible from a full catalogue or a locally mounted lite
catalogue source, then records exact source-relative paths for a later import.
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
class SnapshotSelection:
    """Snapshot-selection result for one catalogue simulation.

    Args:
        simulation_id: Stable ID of the selected simulation.
        target_time_myr: Requested physical time after optional normalization.
        snapshot_time_myr: Stored snapshot time, or ``None`` when unmatched.
        tolerance_myr: Adaptive allowed time difference, or ``None`` when it
            cannot be determined.
        source_paths: Required absolute source files for the selected snapshot.
        issue: Reason that no snapshot was selected, or ``None`` on success.
    """

    simulation_id: str
    target_time_myr: float
    snapshot_time_myr: float | None
    tolerance_myr: float | None
    source_paths: tuple[Path, ...]
    issue: str | None


@dataclass(frozen=True)
class SnapshotListReport:
    """Selection results and provenance for one collection snapshot request.

    Args:
        source_catalogue: Full catalogue that owns the inspected raw files.
        source_hostname: Host recorded for the source catalogue.
        collection_id: Collection from which simulations were selected.
        collection_sha256: Digest of the source ``collection.yaml``.
        time_myr: Requested physical time, or dimensionless multiplier when
            ``normalization`` is provided.
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


def list_snapshots(
    catalogue_root: Path | str,
    collection_id: str,
    time_myr: float,
    filters: Mapping[str, str | int | float | bool | tuple[float | None, float | None]] | None = None,
    normalization: str | None = None,
) -> SnapshotListReport:
    """Select the closest valid snapshot for every filtered simulation.

    Args:
        catalogue_root: Indexed full catalogue or lite catalogue root.
        collection_id: One collection ID to inspect.
        time_myr: Physical target time in Myr, or a dimensionless multiplier
            when ``normalization`` is supplied.
        filters: Exact or inclusive-range indexed configuration filters.
        normalization: Optional known canonical configuration parameter in Myr.

    Returns:
        Provenance plus one selected or unmatched result per filtered simulation.

    Raises:
        FileNotFoundError: If the catalogue is unindexed or a lite source is
            not locally accessible.
        ValueError: If the collection is incompatible with a lite catalogue or
            uses an unsupported simulation adapter.

    Notes:
        A stored snapshot is selected only when its distance from the target is
        at most half the local output interval toward the target. This gives an
        adaptive tolerance for irregular output cadence. A single snapshot can
        match only an exact requested time.
    """
    selection_catalogue = Path(catalogue_root).resolve()
    source_catalogue = selection_catalogue
    source_hostname = socket.gethostname()
    if is_lite_catalogue(selection_catalogue):
        source = read_lite_source(selection_catalogue)
        if source.collection_id != collection_id:
            raise ValueError("Lite catalogue does not contain the requested collection.")
        source_catalogue = source.catalogue_root
        source_hostname = source.hostname
        source_collection = source_catalogue / "collections" / collection_id
        if not source_collection.is_dir():
            raise FileNotFoundError(f"Lite source collection is unavailable: {source_collection}")
        if file_sha256(source_collection / "collection.yaml") != source.collection_sha256:
            raise ValueError("Lite source collection configuration has changed.")

    collection_path = source_catalogue / "collections" / collection_id / "collection.yaml"
    if not collection_path.is_file():
        raise FileNotFoundError(f"Collection configuration is missing: {collection_path}")
    simulations = find_simulations(selection_catalogue, collection_id, filters)
    selections: list[SnapshotSelection] = []
    for simulation in simulations:
        target_time = float(time_myr)
        if normalization is not None:
            parameter = read_simulation_configuration(simulation.path / "config.yaml").parameter(
                normalization
            )
            if parameter is None or not parameter.is_known or parameter.unit != "Myr":
                selections.append(
                    SnapshotSelection(
                        simulation.simulation_id,
                        target_time,
                        None,
                        None,
                        (),
                        f"Missing known Myr normalization parameter: {normalization}",
                    )
                )
                continue
            target_time *= float(parameter.value)
        if simulation.importer != "dcaf":
            raise ValueError(f"Unsupported catalogue importer: {simulation.importer}")

        source_simulation = (
            source_catalogue / "collections" / collection_id / "simulations" / simulation.simulation_id
        )
        adapter = DcafAdapter(source_simulation / "raw")
        snapshot_records = sorted(
            (
                (snapshot_time, snapshot_path)
                for snapshot_path in adapter.snapshot_paths()
                if (snapshot_time := adapter.snapshot_time(snapshot_path)) is not None
            ),
            key=lambda record: (record[0], str(record[1])),
        )
        if not snapshot_records:
            selections.append(
                SnapshotSelection(
                    simulation.simulation_id,
                    target_time,
                    None,
                    None,
                    (),
                    "No readable snapshots are available.",
                )
            )
            continue

        selected_index = min(
            range(len(snapshot_records)),
            key=lambda index: abs(snapshot_records[index][0] - target_time),
        )
        selected_time, selected_path = snapshot_records[selected_index]
        if len(snapshot_records) == 1:
            tolerance = 0.0
        elif target_time < selected_time and selected_index > 0:
            tolerance = (selected_time - snapshot_records[selected_index - 1][0]) / 2.0
        elif target_time > selected_time and selected_index < len(snapshot_records) - 1:
            tolerance = (snapshot_records[selected_index + 1][0] - selected_time) / 2.0
        elif selected_index == 0:
            tolerance = (snapshot_records[1][0] - selected_time) / 2.0
        else:
            tolerance = (selected_time - snapshot_records[selected_index - 1][0]) / 2.0

        if abs(selected_time - target_time) > tolerance:
            selections.append(
                SnapshotSelection(
                    simulation.simulation_id,
                    target_time,
                    None,
                    tolerance,
                    (),
                    "No snapshot is within the adaptive time tolerance.",
                )
            )
            continue
        selections.append(
            SnapshotSelection(
                simulation.simulation_id,
                target_time,
                selected_time,
                tolerance,
                (selected_path,),
                None,
            )
        )

    return SnapshotListReport(
        source_catalogue,
        source_hostname,
        collection_id,
        file_sha256(collection_path),
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
        ValueError: If a selected source path is outside the source catalogue.
    """
    manifest_path = Path(path).resolve()
    if manifest_path.exists():
        raise FileExistsError(f"Snapshot manifest already exists: {manifest_path}")
    selected: list[dict[str, object]] = []
    unmatched: list[dict[str, object]] = []
    total_selected_size_bytes = 0
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
        try:
            paths = [str(source_path.relative_to(report.source_catalogue)) for source_path in selection.source_paths]
        except ValueError as error:
            raise ValueError(f"Selected file is outside the source catalogue: {selection.source_paths}") from error
        selected.append(
            {
                "simulation_id": selection.simulation_id,
                "target_time_myr": selection.target_time_myr,
                "snapshot_time_myr": selection.snapshot_time_myr,
                "time_offset_myr": selection.snapshot_time_myr - selection.target_time_myr,
                "tolerance_myr": selection.tolerance_myr,
                "source_paths": paths,
            }
        )
        total_selected_size_bytes += sum(source_path.stat().st_size for source_path in selection.source_paths)
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
    """Remove all adapter-recognized snapshot files from a lite catalogue.

    Args:
        lite_catalogue: Root of the lite catalogue to clear.

    Returns:
        Paths removed and their total reclaimed size in bytes.

    Raises:
        ValueError: If the target is not a lite catalogue or uses an unsupported
            simulation format.
        FileNotFoundError: If the lite collection definition is absent.
        OSError: If a snapshot cannot be inspected or removed.

    Notes:
        This operation is intentionally non-interactive. It preserves all
        metadata, canonical configuration, derived products, and non-snapshot
        raw files. The ``lite.yaml`` check prevents use on a full catalogue.
    """
    lite_root = Path(lite_catalogue).resolve()
    if not is_lite_catalogue(lite_root):
        raise ValueError(f"Snapshots may be cleared only from a lite catalogue: {lite_root}")
    source = read_lite_source(lite_root)
    collection_path = lite_root / "collections" / source.collection_id / "collection.yaml"
    collection = read_collection_configuration(collection_path)
    if collection.importer != "dcaf":
        raise ValueError(f"Unsupported catalogue importer: {collection.importer}")
    simulations_root = collection_path.parent / "simulations"
    if not simulations_root.is_dir():
        raise FileNotFoundError(f"Lite collection has no simulations directory: {simulations_root}")

    deleted_paths: list[Path] = []
    reclaimed_size_bytes = 0
    for simulation_path in sorted(path for path in simulations_root.iterdir() if path.is_dir()):
        adapter = DcafAdapter(simulation_path / "raw")
        for snapshot_path in adapter.snapshot_paths():
            reclaimed_size_bytes += snapshot_path.stat().st_size
            snapshot_path.unlink()
            deleted_paths.append(snapshot_path)
    return SnapshotClearReport(lite_root, tuple(deleted_paths), reclaimed_size_bytes)
