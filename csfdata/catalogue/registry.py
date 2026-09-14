"""SQLite indexing for fast catalogue simulation selection.

The registry is a rebuildable cache of catalogue ``metadata.yaml`` and
``config.yaml`` files. Those YAML files remain the human-readable source of
truth for simulation identity, provenance, and scientific parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from csfdata.catalogue.collection import read_collection_configuration
from csfdata.catalogue.configuration import read_simulation_configuration
from csfdata.catalogue.metadata import read_simulation_metadata


@dataclass(frozen=True)
class IndexReport:
    """Summary of one completed catalogue indexing operation.

    Args:
        catalogue_root: Root directory containing ``collections/``.
        registry_path: SQLite file created or updated by indexing.
        collection_ids: IDs of collections indexed during this operation.
        simulation_count: Number of simulations indexed during this operation.
        parameter_count: Number of known scientific parameters indexed during
            this operation.
    """

    catalogue_root: Path
    registry_path: Path
    collection_ids: tuple[str, ...]
    simulation_count: int
    parameter_count: int


def index_catalogue(
    catalogue_root: Path,
    collection_id: str | None = None,
) -> IndexReport:
    """Index one collection or every collection in a local catalogue.

    Args:
        catalogue_root: Existing catalogue root containing ``collections/``.
        collection_id: Optional collection ID to replace in the registry. When
            omitted, rebuild the registry from every collection on disk.

    Returns:
        Summary of the collections, simulations, and known parameters indexed.

    Raises:
        NotADirectoryError: If the catalogue root or its ``collections/``
            directory does not exist.
        ValueError: If a selected collection is absent, a simulation directory
            disagrees with its metadata, or an indexed parameter is unsupported.
        OSError: If a catalogue YAML file cannot be read or the registry cannot
            be created or updated.
        sqlite3.Error: If SQLite cannot create or update the registry.

    Notes:
        The function validates all selected YAML files before changing the
        database. It then replaces only the selected collection rows, or all
        rows for a full rebuild, in one SQLite transaction. Unknown and
        inapplicable parameters are deliberately not indexed because they have
        no scientific value to compare.
    """
    catalogue_root = catalogue_root.resolve()
    if not catalogue_root.is_dir():
        raise NotADirectoryError(f"Catalogue root is not a directory: {catalogue_root}")
    collections_root = catalogue_root / "collections"
    if not collections_root.is_dir():
        raise NotADirectoryError(f"Catalogue has no collections directory: {collections_root}")

    if collection_id is None:
        collection_roots = tuple(
            sorted(path for path in collections_root.iterdir() if path.is_dir())
        )
    else:
        collection_roots = (collections_root / collection_id,)
        if not collection_roots[0].is_dir():
            raise ValueError(f"Collection does not exist: {collection_id}")

    collection_rows: list[tuple[str, str, str]] = []
    simulation_rows: list[tuple[str, str, str, str]] = []
    parameter_rows: list[tuple[str, str, str, str, float | None, str | None, str | None, str]] = []

    for collection_root in collection_roots:
        collection = read_collection_configuration(collection_root / "collection.yaml")
        if collection.collection_id != collection_root.name:
            raise ValueError(
                "Collection directory name does not match collection.yaml id: "
                f"{collection_root.name} != {collection.collection_id}."
            )
        collection_rows.append(
            (
                collection.collection_id,
                collection.importer,
                str(collection_root.relative_to(catalogue_root)),
            )
        )

        simulations_root = collection_root / "simulations"
        if not simulations_root.is_dir():
            raise NotADirectoryError(
                f"Collection has no simulations directory: {simulations_root}"
            )
        for simulation_root in sorted(path for path in simulations_root.iterdir() if path.is_dir()):
            metadata = read_simulation_metadata(simulation_root / "metadata.yaml")
            if metadata.collection_id != collection.collection_id:
                raise ValueError(
                    f"Simulation metadata collection_id does not match {simulation_root}: "
                    f"{metadata.collection_id} != {collection.collection_id}."
                )
            if metadata.simulation_id != simulation_root.name:
                raise ValueError(
                    f"Simulation metadata simulation_id does not match directory: "
                    f"{metadata.simulation_id} != {simulation_root.name}."
                )
            configuration = read_simulation_configuration(simulation_root / "config.yaml")
            simulation_rows.append(
                (
                    collection.collection_id,
                    metadata.simulation_id,
                    str(simulation_root.relative_to(catalogue_root)),
                    metadata.imported_at,
                )
            )
            for section, parameters in (
                ("parameters", configuration.parameters),
                ("code_parameters", configuration.code_parameters),
            ):
                for parameter in parameters:
                    if not parameter.is_known:
                        continue
                    if isinstance(parameter.value, bool):
                        value_type = "boolean"
                        numeric_value = float(parameter.value)
                        text_value = None
                    elif isinstance(parameter.value, (int, float)):
                        value_type = "number"
                        numeric_value = float(parameter.value)
                        text_value = None
                    elif isinstance(parameter.value, str):
                        value_type = "text"
                        numeric_value = None
                        text_value = parameter.value
                    else:
                        raise ValueError(
                            f"Known parameter {parameter.name} has an unsupported value."
                        )
                    parameter_rows.append(
                        (
                            collection.collection_id,
                            metadata.simulation_id,
                            parameter.name,
                            value_type,
                            numeric_value,
                            text_value,
                            parameter.unit,
                            section,
                        )
                    )

    registry_path = catalogue_root / "registry.sqlite"
    with sqlite3.connect(registry_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS collections (
                collection_id TEXT PRIMARY KEY,
                importer TEXT NOT NULL,
                relative_path TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS simulations (
                collection_id TEXT NOT NULL,
                simulation_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                PRIMARY KEY (collection_id, simulation_id),
                FOREIGN KEY (collection_id) REFERENCES collections (collection_id)
            );
            CREATE TABLE IF NOT EXISTS parameter_values (
                collection_id TEXT NOT NULL,
                simulation_id TEXT NOT NULL,
                name TEXT NOT NULL,
                value_type TEXT NOT NULL,
                numeric_value REAL,
                text_value TEXT,
                unit TEXT,
                section TEXT NOT NULL,
                PRIMARY KEY (collection_id, simulation_id, name),
                FOREIGN KEY (collection_id, simulation_id)
                    REFERENCES simulations (collection_id, simulation_id)
            );
            CREATE INDEX IF NOT EXISTS parameter_numeric_lookup
                ON parameter_values (name, numeric_value, collection_id, simulation_id);
            CREATE INDEX IF NOT EXISTS parameter_text_lookup
                ON parameter_values (name, text_value, collection_id, simulation_id);
            """
        )
        indexed_collection_ids = tuple(row[0] for row in collection_rows)
        if collection_id is None:
            connection.execute("DELETE FROM parameter_values")
            connection.execute("DELETE FROM simulations")
            connection.execute("DELETE FROM collections")
        else:
            for indexed_collection_id in indexed_collection_ids:
                connection.execute(
                    "DELETE FROM parameter_values WHERE collection_id = ?",
                    (indexed_collection_id,),
                )
                connection.execute(
                    "DELETE FROM simulations WHERE collection_id = ?",
                    (indexed_collection_id,),
                )
                connection.execute(
                    "DELETE FROM collections WHERE collection_id = ?",
                    (indexed_collection_id,),
                )
        connection.executemany(
            "INSERT INTO collections (collection_id, importer, relative_path) VALUES (?, ?, ?)",
            collection_rows,
        )
        connection.executemany(
            """
            INSERT INTO simulations (collection_id, simulation_id, relative_path, imported_at)
            VALUES (?, ?, ?, ?)
            """,
            simulation_rows,
        )
        connection.executemany(
            """
            INSERT INTO parameter_values (
                collection_id, simulation_id, name, value_type, numeric_value,
                text_value, unit, section
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            parameter_rows,
        )

    return IndexReport(
        catalogue_root=catalogue_root,
        registry_path=registry_path,
        collection_ids=tuple(row[0] for row in collection_rows),
        simulation_count=len(simulation_rows),
        parameter_count=len(parameter_rows),
    )
