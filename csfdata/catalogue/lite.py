"""Create and inspect lightweight, collection-scoped catalogue copies."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import socket

import yaml

from csfdata.catalogue.registry import IndexReport, index_catalogue


@dataclass(frozen=True)
class LiteSource:
    """Provenance needed to read raw data for one lite collection.

    Args:
        catalogue_root: Absolute full-catalogue root that owns the raw data.
        hostname: Host where the source catalogue was exported.
        collection_id: The single collection represented by the lite catalogue.
        collection_sha256: SHA-256 digest of the exported ``collection.yaml``.
    """

    catalogue_root: Path
    hostname: str
    collection_id: str
    collection_sha256: str


@dataclass(frozen=True)
class LiteExportReport:
    """Summary of one completed lite-collection export.

    Args:
        destination: Created lite catalogue root.
        source: Recorded provenance of the original collection.
        simulation_count: Number of mirrored simulation metadata records.
        index_report: Registry report for the newly created lite catalogue.
    """

    destination: Path
    source: LiteSource
    simulation_count: int
    index_report: IndexReport


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of one regular file.

    Args:
        path: Existing file whose bytes are hashed.

    Returns:
        Lowercase hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export_lite_collection(
    source_catalogue: Path,
    collection_id: str,
    destination: Path,
) -> LiteExportReport:
    """Create a queryable, raw-data-free copy of one catalogue collection.

    Args:
        source_catalogue: Existing full catalogue containing the collection.
        collection_id: ID of the one collection to mirror.
        destination: New empty directory that will become the lite catalogue.

    Returns:
        Summary of the created lite catalogue and its source provenance.

    Raises:
        FileExistsError: If ``destination`` already exists.
        FileNotFoundError: If required collection files are absent.
        NotADirectoryError: If the source catalogue or collection is invalid.
        OSError: If required files cannot be copied or indexed.

    Notes:
        Only ``collection.yaml``, ``metadata.yaml``, and canonical
        ``config.yaml`` files are copied. Raw snapshots and existing derived
        products are deliberately excluded.
    """
    source_catalogue = source_catalogue.resolve()
    destination = destination.resolve()
    if not source_catalogue.is_dir():
        raise NotADirectoryError(f"Catalogue root is not a directory: {source_catalogue}")
    if destination.exists():
        raise FileExistsError(f"Lite catalogue destination already exists: {destination}")
    source_collection = source_catalogue / "collections" / collection_id
    source_simulations = source_collection / "simulations"
    collection_path = source_collection / "collection.yaml"
    if not source_collection.is_dir() or not source_simulations.is_dir():
        raise NotADirectoryError(f"Collection does not exist: {collection_id}")
    if not collection_path.is_file():
        raise FileNotFoundError(f"Collection configuration is missing: {collection_path}")

    source = LiteSource(
        catalogue_root=source_catalogue,
        hostname=socket.gethostname(),
        collection_id=collection_id,
        collection_sha256=file_sha256(collection_path),
    )
    destination_collection = destination / "collections" / collection_id
    destination_simulations = destination_collection / "simulations"
    destination_simulations.mkdir(parents=True)
    shutil.copy2(collection_path, destination_collection / "collection.yaml")

    simulation_count = 0
    for source_simulation in sorted(path for path in source_simulations.iterdir() if path.is_dir()):
        destination_simulation = destination_simulations / source_simulation.name
        destination_simulation.mkdir()
        for name in ("metadata.yaml", "config.yaml"):
            source_path = source_simulation / name
            if not source_path.is_file():
                raise FileNotFoundError(f"Simulation file is missing: {source_path}")
            shutil.copy2(source_path, destination_simulation / name)
        simulation_count += 1

    (destination / "lite.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source": {
                    "catalogue_root": str(source.catalogue_root),
                    "hostname": source.hostname,
                    "collection_id": source.collection_id,
                    "collection_sha256": source.collection_sha256,
                },
            },
            allow_unicode=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return LiteExportReport(destination, source, simulation_count, index_catalogue(destination))


def is_lite_catalogue(path: Path) -> bool:
    """Return whether a path is the root of a version-1 lite catalogue.

    Args:
        path: Candidate catalogue root.

    Returns:
        ``True`` when the root contains a ``lite.yaml`` manifest.
    """
    return (path / "lite.yaml").is_file()


def read_lite_source(lite_catalogue: Path) -> LiteSource:
    """Read the source provenance recorded in one lite catalogue.

    Args:
        lite_catalogue: Lite catalogue root containing ``lite.yaml``.

    Returns:
        Validated source catalogue provenance.

    Raises:
        FileNotFoundError: If the lite manifest is absent.
        ValueError: If the manifest has an unsupported or invalid schema.
    """
    manifest = lite_catalogue / "lite.yaml"
    with manifest.open(encoding="utf-8") as stream:
        contents = yaml.safe_load(stream)
    if not isinstance(contents, dict) or contents.get("schema_version") != 1:
        raise ValueError("Lite catalogue must use lite.yaml schema_version 1.")
    source = contents.get("source")
    if not isinstance(source, dict):
        raise ValueError("Lite catalogue must contain a source mapping.")
    root = source.get("catalogue_root")
    hostname = source.get("hostname")
    collection_id = source.get("collection_id")
    collection_sha256 = source.get("collection_sha256")
    if not all(isinstance(value, str) and value for value in (root, hostname, collection_id, collection_sha256)):
        raise ValueError("Lite catalogue source has an invalid required field.")
    source_root = Path(root)
    if not source_root.is_absolute():
        raise ValueError("Lite catalogue source catalogue_root must be absolute.")
    return LiteSource(source_root, hostname, collection_id, collection_sha256)
