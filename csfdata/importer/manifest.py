"""In-memory mapping from validated source paths to local simulation IDs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from csfdata.importer.validation import ValidatedSource, validate_relative_simulation_path


@dataclass(frozen=True)
class ImportItem:
    """One source simulation selected for import into a destination collection.

    Args:
        simulation_id: Immutable identifier assigned in the destination
            collection.
        source_relative_path: Simulation path relative to the validated source
            grid root.

    Notes:
        This object represents exactly one simulation. It connects that
        simulation's approved source path with the permanent ID it will have
        in the destination collection.
    """

    simulation_id: str
    source_relative_path: Path

    def __post_init__(self) -> None:
        """Validate the item fields needed for unambiguous destination paths.

        Raises:
            ValueError: If the simulation ID is not one safe directory name or
                the source path is not a safe, non-empty path relative to the
                validated source root.
        """
        if not self.simulation_id:
            raise ValueError("simulation_id must not be empty.")
        simulation_path = Path(self.simulation_id)
        if (
            simulation_path.is_absolute()
            or simulation_path.name != self.simulation_id
            or self.simulation_id in {".", ".."}
        ):
            raise ValueError("simulation_id must be one safe directory name.")
        validate_relative_simulation_path(self.source_relative_path)


@dataclass(frozen=True)
class ImportManifest:
    """A complete, immutable import mapping from one source grid to one collection.

    Args:
        collection_id: Destination collection identifier.
        source_hostname: Hostname recorded by the validation report.
        source_root: Absolute root directory recorded by the validation report.
        items: Source simulations selected for this import.

    Notes:
        This object represents the whole proposed import, not one simulation.
        It records one source grid, one destination collection, and one
        ``ImportItem`` for every simulation selected for import. It neither
        reads source data nor creates destination files. The copy
        implementation will use this manifest after it has been reviewed.
    """

    collection_id: str
    source_hostname: str
    source_root: Path
    items: tuple[ImportItem, ...]

    def __post_init__(self) -> None:
        """Validate collection, source, and item uniqueness constraints.

        Raises:
            ValueError: If a required identifier is empty, the source root is
                relative, or items reuse a simulation ID or source path.
        """
        if not self.collection_id:
            raise ValueError("collection_id must not be empty.")
        if not self.source_hostname:
            raise ValueError("source_hostname must not be empty.")
        if not self.source_root.is_absolute():
            raise ValueError("source_root must be absolute.")

        simulation_ids = [item.simulation_id for item in self.items]
        if len(simulation_ids) != len(set(simulation_ids)):
            raise ValueError("Each import item must have a unique simulation_id.")

        source_paths = [item.source_relative_path for item in self.items]
        if len(source_paths) != len(set(source_paths)):
            raise ValueError("Each import item must have a unique source_relative_path.")

    def source_path(self, item: ImportItem) -> Path:
        """Return the absolute source path for one item in this manifest.

        Args:
            item: Item whose source directory is required.

        Returns:
            The item's source directory below ``source_root``.
        """
        return self.source_root / item.source_relative_path

    def destination_relative_path(self, item: ImportItem) -> Path:
        """Return the item's collection-relative destination directory.

        Args:
            item: Item whose destination directory is required.

        Returns:
            The path below a catalogue root where the item will be promoted.
        """
        return Path("collections") / self.collection_id / "simulations" / item.simulation_id


def create_import_manifest(
    validated_source: ValidatedSource,
    collection_id: str,
) -> ImportManifest:
    """Create a deterministic import manifest from approved simulation paths.

    Args:
        validated_source: Source grid and approved paths read from validation.
        collection_id: Identifier of the destination collection.

    Returns:
        One ``ImportManifest`` representing every approved source simulation
        assigned to ``collection_id``. Source paths are sorted alphabetically
        and IDs start at ``"0001"``. The minimum width grows automatically
        beyond four digits.

    Notes:
        The local importer creates this mapping in memory from a reviewed
        validation report. The simulation metadata written during import then
        records the permanent source-path-to-ID association.
    """
    paths = tuple(sorted(validated_source.valid_simulation_paths))
    width = max(4, len(str(len(paths))))
    items = tuple(
        ImportItem(
            simulation_id=f"{index:0{width}d}",
            source_relative_path=path,
        )
        for index, path in enumerate(paths, start=1)
    )
    return ImportManifest(
        collection_id=collection_id,
        source_hostname=validated_source.hostname,
        source_root=validated_source.root,
        items=items,
    )
