"""SQLite indexing for fast catalogue simulation selection.

The registry is a rebuildable cache of catalogue ``metadata.yaml`` and
``config.yaml`` files. Those YAML files remain the human-readable source of
truth for simulation identity, provenance, and scientific parameters.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import product
from math import prod
from pathlib import Path
import h5py
import json
import shutil
import sqlite3
import statistics
import textwrap

from csfdata.catalogue.collection import read_collection_configuration
from csfdata.catalogue.configuration import read_simulation_configuration
from csfdata.catalogue.diagnostics import (
    collection_diagnostics_path,
    read_collection_diagnostics,
    read_simulation_scalar_diagnostics,
    simulation_scalar_diagnostics_path,
)
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


@dataclass(frozen=True)
class CatalogueSimulation:
    """One simulation selected from the indexed catalogue.

    Args:
        collection_id: Stable ID of the containing collection.
        simulation_id: Permanent ID within the collection.
        path: Absolute path to the imported simulation directory.
        importer: Name of the adapter that imported this simulation.
    """

    collection_id: str
    simulation_id: str
    path: Path
    importer: str


def _index_scalar_value(value: str | int | float | bool) -> tuple[str, float | None, str | None]:
    """Convert one catalogue scalar to the SQLite comparison representation.

    Args:
        value: Known scalar from a configuration or scalar-diagnostic record.

    Returns:
        The SQLite value type plus numeric and text columns.

    Raises:
        ValueError: If the scalar cannot be represented by the registry.
    """
    # Both configuration and derived values use this conversion so one query
    # applies identical numeric, text, and boolean comparison rules to both.
    if isinstance(value, bool):
        return "boolean", float(value), None
    if isinstance(value, (int, float)):
        return "number", float(value), None
    if isinstance(value, str):
        return "text", None, value
    raise ValueError(f"Catalogue value has an unsupported type: {type(value).__name__}.")


def index_catalogue(
    catalogue_root: Path,
    collection_id: str | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> IndexReport:
    """Index one collection or every collection in a local catalogue.

    Args:
        catalogue_root: Existing catalogue root containing ``collections/``.
        collection_id: Optional collection ID to replace in the registry. When
            omitted, rebuild the registry from every collection on disk.
        progress: Optional callback invoked after each simulation is indexed.
            It receives the one-based completed count, total count, and the
            ``collection_id/simulation_id`` label.

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
    derived_rows: list[
        tuple[str, str, str, str, float | None, str | None, str | None, str, str, str, int]
    ] = []
    time_series_rows: list[tuple[str, str, str, str]] = []

    simulation_roots_by_collection = []
    for collection_root in collection_roots:
        simulations_root = collection_root / "simulations"
        if not simulations_root.is_dir():
            raise NotADirectoryError(
                f"Collection has no simulations directory: {simulations_root}"
            )
        simulation_roots_by_collection.append(
            (
                collection_root,
                tuple(sorted(path for path in simulations_root.iterdir() if path.is_dir())),
            )
        )
    total_simulations = sum(
        len(simulation_roots)
        for _, simulation_roots in simulation_roots_by_collection
    )
    indexed_simulations = 0

    for collection_root, simulation_roots in simulation_roots_by_collection:
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
        diagnostics_path = collection_diagnostics_path(collection_root)
        diagnostics = (
            read_collection_diagnostics(diagnostics_path)
            if diagnostics_path.is_file()
            else None
        )

        for simulation_root in simulation_roots:
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
                    value_type, numeric_value, text_value = _index_scalar_value(parameter.value)
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

            scalar_diagnostics_path = simulation_scalar_diagnostics_path(simulation_root)
            if scalar_diagnostics_path.is_file():
                if diagnostics is None:
                    raise ValueError(
                        "Simulation scalar diagnostics has no collection definition: "
                        f"{scalar_diagnostics_path}"
                    )
                scalar_diagnostics = read_simulation_scalar_diagnostics(
                    scalar_diagnostics_path,
                    diagnostics,
                )
                for result in scalar_diagnostics.results:
                    # Store every choice combination. The default flag lets the
                    # normal query API select the registered scientific default.
                    choice_key = json.dumps(
                        dict(result.choices), sort_keys=True, separators=(",", ":")
                    )
                    is_default = int(result.uses_default_choices(diagnostics))
                    for value in result.values:
                        value_type, numeric_value, text_value = _index_scalar_value(value.value)
                        derived_rows.append(
                            (
                                collection.collection_id,
                                metadata.simulation_id,
                                value.name,
                                value_type,
                                numeric_value,
                                text_value,
                                value.unit,
                                result.diagnostic_name,
                                result.diagnostic_version,
                                choice_key,
                                is_default,
                            )
                        )

            if diagnostics is not None:
                for definition in diagnostics.diagnostics:
                    if definition.kind != "time_series":
                        continue
                    product_path = simulation_root / definition.relative_path
                    if not product_path.is_file():
                        continue
                    # Index only a completed file with matching identity. This
                    # keeps coverage queries fast without reading measurements.
                    with h5py.File(product_path, "r") as product:
                        if (
                            product.attrs.get("complete") != True
                            or product.attrs.get("diagnostic_name") != definition.name
                            or f"v{product.attrs.get('diagnostic_version')}" != definition.version
                        ):
                            raise ValueError(
                                f"Time-series diagnostic file is incomplete or mismatched: "
                                f"{product_path}"
                            )
                    time_series_rows.append(
                        (
                            collection.collection_id,
                            metadata.simulation_id,
                            definition.name,
                            definition.version,
                        )
                    )
            indexed_simulations += 1
            if progress is not None:
                progress(
                    indexed_simulations,
                    total_simulations,
                    f"{collection.collection_id}/{metadata.simulation_id}",
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
            CREATE TABLE IF NOT EXISTS derived_values (
                collection_id TEXT NOT NULL,
                simulation_id TEXT NOT NULL,
                name TEXT NOT NULL,
                value_type TEXT NOT NULL,
                numeric_value REAL,
                text_value TEXT,
                unit TEXT,
                diagnostic_name TEXT NOT NULL,
                diagnostic_version TEXT NOT NULL,
                choice_key TEXT NOT NULL,
                is_default INTEGER NOT NULL,
                PRIMARY KEY (
                    collection_id, simulation_id, name, diagnostic_name,
                    diagnostic_version, choice_key
                ),
                FOREIGN KEY (collection_id, simulation_id)
                    REFERENCES simulations (collection_id, simulation_id)
            );
            CREATE INDEX IF NOT EXISTS derived_numeric_lookup
                ON derived_values (name, is_default, numeric_value, collection_id, simulation_id);
            CREATE INDEX IF NOT EXISTS derived_text_lookup
                ON derived_values (name, is_default, text_value, collection_id, simulation_id);
            CREATE TABLE IF NOT EXISTS time_series_products (
                collection_id TEXT NOT NULL,
                simulation_id TEXT NOT NULL,
                diagnostic_name TEXT NOT NULL,
                diagnostic_version TEXT NOT NULL,
                PRIMARY KEY (
                    collection_id, simulation_id, diagnostic_name, diagnostic_version
                ),
                FOREIGN KEY (collection_id, simulation_id)
                    REFERENCES simulations (collection_id, simulation_id)
            );
            CREATE INDEX IF NOT EXISTS time_series_product_lookup
                ON time_series_products (
                    collection_id, diagnostic_name, diagnostic_version, simulation_id
                );
            """
        )
        indexed_collection_ids = tuple(row[0] for row in collection_rows)
        if collection_id is None:
            connection.execute("DELETE FROM time_series_products")
            connection.execute("DELETE FROM derived_values")
            connection.execute("DELETE FROM parameter_values")
            connection.execute("DELETE FROM simulations")
            connection.execute("DELETE FROM collections")
        else:
            for indexed_collection_id in indexed_collection_ids:
                connection.execute(
                    "DELETE FROM time_series_products WHERE collection_id = ?",
                    (indexed_collection_id,),
                )
                connection.execute(
                    "DELETE FROM derived_values WHERE collection_id = ?",
                    (indexed_collection_id,),
                )
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
        connection.executemany(
            """
            INSERT INTO derived_values (
                collection_id, simulation_id, name, value_type, numeric_value,
                text_value, unit, diagnostic_name, diagnostic_version,
                choice_key, is_default
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            derived_rows,
        )
        connection.executemany(
            """
            INSERT INTO time_series_products (
                collection_id, simulation_id, diagnostic_name, diagnostic_version
            ) VALUES (?, ?, ?, ?)
            """,
            time_series_rows,
        )

    return IndexReport(
        catalogue_root=catalogue_root,
        registry_path=registry_path,
        collection_ids=tuple(row[0] for row in collection_rows),
        simulation_count=len(simulation_rows),
        parameter_count=len(parameter_rows) + len(derived_rows),
    )


def find_simulations(
    catalogue_root: Path,
    collection_id: str | None = None,
    filters: Mapping[str, str | int | float | bool | tuple[float | None, float | None]] | None = None,
) -> tuple[CatalogueSimulation, ...]:
    """Return catalogue simulations matching indexed parameter filters.

    Args:
        catalogue_root: Existing catalogue root containing ``registry.sqlite``.
        collection_id: Optional collection ID to restrict the search.
        filters: Configuration and default-choice derived parameter filters.
            A scalar requires an exact match. A two-value tuple gives an
            inclusive numeric range, where ``None`` means no lower or upper
            bound.

    Returns:
        Matching simulations ordered by collection ID and simulation ID.

    Raises:
        FileNotFoundError: If the catalogue has not been indexed yet.
        ValueError: If a range is invalid or a filter value is unsupported.
        sqlite3.Error: If the registry cannot be read.

    Examples:
        ```python
        find_simulations(
            catalogue_root,
            collection_id="dcaf-grid-v1",
            filters={"tff": (0.5, 3.0), "sfe": 0.3},
        )
        ```
    """
    catalogue_root = catalogue_root.resolve()
    registry_path = catalogue_root / "registry.sqlite"
    if not registry_path.is_file():
        raise FileNotFoundError(
            f"Catalogue has not been indexed: {registry_path}. Run index-catalogue first."
        )

    query = [
        "SELECT DISTINCT simulations.collection_id, simulations.simulation_id, ",
        "simulations.relative_path, collections.importer ",
        "FROM simulations JOIN collections USING (collection_id)",
    ]
    conditions: list[str] = []
    join_values: list[str | float] = []
    condition_values: list[str | float] = []
    if collection_id is not None:
        conditions.append("simulations.collection_id = ?")
        condition_values.append(collection_id)

    for index, (name, filter_value) in enumerate((filters or {}).items()):
        alias = f"parameter_{index}"
        if isinstance(filter_value, tuple):
            if len(filter_value) != 2:
                raise ValueError(f"Range filter {name} must contain exactly two bounds.")
            lower, upper = filter_value
            if lower is not None and upper is not None and lower > upper:
                raise ValueError(f"Range filter {name} has a lower bound above its upper bound.")
            query.append(
                f" JOIN (SELECT collection_id, simulation_id, name, value_type, "
                f"numeric_value, text_value FROM parameter_values UNION ALL "
                f"SELECT collection_id, simulation_id, name, value_type, numeric_value, "
                f"text_value FROM derived_values WHERE is_default = 1) AS {alias} ON "
                f"{alias}.collection_id = simulations.collection_id AND "
                f"{alias}.simulation_id = simulations.simulation_id AND "
                f"{alias}.name = ? AND {alias}.value_type = 'number'"
            )
            join_values.append(name)
            if lower is not None:
                conditions.append(f"{alias}.numeric_value >= ?")
                condition_values.append(float(lower))
            if upper is not None:
                conditions.append(f"{alias}.numeric_value <= ?")
                condition_values.append(float(upper))
        elif isinstance(filter_value, bool):
            query.append(
                f" JOIN (SELECT collection_id, simulation_id, name, value_type, "
                f"numeric_value, text_value FROM parameter_values UNION ALL "
                f"SELECT collection_id, simulation_id, name, value_type, numeric_value, "
                f"text_value FROM derived_values WHERE is_default = 1) AS {alias} ON "
                f"{alias}.collection_id = simulations.collection_id AND "
                f"{alias}.simulation_id = simulations.simulation_id AND "
                f"{alias}.name = ? AND {alias}.value_type = 'boolean' AND "
                f"{alias}.numeric_value = ?"
            )
            join_values.extend((name, float(filter_value)))
        elif isinstance(filter_value, (int, float)):
            query.append(
                f" JOIN (SELECT collection_id, simulation_id, name, value_type, "
                f"numeric_value, text_value FROM parameter_values UNION ALL "
                f"SELECT collection_id, simulation_id, name, value_type, numeric_value, "
                f"text_value FROM derived_values WHERE is_default = 1) AS {alias} ON "
                f"{alias}.collection_id = simulations.collection_id AND "
                f"{alias}.simulation_id = simulations.simulation_id AND "
                f"{alias}.name = ? AND {alias}.value_type = 'number' AND "
                f"{alias}.numeric_value = ?"
            )
            join_values.extend((name, float(filter_value)))
        elif isinstance(filter_value, str):
            query.append(
                f" JOIN (SELECT collection_id, simulation_id, name, value_type, "
                f"numeric_value, text_value FROM parameter_values UNION ALL "
                f"SELECT collection_id, simulation_id, name, value_type, numeric_value, "
                f"text_value FROM derived_values WHERE is_default = 1) AS {alias} ON "
                f"{alias}.collection_id = simulations.collection_id AND "
                f"{alias}.simulation_id = simulations.simulation_id AND "
                f"{alias}.name = ? AND {alias}.value_type = 'text' AND "
                f"{alias}.text_value = ?"
            )
            join_values.extend((name, filter_value))
        else:
            raise ValueError(f"Unsupported filter value for {name}.")

    if conditions:
        query.append(" WHERE " + " AND ".join(conditions))
    query.append(" ORDER BY simulations.collection_id, simulations.simulation_id")
    with sqlite3.connect(registry_path) as connection:
        rows = connection.execute("".join(query), [*join_values, *condition_values]).fetchall()
    return tuple(
        CatalogueSimulation(
            collection_id=indexed_collection_id,
            simulation_id=simulation_id,
            path=catalogue_root / relative_path,
            importer=importer,
        )
        for indexed_collection_id, simulation_id, relative_path, importer in rows
    )


def summarize_catalogue(
    catalogue_root: Path,
    collection_id: str | None = None,
) -> str:
    """Return a concise human-readable summary of an indexed catalogue.

    Args:
        catalogue_root: Existing catalogue root containing ``registry.sqlite``.
        collection_id: Optional collection ID to summarize. When omitted,
            summarize every indexed collection.

    Returns:
        A multi-line summary of collections, simulation counts, and indexed
        parameter availability. Numeric parameters show their stored range;
        text and boolean parameters show their number of distinct values.

    Raises:
        FileNotFoundError: If the catalogue has not been indexed yet.
        ValueError: If ``collection_id`` is not present in the registry.
        sqlite3.Error: If the registry cannot be read.

    Notes:
        This function reads the SQLite registry and each selected collection's
        small ``collection.yaml`` file for optional grid axes. Run
        :func:`index_catalogue` after importing or changing simulations before
        relying on the summary.
    """
    catalogue_root = catalogue_root.resolve()
    registry_path = catalogue_root / "registry.sqlite"
    if not registry_path.is_file():
        raise FileNotFoundError(
            f"Catalogue has not been indexed: {registry_path}. Run index-catalogue first."
        )

    with sqlite3.connect(registry_path) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'time_series_products'"
        ).fetchone()
        if table is None:
            raise ValueError(
                "Catalogue registry is out of date. Run index-catalogue to rebuild it."
            )
        if collection_id is None:
            collections = connection.execute(
                """
                SELECT
                    collections.collection_id,
                    collections.importer,
                    collections.relative_path,
                    COUNT(simulations.simulation_id)
                FROM collections
                LEFT JOIN simulations USING (collection_id)
                GROUP BY collections.collection_id, collections.importer, collections.relative_path
                ORDER BY collections.collection_id
                """
            ).fetchall()
        else:
            collections = connection.execute(
                """
                SELECT
                    collections.collection_id,
                    collections.importer,
                    collections.relative_path,
                    COUNT(simulations.simulation_id)
                FROM collections
                LEFT JOIN simulations USING (collection_id)
                WHERE collections.collection_id = ?
                GROUP BY collections.collection_id, collections.importer, collections.relative_path
                """,
                (collection_id,),
            ).fetchall()
        if collection_id is not None and not collections:
            raise ValueError(f"Collection is not indexed: {collection_id}")

        terminal_width = shutil.get_terminal_size(fallback=(100, 24)).columns
        lines = [f"Registry: {registry_path}", f"Collections: {len(collections)}"]
        for indexed_collection_id, importer, relative_path, simulation_count in collections:
            lines.append("")
            lines.append(f"{indexed_collection_id} ({importer})")
            lines.append(f"  Simulations: {simulation_count}")

            # Configuration rows are the normal simulation query parameters.
            parameter_rows = connection.execute(
                """
                SELECT name, section, value_type, unit, numeric_value, text_value
                FROM parameter_values
                WHERE collection_id = ?
                ORDER BY section, name, value_type, unit, numeric_value, text_value
                """,
                (indexed_collection_id,),
            ).fetchall()
            lines.append("  Simulation parameters:")
            if not parameter_rows:
                lines.append("    none")
            else:
                name_width = min(24, max(4, max(len(row[0]) for row in parameter_rows)))
                source_width = min(15, max(6, max(len(row[1]) for row in parameter_rows)))
                unit_width = min(8, max(4, max(len(row[3] or "1") for row in parameter_rows)))
                available_width = 9
                value_width = max(12, terminal_width - name_width - source_width - unit_width - available_width - 13)
                lines.append(
                    f"    {'name':<{name_width}}  {'source':<{source_width}}  "
                    f"{'unit':<{unit_width}}  {'available':>{available_width}}  values"
                )
                grouped_parameters: dict[tuple[str, str, str, str | None], list[object]] = {}
                for name, section, value_type, unit, numeric_value, text_value in parameter_rows:
                    grouped_parameters.setdefault((name, section, value_type, unit), []).append(
                        numeric_value if value_type == "number" else text_value
                    )
                for (name, section, value_type, unit), values in grouped_parameters.items():
                    distinct_values = list(dict.fromkeys(values))
                    if len(distinct_values) <= 10:
                        detail = ", ".join(
                            f"{value:g}" if value_type == "number" else str(value)
                            for value in distinct_values
                        )
                    elif value_type == "number":
                        detail = (
                            f"{len(distinct_values)} distinct; "
                            f"{min(distinct_values):g} to {max(distinct_values):g}"
                        )
                    else:
                        detail = f"{len(distinct_values)} distinct values"
                    wrapped = textwrap.wrap(detail, width=value_width, break_long_words=False) or [""]
                    available = f"{len(values)}/{simulation_count}"
                    prefix = (
                        f"    {name:<{name_width}}  {section:<{source_width}}  "
                        f"{(unit or '1'):<{unit_width}}  {available:>{available_width}}  "
                    )
                    lines.append(prefix + wrapped[0])
                    continuation = " " * len(prefix)
                    lines.extend(continuation + value for value in wrapped[1:])

            # Default-choice scalar rows share the normal query space, so the
            # summary reports their actual indexed distribution.
            derived_rows = connection.execute(
                """
                SELECT diagnostic_name, diagnostic_version, name, value_type,
                       unit, numeric_value, text_value
                FROM derived_values
                WHERE collection_id = ? AND is_default = 1
                ORDER BY diagnostic_name, diagnostic_version, name, numeric_value, text_value
                """,
                (indexed_collection_id,),
            ).fetchall()
            lines.append("  Derived parameters:")
            if not derived_rows:
                lines.append("    none")
            else:
                diagnostic_width = min(24, max(10, max(len(row[0]) for row in derived_rows)))
                field_width = min(20, max(5, max(len(row[2]) for row in derived_rows)))
                unit_width = min(8, max(4, max(len(row[4] or "1") for row in derived_rows)))
                available_width = 9
                summary_width = max(12, terminal_width - diagnostic_width - field_width - unit_width - available_width - 13)
                lines.append(
                    f"    {'diagnostic':<{diagnostic_width}}  {'field':<{field_width}}  "
                    f"{'unit':<{unit_width}}  {'available':>{available_width}}  summary"
                )
                grouped_derived: dict[tuple[str, str, str, str, str | None], list[object]] = {}
                for diagnostic_name, version, name, value_type, unit, numeric_value, text_value in derived_rows:
                    grouped_derived.setdefault(
                        (diagnostic_name, version, name, value_type, unit), []
                    ).append(numeric_value if value_type == "number" else text_value)
                for (diagnostic_name, version, name, value_type, unit), values in grouped_derived.items():
                    if value_type == "number":
                        numeric_values = [float(value) for value in values]
                        deviation = statistics.pstdev(numeric_values) if len(numeric_values) > 1 else 0.0
                        detail = (
                            f"{min(numeric_values):g} to {max(numeric_values):g}; "
                            f"median {statistics.median(numeric_values):g}; "
                            f"mean {statistics.mean(numeric_values):g} +/- {deviation:g}"
                        )
                    else:
                        distinct_values = list(dict.fromkeys(values))
                        detail = (
                            ", ".join(str(value) for value in distinct_values)
                            if len(distinct_values) <= 10
                            else f"{len(distinct_values)} distinct values"
                        )
                    wrapped = textwrap.wrap(detail, width=summary_width, break_long_words=False) or [""]
                    diagnostic_label = f"{diagnostic_name} {version}"
                    available = f"{len(values)}/{simulation_count}"
                    prefix = (
                        f"    {diagnostic_label:<{diagnostic_width}}  {name:<{field_width}}  "
                        f"{(unit or '1'):<{unit_width}}  {available:>{available_width}}  "
                    )
                    lines.append(prefix + wrapped[0])
                    continuation = " " * len(prefix)
                    lines.extend(continuation + value for value in wrapped[1:])

            collection_root = catalogue_root / relative_path
            diagnostics_path = collection_diagnostics_path(collection_root)
            diagnostics = (
                read_collection_diagnostics(diagnostics_path)
                if diagnostics_path.is_file()
                else None
            )
            lines.append("  Time-series diagnostics:")
            if diagnostics is None or not any(
                definition.kind == "time_series" for definition in diagnostics.diagnostics
            ):
                lines.append("    none")
            else:
                time_series_width = 24
                version_width = 7
                available_width = 9
                field_width = max(12, terminal_width - time_series_width - version_width - available_width - 13)
                lines.append(
                    f"    {'diagnostic':<{time_series_width}}  {'version':<{version_width}}  "
                    f"{'available':>{available_width}}  fields"
                )
                availability = {
                    (name, version): count
                    for name, version, count in connection.execute(
                        """
                        SELECT diagnostic_name, diagnostic_version, COUNT(*)
                        FROM time_series_products
                        WHERE collection_id = ?
                        GROUP BY diagnostic_name, diagnostic_version
                        """,
                        (indexed_collection_id,),
                    )
                }
                for definition in diagnostics.diagnostics:
                    if definition.kind != "time_series":
                        continue
                    fields = ", ".join(
                        f"{field.name} [{field.unit or '1'}]"
                        for field in definition.fields
                    )
                    if definition.choices:
                        choice_definitions = {
                            choice.name: choice for choice in diagnostics.choices
                        }
                        fields += "; choices: " + ", ".join(
                            (
                                f"{name}="
                                f"{','.join(choice_definitions[name].values)} "
                                f"(default {choice_definitions[name].default})"
                            )
                            for name in definition.choices
                        )
                    wrapped = textwrap.wrap(fields, width=field_width, break_long_words=False) or [""]
                    available_count = availability.get((definition.name, definition.version), 0)
                    available = f"{available_count}/{simulation_count}"
                    prefix = (
                        f"    {definition.name:<{time_series_width}}  "
                        f"{definition.version:<{version_width}}  "
                        f"{available:>{available_width}}  "
                    )
                    lines.append(prefix + wrapped[0])
                    continuation = " " * len(prefix)
                    lines.extend(continuation + value for value in wrapped[1:])
            collection = read_collection_configuration(
                catalogue_root / relative_path / "collection.yaml"
            )
            if collection.grid_axes:
                expected_count = prod(len(values) for _, values in collection.grid_axes)
                missing_count = len(missing_combinations(catalogue_root, indexed_collection_id))
                lines.append("  Grid coverage:")
                lines.append(f"    Expected combinations: {expected_count}")
                lines.append(f"    Indexed combinations: {expected_count - missing_count}")
                lines.append(f"    Missing combinations: {missing_count}")
    return "\n".join(lines)


