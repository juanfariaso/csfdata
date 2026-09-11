"""Staged local import of validated simulations into a catalogue collection."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil

from csfdata.adapters.base import SimulationAdapter
from csfdata.catalogue.collection import (
    CollectionConfiguration,
    read_collection_configuration,
)
from csfdata.catalogue.configuration import (
    SimulationConfiguration,
    read_simulation_configuration,
    write_simulation_configuration,
)
from csfdata.catalogue.metadata import (
    SimulationMetadata,
    read_simulation_metadata,
    write_simulation_metadata,
)
from csfdata.importer.manifest import ImportItem, ImportManifest


def import_manifest(
    manifest: ImportManifest,
    catalogue_root: Path,
    collection_path: Path,
    adapter: type[SimulationAdapter],
    dry_run: bool = False,
) -> tuple[Path, ...]:
    """Import one reviewed manifest into a local catalogue collection.

    Args:
        manifest: Reviewed source-to-destination simulation mapping.
        catalogue_root: Existing root directory of the local catalogue.
        collection_path: Source ``collection.yaml`` that defines import
            requirements for this collection.
        adapter: Adapter class used to inspect each source simulation.
        dry_run: Whether to stop after preflight without changing the catalogue.

    Returns:
        Final destination directories promoted during this import, in manifest
        item order.

    Raises:
        NotADirectoryError: If ``catalogue_root`` is not an existing directory.
        FileNotFoundError: If a source simulation or planned raw file is absent.
        FileExistsError: If the destination simulation, its retained staging
            directory, or destination collection configuration already conflicts.
        ValueError: If collection definitions disagree, a source is no longer
            recognizable, a required parameter is absent, or raw data include a
            symbolic link or a path outside the source simulation.
        OSError: If copying, writing, verification, or promotion fails.

    Notes:
        The validation report and manifest are trusted records, so this function
        does not rediscover the grid or run full source validation. It does
        re-read each source configuration to create canonical ``config.yaml``
        and checks the collection's required parameters. Each simulation is
        copied into retained staging before promotion; existing destinations are
        never overwritten. A dry run performs the same preflight checks but
        creates no catalogue files or directories.
    """
    if not catalogue_root.is_dir():
        raise NotADirectoryError(f"Catalogue root is not a directory: {catalogue_root}")

    collection = read_collection_configuration(collection_path)
    if manifest.collection_id != collection.collection_id:
        raise ValueError(
            "Manifest collection_id does not match collection configuration: "
            f"{manifest.collection_id} != {collection.collection_id}."
        )

    collection_root = catalogue_root / "collections" / collection.collection_id
    destination_collection_path = collection_root / "collection.yaml"
    if destination_collection_path.exists():
        if not destination_collection_path.is_file():
            raise FileExistsError(
                f"Destination collection configuration is not a file: "
                f"{destination_collection_path}"
            )
        if read_collection_configuration(destination_collection_path) != collection:
            raise ValueError(
                "Destination collection configuration differs from the supplied "
                f"configuration: {destination_collection_path}"
            )

    simulations_root = collection_root / "simulations"
    staging_root = collection_root / ".staging"
    prepared: list[tuple[ImportItem, SimulationConfiguration, tuple[Path, ...]]] = []

    # Preflight every item before creating catalogue files or copying raw data.
    for item in manifest.items:
        source_root = manifest.source_path(item)
        if not source_root.is_dir():
            raise FileNotFoundError(f"Source simulation is not a directory: {source_root}")
        source_adapter = adapter(source_root)
        if not source_adapter.is_simulation():
            raise ValueError(f"Source is no longer recognized as a simulation: {source_root}")

        configuration = source_adapter.prepare_configuration(collection)
        raw_paths = source_adapter.raw_data_paths()
        for raw_path in raw_paths:
            if raw_path.is_symlink():
                raise ValueError(f"Symbolic links are not supported in raw data: {raw_path}")
            if not raw_path.is_file():
                raise FileNotFoundError(f"Planned raw data file does not exist: {raw_path}")
            try:
                raw_path.relative_to(source_root)
            except ValueError as error:
                raise ValueError(
                    f"Raw data path is outside its source simulation: {raw_path}"
                ) from error

        destination_path = simulations_root / item.simulation_id
        staging_path = staging_root / item.simulation_id
        if destination_path.exists():
            raise FileExistsError(f"Destination simulation already exists: {destination_path}")
        if staging_path.exists():
            raise FileExistsError(f"Retained staging directory already exists: {staging_path}")
        prepared.append((item, configuration, raw_paths))

    if dry_run:
        return tuple(simulations_root / item.simulation_id for item, _, _ in prepared)

    collection_root.mkdir(parents=True, exist_ok=True)
    if not destination_collection_path.exists():
        # Preserve the reviewed collection definition inside the catalogue itself.
        shutil.copy2(collection_path, destination_collection_path)
    simulations_root.mkdir(exist_ok=True)
    staging_root.mkdir(exist_ok=True)

    destinations: list[Path] = []
    for item, configuration, raw_paths in prepared:
        source_root = manifest.source_path(item)
        staging_path = staging_root / item.simulation_id
        destination_path = simulations_root / item.simulation_id
        raw_root = staging_path / "raw"
        raw_root.mkdir(parents=True)

        # Preserve each approved source path below raw/ with its original layout.
        for raw_path in raw_paths:
            destination_raw_path = raw_root / raw_path.relative_to(source_root)
            destination_raw_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(raw_path, destination_raw_path)
            if destination_raw_path.stat().st_size != raw_path.stat().st_size:
                raise OSError(f"Copied file size does not match source: {raw_path}")

        write_simulation_configuration(configuration, staging_path / "config.yaml")
        metadata = SimulationMetadata(
            simulation_id=item.simulation_id,
            collection_id=manifest.collection_id,
            importer=collection.importer,
            source_hostname=manifest.source_hostname,
            source_root=manifest.source_root,
            source_relative_path=item.source_relative_path,
            imported_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            ),
        )
        write_simulation_metadata(metadata, staging_path / "metadata.yaml")
        (staging_path / "derived").mkdir()

        # Re-read generated files before promotion so malformed catalogue files never land.
        if read_simulation_configuration(staging_path / "config.yaml") != configuration:
            raise OSError(f"Copied configuration verification failed: {staging_path}")
        if read_simulation_metadata(staging_path / "metadata.yaml") != metadata:
            raise OSError(f"Copied metadata verification failed: {staging_path}")
        if destination_path.exists():
            raise FileExistsError(f"Destination simulation already exists: {destination_path}")
        staging_path.rename(destination_path)
        destinations.append(destination_path)

    return tuple(destinations)
