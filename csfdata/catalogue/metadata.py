"""Identity and provenance metadata for one imported simulation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from csfdata.importer.validation import validate_relative_simulation_path


@dataclass(frozen=True)
class SimulationMetadata:
    """Version-1 identity and provenance metadata for one simulation.

    Args:
        simulation_id: Collection-local permanent simulation identifier.
        collection_id: Identifier of the destination collection.
        importer: Name of the adapter used to import the simulation.
        source_hostname: Hostname recorded when the source grid was validated.
        source_root: Absolute source-grid root recorded during validation.
        source_relative_path: Simulation path below ``source_root``.
        imported_at: UTC import timestamp in ISO 8601 ``Z`` notation.

    Notes:
        This object records identity and provenance, not scientific parameters.
        Those belong in the simulation's top-level ``config.yaml``. A hostname
        is informative provenance only and is not a stable source identity.
    """

    simulation_id: str
    collection_id: str
    importer: str
    source_hostname: str
    source_root: Path
    source_relative_path: Path
    imported_at: str

    def __post_init__(self) -> None:
        """Validate the required identity and provenance fields.

        Raises:
            ValueError: If a required field is empty, the source root is not
                absolute, or the source path is unsafe.
        """
        for field_name, value in (
            ("simulation_id", self.simulation_id),
            ("collection_id", self.collection_id),
            ("importer", self.importer),
            ("source_hostname", self.source_hostname),
            ("imported_at", self.imported_at),
        ):
            if not value:
                raise ValueError(f"{field_name} must not be empty.")
        if not self.source_root.is_absolute():
            raise ValueError("source_root must be absolute.")
        validate_relative_simulation_path(self.source_relative_path)


def write_simulation_metadata(metadata: SimulationMetadata, path: Path) -> None:
    """Write version-1 simulation metadata as YAML.

    Args:
        metadata: Identity and provenance metadata to save.
        path: Destination ``metadata.yaml`` path. Its parent must exist.

    Raises:
        OSError: If the metadata cannot be written.
    """
    contents = {
        "schema_version": 1,
        "simulation_id": metadata.simulation_id,
        "collection_id": metadata.collection_id,
        "importer": metadata.importer,
        "source": {
            "hostname": metadata.source_hostname,
            "root": str(metadata.source_root),
            "relative_path": str(metadata.source_relative_path),
        },
        "imported_at": metadata.imported_at,
    }
    path.write_text(
        yaml.safe_dump(contents, allow_unicode=False, sort_keys=False),
        encoding="utf-8",
    )


def read_simulation_metadata(path: Path) -> SimulationMetadata:
    """Read version-1 simulation metadata from YAML.

    Args:
        path: ``metadata.yaml`` path to read.

    Returns:
        Validated identity and provenance metadata.

    Raises:
        FileNotFoundError: If the metadata file does not exist.
        OSError: If the metadata cannot be read.
        ValueError: If the YAML contents do not follow version 1 of the schema.
        yaml.YAMLError: If the metadata is not valid YAML.
    """
    with path.open(encoding="utf-8") as stream:
        contents = yaml.safe_load(stream)
    if not isinstance(contents, dict):
        raise ValueError("Simulation metadata must contain a YAML mapping.")
    if contents.get("schema_version") != 1:
        raise ValueError("Simulation metadata must use schema_version 1.")

    simulation_id = contents.get("simulation_id")
    collection_id = contents.get("collection_id")
    importer = contents.get("importer")
    imported_at = contents.get("imported_at")
    if not all(
        isinstance(value, str) and value
        for value in (simulation_id, collection_id, importer, imported_at)
    ):
        raise ValueError("Simulation metadata has an invalid required field.")

    source = contents.get("source")
    if not isinstance(source, dict):
        raise ValueError("Simulation metadata must contain a source mapping.")
    hostname = source.get("hostname")
    root = source.get("root")
    relative_path = source.get("relative_path")
    if not all(
        isinstance(value, str) and value for value in (hostname, root, relative_path)
    ):
        raise ValueError("Simulation metadata source has an invalid required field.")

    return SimulationMetadata(
        simulation_id=simulation_id,
        collection_id=collection_id,
        importer=importer,
        source_hostname=hostname,
        source_root=Path(root),
        source_relative_path=Path(relative_path),
        imported_at=imported_at,
    )
