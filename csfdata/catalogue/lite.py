"""Operate on catalogue roots marked as lightweight copies.

A lite catalogue uses the normal catalogue layout, but its ``lite.yaml`` file
records that it is a portable, collection-scoped copy. The marker stores the
full catalogue that owns the omitted raw snapshots. This module implements the
extra safety rules required by that mode: copy collection metadata and derived
data without ``raw/``, record provenance, and reject incompatible updates.

Lite is therefore a catalogue mode, not a separate data model. General
catalogue operations continue to work on a lite root in the usual way.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import socket
import subprocess

import yaml

from csfdata.catalogue.registry import IndexReport, index_catalogue


@dataclass(frozen=True)
class LiteSource:
    """Provenance needed to read raw data for one lite collection.

    Args:
        catalogue_root: Absolute full-catalogue root that owns the raw data.
        hostname: Host where the source catalogue is located.
        collection_id: The single collection represented by the lite catalogue.
        collection_sha256: SHA-256 digest of the source ``collection.yaml``.
    """

    catalogue_root: Path
    hostname: str
    collection_id: str
    collection_sha256: str


@dataclass(frozen=True)
class LiteImportReport:
    """Summary of one completed lite-collection import.

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


def import_lite_collection(
    source_catalogue: Path | str,
    collection_id: str,
    destination: Path,
    overwrite: bool = False,
) -> LiteImportReport:
    """Import one full-catalogue collection as a local lite catalogue.

    Args:
        source_catalogue: Local catalogue path or ``HOST:PATH`` remote source.
        collection_id: ID of the one collection to mirror.
        destination: New or compatible existing local lite catalogue root.
        overwrite: Whether existing local lite files may be replaced.

    Returns:
        Summary of the imported lite catalogue and its source provenance.

    Raises:
        FileExistsError: If ``destination`` is not a compatible lite catalogue.
        FileNotFoundError: If a required local source file is absent.
        NotADirectoryError: If a local source catalogue or collection is invalid.
        OSError: If rsync or local indexing fails.

    Notes:
        ``rsync`` transfers the collection while excluding every ``raw/``
        directory. This preserves metadata, canonical configurations, and
        derived products while never copying raw snapshots. Remote transfers
        use the caller's ordinary SSH credentials.
    """
    destination = destination.resolve()
    source_text = str(source_catalogue)
    remote_hostname: str | None = None
    # SSH-style sources are passed directly to rsync; local paths are checked
    # here first so obvious catalogue errors fail before a transfer starts.
    if ":" in source_text and not source_text.startswith("/"):
        remote_hostname, remote_root = source_text.split(":", maxsplit=1)
        if not remote_hostname or not remote_root.startswith("/"):
            raise ValueError("Remote source must use HOST:/absolute/catalogue/path syntax.")
        source_root = Path(remote_root)
        source_collection_argument = (
            f"{remote_hostname}:{source_root}/collections/{collection_id}/"
        )
    else:
        source_root = Path(source_catalogue).resolve()
        source_collection = source_root / "collections" / collection_id
        if not source_root.is_dir():
            raise NotADirectoryError(f"Catalogue root is not a directory: {source_root}")
        if not (source_collection / "simulations").is_dir():
            raise NotADirectoryError(f"Collection does not exist: {collection_id}")
        if not (source_collection / "collection.yaml").is_file():
            raise FileNotFoundError(
                f"Collection configuration is missing: {source_collection / 'collection.yaml'}"
            )
        source_collection_argument = f"{source_collection}/"
    if destination.exists() and not destination.is_dir():
        raise FileExistsError(f"Lite catalogue destination is not a directory: {destination}")
    if destination.exists() and any(destination.iterdir()):
        # An existing lite root may be resumed only when it represents exactly
        # the same original collection. This prevents mixed-source catalogues.
        if not is_lite_catalogue(destination):
            raise FileExistsError(f"Lite catalogue destination is not empty: {destination}")
        existing_source = read_lite_source(destination)
        if (
            existing_source.catalogue_root != source_root
            or existing_source.hostname != (remote_hostname or socket.gethostname())
            or existing_source.collection_id != collection_id
        ):
            raise ValueError("Existing lite catalogue has a different recorded source collection.")
    else:
        destination.mkdir(parents=True, exist_ok=True)
    destination_collection = destination / "collections" / collection_id
    destination_collection.mkdir(parents=True, exist_ok=True)
    # Retain catalogue metadata and derived products, but never bring the raw
    # snapshots into a lite copy. --partial makes interrupted transfers resumable.
    command = ["rsync", "-rt", "--partial", "--info=progress2", "--exclude=raw/"]
    if not overwrite:
        command.append("--ignore-existing")
    command.extend((source_collection_argument, f"{destination_collection}/"))
    subprocess.run(command, check=True)

    destination_collection_path = destination_collection / "collection.yaml"
    if not destination_collection_path.is_file():
        raise FileNotFoundError(
            f"Imported collection configuration is missing: {destination_collection_path}"
        )
    source = LiteSource(
        catalogue_root=source_root,
        hostname=remote_hostname or socket.gethostname(),
        collection_id=collection_id,
        collection_sha256=file_sha256(destination_collection_path),
    )
    if not (destination / "lite.yaml").exists():
        # Provenance lets analysis locate raw snapshots later and lets derived
        # results be checked before they are copied back to the full catalogue.
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
    index_report = index_catalogue(destination)
    return LiteImportReport(
        destination,
        source,
        index_report.simulation_count,
        index_report,
    )


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