def missing_combinations(
    catalogue_root: Path,
    collection_id: str,
) -> tuple[dict[str, str | int | float | bool], ...]:
    """Return declared grid parameter combinations absent from one collection.

    Args:
        catalogue_root: Existing catalogue root containing ``registry.sqlite``.
        collection_id: Indexed collection ID that declares ``grid_axes``.

    Returns:
        Missing parameter combinations in the order defined by
        ``collection.yaml``. Each dictionary maps a grid-axis name to one
        expected value.

    Raises:
        FileNotFoundError: If the catalogue has not been indexed yet.
        ValueError: If the collection is not indexed or does not declare
            ``grid_axes``.
        sqlite3.Error: If the registry cannot be read.

    Notes:
        ``grid_axes`` represents a full Cartesian product. The function does
        not infer intended combinations from existing simulations.
    """
    catalogue_root = catalogue_root.resolve()
    registry_path = catalogue_root / "registry.sqlite"
    if not registry_path.is_file():
        raise FileNotFoundError(
            f"Catalogue has not been indexed: {registry_path}. Run index-catalogue first."
        )
    with sqlite3.connect(registry_path) as connection:
        row = connection.execute(
            "SELECT relative_path FROM collections WHERE collection_id = ?",
            (collection_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Collection is not indexed: {collection_id}")
        collection = read_collection_configuration(catalogue_root / row[0] / "collection.yaml")
        if not collection.grid_axes:
            raise ValueError(f"Collection does not declare grid_axes: {collection_id}")
        axis_names = tuple(name for name, _ in collection.grid_axes)
        placeholders = ", ".join("?" for _ in axis_names)
        rows = connection.execute(
            f"""
            SELECT simulation_id, name, value_type, numeric_value, text_value
            FROM parameter_values
            WHERE collection_id = ? AND name IN ({placeholders})
            """,
            (collection_id, *axis_names),
        ).fetchall()

    values_by_simulation: dict[str, dict[str, str | int | float | bool]] = {}
    for simulation_id, name, value_type, numeric_value, text_value in rows:
        if value_type == "boolean":
            value: str | int | float | bool = bool(numeric_value)
        elif value_type == "number":
            value = float(numeric_value)
        else:
            value = text_value
        values_by_simulation.setdefault(simulation_id, {})[name] = value

    observed = {
        tuple(values[name] for name in axis_names)
        for values in values_by_simulation.values()
        if all(name in values for name in axis_names)
    }
    return tuple(
        dict(zip(axis_names, combination, strict=True))
        for combination in product(*(values for _, values in collection.grid_axes))
        if combination not in observed
    )
