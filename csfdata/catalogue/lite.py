"""Operate on catalogue roots marked as lightweight copies.

A lite catalogue uses the normal catalogue layout, but its ``lite.yaml`` file
records that it is a portable, collection-scoped copy. The marker stores the
full catalogue that owns the omitted raw snapshots. This module implements the
extra safety rules required by that mode: copy collection metadata, derived
data, and explicitly declared raw support files; record provenance; and reject
incompatible updates.

Lite is therefore a catalogue mode, not a separate data model. General
catalogue operations continue to work on a lite root in the usual way.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import uuid4

import h5py
import yaml

from csfdata.catalogue.collection import read_collection_configuration
from csfdata.catalogue.diagnostics import (
    DiagnosticDefinition,
    read_collection_diagnostics,
)
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


@dataclass(frozen=True)
class TimeSeriesSelection:
    """Selected material from one time-series diagnostic.

    Args:
        name: Published diagnostic name.
        version: Optional exact version such as ``"v1"``. ``None`` selects
            the latest version declared by the source collection.
        choices: Optional scientific choice values keyed by choice name.
            ``None`` retains every stored choice.
        fields: Optional ordinary series fields. ``None`` retains every field.
        particle_fields: Particle fields to retain, ``"all"`` for every
            particle field, or ``None`` to omit particle data.
    """

    name: str
    version: str | None
    choices: dict[str, tuple[str, ...]] | None
    fields: tuple[str, ...] | None
    particle_fields: tuple[str, ...] | Literal["all"] | None


@dataclass(frozen=True)
class DerivedSelection:
    """One collection's requested time-series material for a lite copy.

    Args:
        collection_id: Source collection represented by the lite catalogue.
        time_series: Selected diagnostics. Scalars are intentionally absent
            because lite imports always retain them completely.
    """

    collection_id: str
    time_series: tuple[TimeSeriesSelection, ...]


def read_derived_selection(path: Path) -> DerivedSelection:
    """Read and validate one derived-data selection configuration.

    Args:
        path: YAML configuration containing ``schema_version``, ``collection``,
            and an optional ``time_series`` mapping.

    Returns:
        Validated collection and time-series selection.

    Raises:
        ValueError: If the configuration shape or any identifier is invalid.
        OSError: If the file cannot be read.
        yaml.YAMLError: If the YAML document cannot be parsed.
    """
    with path.open(encoding="utf-8") as stream:
        contents = yaml.safe_load(stream)
    if not isinstance(contents, dict) or contents.get("schema_version") != 1:
        raise ValueError("Derived selection must use schema_version 1.")
    collection_id = contents.get("collection")
    if not isinstance(collection_id, str) or not collection_id:
        raise ValueError("Derived selection must name one non-empty collection.")
    configured = contents.get("time_series", {})
    if not isinstance(configured, dict):
        raise ValueError("Derived selection time_series must be a mapping.")

    selections = []
    for name, options in configured.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Derived selection diagnostic names must be non-empty strings.")
        if options is None:
            options = {}
        if not isinstance(options, dict):
            raise ValueError(f"Selection for {name!r} must be a mapping.")
        unknown_options = set(options) - {"version", "choices", "fields", "particle_fields"}
        if unknown_options:
            raise ValueError(
                f"Selection for {name!r} has unknown options: "
                + ", ".join(sorted(unknown_options))
            )

        version = options.get("version")
        if version is not None and (
            not isinstance(version, str) or not version.startswith("v") or not version[1:].isdigit()
        ):
            raise ValueError(f"Selection for {name!r} has an invalid version.")

        choices = options.get("choices")
        if choices is not None:
            if not isinstance(choices, dict):
                raise ValueError(f"Selection choices for {name!r} must be a mapping.")
            parsed_choices = {}
            for choice_name, values in choices.items():
                if (
                    not isinstance(choice_name, str)
                    or not choice_name
                    or not isinstance(values, list)
                    or not values
                    or not all(isinstance(value, str) and value for value in values)
                    or len(values) != len(set(values))
                ):
                    raise ValueError(
                        f"Selection choice {choice_name!r} for {name!r} must contain "
                        "unique non-empty string values."
                    )
                parsed_choices[choice_name] = tuple(values)
            choices = parsed_choices

        fields = options.get("fields")
        if fields is not None and (
            not isinstance(fields, list)
            or not all(isinstance(field, str) and field for field in fields)
            or len(fields) != len(set(fields))
        ):
            raise ValueError(f"Selection fields for {name!r} must be unique strings.")

        particle_fields = options.get("particle_fields")
        if particle_fields != "all" and particle_fields is not None and (
            not isinstance(particle_fields, list)
            or not all(isinstance(field, str) and field for field in particle_fields)
            or len(particle_fields) != len(set(particle_fields))
        ):
            raise ValueError(
                f"Selection particle_fields for {name!r} must be 'all' or unique strings."
            )
        selections.append(
            TimeSeriesSelection(
                name,
                version,
                choices,
                tuple(fields) if fields is not None else None,
                tuple(particle_fields) if isinstance(particle_fields, list) else particle_fields,
            )
        )
    return DerivedSelection(collection_id, tuple(selections))


def write_derived_selection(selection: DerivedSelection, path: Path) -> Path:
    """Write the normalized selection used to materialize a lite catalogue.

    Args:
        selection: Validated one-collection derived selection.
        path: Destination YAML path.

    Returns:
        The written path.
    """
    time_series = {}
    for diagnostic in selection.time_series:
        options = {}
        if diagnostic.version is not None:
            options["version"] = diagnostic.version
        if diagnostic.choices is not None:
            options["choices"] = {
                name: list(values) for name, values in diagnostic.choices.items()
            }
        if diagnostic.fields is not None:
            options["fields"] = list(diagnostic.fields)
        if diagnostic.particle_fields is not None:
            options["particle_fields"] = (
                diagnostic.particle_fields
                if diagnostic.particle_fields == "all"
                else list(diagnostic.particle_fields)
            )
        time_series[diagnostic.name] = options
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "collection": selection.collection_id,
                "time_series": time_series,
            },
            allow_unicode=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


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


def resolve_time_series_selection(
    collection_root: Path,
    selection: DerivedSelection,
) -> tuple[tuple[DiagnosticDefinition, TimeSeriesSelection], ...]:
    """Resolve configured diagnostic names against collection declarations.

    Args:
        collection_root: Local collection containing ``diagnostics.yaml``.
        selection: Requested time-series diagnostics for that collection.

    Returns:
        Exact published definitions paired with their requested material.

    Raises:
        FileNotFoundError: If the collection has no diagnostic declarations.
        ValueError: If a diagnostic, version, choice, or field is unavailable.
    """
    diagnostics_path = collection_root / "diagnostics.yaml"
    if selection.time_series and not diagnostics_path.is_file():
        raise FileNotFoundError(
            f"Collection diagnostics are missing: {diagnostics_path}"
        )
    if not selection.time_series:
        return ()
    diagnostics = read_collection_diagnostics(diagnostics_path)
    choices_by_name = {choice.name: choice for choice in diagnostics.choices}
    resolved = []
    for requested in selection.time_series:
        candidates = [
            definition
            for definition in diagnostics.diagnostics
            if definition.kind == "time_series"
            and definition.name == requested.name
            and (requested.version is None or definition.version == requested.version)
        ]
        if not candidates:
            version_text = f" {requested.version}" if requested.version else ""
            raise ValueError(
                f"Collection has no time-series diagnostic {requested.name!r}{version_text}."
            )
        definition = candidates[-1]
        if len(definition.choices) > 1:
            raise ValueError(
                f"Time-series selection does not support multiple choice dimensions: "
                f"{requested.name}."
            )
        configured_choices = requested.choices or {}
        unknown_choice_names = set(configured_choices) - set(definition.choices)
        if unknown_choice_names:
            raise ValueError(
                f"Selection for {requested.name!r} has irrelevant choices: "
                + ", ".join(sorted(unknown_choice_names))
            )
        for choice_name, values in configured_choices.items():
            unavailable = set(values) - set(choices_by_name[choice_name].values)
            if unavailable:
                raise ValueError(
                    f"Selection for {requested.name!r} has unavailable {choice_name} values: "
                    + ", ".join(sorted(unavailable))
                )
        if requested.fields is not None:
            available_fields = {field.name for field in definition.fields}
            unknown_fields = set(requested.fields) - available_fields
            if unknown_fields:
                raise ValueError(
                    f"Selection for {requested.name!r} has unavailable fields: "
                    + ", ".join(sorted(unknown_fields))
                )
        resolved.append((definition, requested))
    return tuple(resolved)


def write_selected_time_series(
    source_series: Path,
    destination_series: Path,
    definition: DiagnosticDefinition,
    selection: TimeSeriesSelection,
) -> None:
    """Write one atomic, standard-path HDF5 subset from a complete result.

    Args:
        source_series: Complete source ``series.h5`` file.
        destination_series: Standard lite-catalogue ``series.h5`` path.
        definition: Published diagnostic definition selected for the copy.
        selection: Requested choices and ordinary and particle fields.

    Raises:
        FileNotFoundError: If requested particle data are absent.
        ValueError: If source identity, groups, or fields do not satisfy the
            requested selection.
        OSError: If an HDF5 file cannot be read or written.

    Notes:
        ``series.h5`` remains the completion marker. When particle fields are
        requested, ``particles.h5`` is installed first and the matching series
        file is installed last. Both files retain their standard names and are
        marked with ``csfdata_subset`` so they cannot be imported back into a
        full catalogue.
    """
    destination_series.parent.mkdir(parents=True, exist_ok=True)
    series_staging = destination_series.parent / f".series.{uuid4().hex}.tmp"
    destination_particles = destination_series.with_name("particles.h5")
    particle_staging = destination_series.parent / f".particles.{uuid4().hex}.tmp"
    requested_particles = bool(selection.particle_fields)
    try:
        with h5py.File(source_series, "r") as source:
            if source.attrs.get("complete") != True:
                raise ValueError(f"Source time-series result is incomplete: {source_series}")
            if (
                source.attrs.get("diagnostic_name") != definition.name
                or f"v{source.attrs.get('diagnostic_version')}" != definition.version
            ):
                raise ValueError(f"Source time-series identity differs: {source_series}")
            if "choices" not in source:
                raise ValueError(f"Source time-series has no choices group: {source_series}")

            available_groups = tuple(source["choices"])
            if definition.choices and selection.choices:
                choice_name = definition.choices[0]
                selected_groups = selection.choices.get(choice_name, available_groups)
            else:
                selected_groups = available_groups
            unavailable_groups = set(selected_groups) - set(available_groups)
            if unavailable_groups:
                raise ValueError(
                    f"Source time-series lacks selected choices: "
                    + ", ".join(sorted(unavailable_groups))
                )
            selected_fields = (
                tuple(field.name for field in definition.fields)
                if selection.fields is None
                else selection.fields
            )

            with h5py.File(series_staging, "w") as output:
                for name, value in source.attrs.items():
                    output.attrs[name] = value
                output.attrs["csfdata_subset"] = True
                if not requested_particles:
                    if "particle_series_file" in output.attrs:
                        del output.attrs["particle_series_file"]
                    if "series_id" in output.attrs:
                        del output.attrs["series_id"]
                for name in ("time", "snapshot_id"):
                    if name not in source:
                        raise ValueError(
                            f"Source time-series is missing {name!r}: {source_series}"
                        )
                    source.copy(name, output)
                output_choices = output.create_group("choices")
                for group_name in selected_groups:
                    source_group = source["choices"][group_name]
                    output_group = output_choices.create_group(group_name)
                    for name, value in source_group.attrs.items():
                        output_group.attrs[name] = value
                    missing_fields = set(selected_fields) - set(source_group)
                    if missing_fields:
                        raise ValueError(
                            f"Source time-series choice {group_name!r} lacks fields: "
                            + ", ".join(sorted(missing_fields))
                        )
                    for field in selected_fields:
                        source_group.copy(field, output_group)

        if requested_particles:
            source_particles = source_series.with_name("particles.h5")
            if not source_particles.is_file():
                raise FileNotFoundError(
                    f"Requested particle-series file is missing: {source_particles}"
                )
            with h5py.File(source_particles, "r") as source, h5py.File(
                particle_staging, "w"
            ) as output:
                if source.attrs.get("complete") != True:
                    raise ValueError(
                        f"Source particle-series result is incomplete: {source_particles}"
                    )
                for name, value in source.attrs.items():
                    output.attrs[name] = value
                output.attrs["csfdata_subset"] = True
                if "choices" not in source:
                    raise ValueError(
                        f"Source particle-series has no choices group: {source_particles}"
                    )
                output_choices = output.create_group("choices")
                particle_groups = [
                    group_name for group_name in selected_groups if group_name in source["choices"]
                ]
                if not particle_groups:
                    raise ValueError(
                        f"Selected choices have no particle data: {source_particles}"
                    )
                for group_name in particle_groups:
                    source_group = source["choices"][group_name]
                    output_group = output_choices.create_group(group_name)
                    for name, value in source_group.attrs.items():
                        output_group.attrs[name] = value
                    for identity_field in ("snapshot_id", "particle_key"):
                        if identity_field not in source_group:
                            raise ValueError(
                                f"Source particle-series choice {group_name!r} is missing "
                                f"{identity_field!r}."
                            )
                        source_group.copy(identity_field, output_group)
                    available_fields = set(source_group) - {"snapshot_id", "particle_key"}
                    particle_fields = (
                        tuple(sorted(available_fields))
                        if selection.particle_fields == "all"
                        else selection.particle_fields
                    )
                    missing_fields = set(particle_fields or ()) - available_fields
                    if missing_fields:
                        raise ValueError(
                            f"Source particle-series choice {group_name!r} lacks fields: "
                            + ", ".join(sorted(missing_fields))
                        )
                    for field in particle_fields or ():
                        source_group.copy(field, output_group)

            particle_staging.replace(destination_particles)
        else:
            destination_particles.unlink(missing_ok=True)
        series_staging.replace(destination_series)
    except Exception:
        series_staging.unlink(missing_ok=True)
        particle_staging.unlink(missing_ok=True)
        raise


def synchronize_selected_time_series(
    source_collection: Path | None,
    source_collection_argument: str,
    destination_collection: Path,
    selection: DerivedSelection,
) -> None:
    """Synchronize selected time-series material into one lite collection.

    Args:
        source_collection: Local source collection, or ``None`` for SSH input.
        source_collection_argument: Local or SSH-style rsync collection source.
        destination_collection: Local lite collection receiving subsets.
        selection: Validated one-collection derived selection.

    Raises:
        OSError: If source files cannot be transferred or filtered.
        ValueError: If the selection does not match published or stored data.

    Notes:
        Local sources are read directly. Remote sources are staged with one
        selective rsync call because HDF5 datasets cannot be addressed by
        rsync itself. Particle sidecars are not transferred unless requested.
    """
    resolved = resolve_time_series_selection(destination_collection, selection)
    if not resolved:
        return

    with TemporaryDirectory(prefix=".csfdata-derived-", dir=destination_collection) as temporary:
        staged_collection = Path(temporary)
        if source_collection is None:
            command = [
                "rsync",
                "-rt",
                "--partial",
                "--info=progress2",
                "--include=*/",
            ]
            for definition, requested in resolved:
                relative = definition.relative_path.as_posix()
                command.extend(("--include", f"simulations/*/{relative}"))
                if requested.particle_fields:
                    particle_relative = str(Path(relative).with_name("particles.h5"))
                    command.extend(("--include", f"simulations/*/{particle_relative}"))
            command.extend(("--exclude=*", source_collection_argument, f"{staged_collection}/"))
            subprocess.run(command, check=True)
            readable_collection = staged_collection
        else:
            readable_collection = source_collection

        simulations_root = destination_collection / "simulations"
        for destination_simulation in sorted(
            path for path in simulations_root.iterdir() if path.is_dir()
        ):
            source_simulation = (
                readable_collection / "simulations" / destination_simulation.name
            )
            for definition, requested in resolved:
                source_series = source_simulation / definition.relative_path
                if not source_series.is_file():
                    continue
                write_selected_time_series(
                    source_series,
                    destination_simulation / definition.relative_path,
                    definition,
                    requested,
                )


def import_lite_collection(
    source_catalogue: Path | str,
    collection_id: str | None,
    destination: Path,
    overwrite: bool = False,
    progress: Callable[[int, int, str], None] | None = None,
    selection: DerivedSelection | None = None,
) -> LiteImportReport:
    """Import one full-catalogue collection as a local lite catalogue.

    Args:
        source_catalogue: Local catalogue path or ``HOST:PATH`` remote source.
        collection_id: ID of the one collection to mirror. May be ``None``
            when ``selection`` supplies it.
        destination: New or compatible existing local lite catalogue root.
        overwrite: Whether existing local lite files may be replaced.
        progress: Optional callback forwarded to the final local catalogue
            indexing pass after transfer completes.
        selection: Optional fields and choices to retain from selected
            time-series diagnostics. Scalars are always copied completely.

    Returns:
        Summary of the imported lite catalogue and its source provenance.

    Raises:
        FileExistsError: If ``destination`` is not a compatible lite catalogue.
        FileNotFoundError: If a required local source file is absent.
        NotADirectoryError: If a local source catalogue or collection is invalid.
        OSError: If rsync or local indexing fails.

    Notes:
        ``rsync`` transfers the collection while excluding raw data except for
        patterns explicitly declared by the source collection's ``lite.include``
        policy. This preserves metadata, canonical configurations, derived
        products, and small support files without copying raw snapshots.
        Remote transfers use the caller's ordinary SSH credentials. A
        selection excludes complete time-series bundles from the broad rsync
        and replaces only its named standard paths with filtered HDF5 files.
    """
    if selection is not None:
        if collection_id is not None and collection_id != selection.collection_id:
            raise ValueError("--collection differs from the derived selection collection.")
        collection_id = selection.collection_id
    if not collection_id:
        raise ValueError("A collection is required directly or through a selection file.")

    destination = destination.resolve()
    source_text = str(source_catalogue)
    remote_hostname: str | None = None
    source_collection: Path | None = None
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
    destination_collection_path = destination_collection / "collection.yaml"
    # The collection policy and snapshot inventory must stay aligned with the
    # source before ordinary files are copied or a lite registry is rebuilt.
    subprocess.run(
        [
            "rsync",
            "-rt",
            f"{source_collection_argument.rstrip('/')}/collection.yaml",
            str(destination_collection_path),
        ],
        check=True,
    )
    subprocess.run(
        [
            "rsync",
            "-rt",
            f"{source_collection_argument.rstrip('/')}/snapshot-times.sqlite",
            str(destination_collection / "snapshot-times.sqlite"),
        ],
        check=True,
    )
    collection = read_collection_configuration(destination_collection_path)
    # Retain catalogue metadata and derived products, but never bring the raw
    # snapshot payload into a lite copy. --partial makes interrupted transfers resumable.
    command = ["rsync", "-rt", "--partial", "--info=progress2", "--exclude=raw/"]
    if selection is not None:
        # Time-series bundles need content-aware filtering after ordinary
        # metadata and complete scalar diagnostics have been transferred.
        command.append("--exclude=simulations/*/derived/diagnostics/")
    if not overwrite:
        command.append("--ignore-existing")
    command.extend((source_collection_argument, f"{destination_collection}/"))
    subprocess.run(command, check=True)

    if collection.lite_include:
        # Include directories for traversal, then permit only collection-declared
        # support files below each simulation's raw directory.
        command = ["rsync", "-rt", "--partial", "--info=progress2", "--include=*/"]
        for pattern in collection.lite_include:
            command.extend(("--include", f"simulations/*/{pattern}"))
        command.append("--exclude=*")
        if not overwrite:
            command.append("--ignore-existing")
        command.extend((source_collection_argument, f"{destination_collection}/"))
        subprocess.run(command, check=True)

    if selection is not None:
        synchronize_selected_time_series(
            source_collection,
            source_collection_argument,
            destination_collection,
            selection,
        )
        write_derived_selection(selection, destination / "derived-selection.yaml")

    source = LiteSource(
        catalogue_root=source_root,
        hostname=remote_hostname or socket.gethostname(),
        collection_id=collection_id,
        collection_sha256=file_sha256(destination_collection_path),
    )
    manifest_path = destination / "lite.yaml"
    if not manifest_path.exists() or read_lite_source(destination).collection_sha256 != source.collection_sha256:
        # Provenance lets analysis locate raw snapshots later and lets derived
        # results be checked before they are copied back to the full catalogue.
        manifest_path.write_text(
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
    # rsync reports transfer progress itself; the callback covers the separate
    # local indexing stage that follows a successful transfer.
    index_report = index_catalogue(destination, progress=progress)
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
