"""Collection-level configuration for a catalogue simulation campaign."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


_COLLECTION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CollectionConfiguration:
    """Shared import requirements for one destination simulation collection.

    Args:
        collection_id: Stable identifier of the destination collection.
        importer: Name of the code-specific importer selected by the collection.
        config_schema_version: Version expected for each simulation's canonical
            top-level ``config.yaml``.
        required_parameters: Parameter names every imported simulation must
            provide.
        optional_parameters: Parameter names that may be provided when
            applicable.

    Notes:
        This object represents one whole collection, not an individual
        simulation. The selected adapter uses these requirements while
        preparing an import. Names may initially be code-specific, such as
        D-CAF's ``Mstars``. A shared cross-code vocabulary will be added later.
    """

    collection_id: str
    importer: str
    config_schema_version: int
    required_parameters: tuple[str, ...]
    optional_parameters: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate the collection identity and declared parameter vocabulary.

        Raises:
            ValueError: If an identifier is empty, the configuration schema
                version is invalid, or parameter names are duplicated or shared
                between the required and optional lists.
        """
        if not self.collection_id:
            raise ValueError("collection_id must not be empty.")
        if not self.importer:
            raise ValueError("importer must not be empty.")
        if (
            isinstance(self.config_schema_version, bool)
            or not isinstance(self.config_schema_version, int)
            or self.config_schema_version < 1
        ):
            raise ValueError("config_schema_version must be a positive integer.")

        for field_name, names in (
            ("required_parameters", self.required_parameters),
            ("optional_parameters", self.optional_parameters),
        ):
            if any(not name for name in names):
                raise ValueError(f"{field_name} must not contain empty parameter names.")
            if len(names) != len(set(names)):
                raise ValueError(f"{field_name} must not contain duplicate parameter names.")
        shared_parameters = set(self.required_parameters) & set(self.optional_parameters)
        if shared_parameters:
            names = ", ".join(sorted(shared_parameters))
            raise ValueError(f"Parameters cannot be both required and optional: {names}.")


def read_collection_configuration(path: Path) -> CollectionConfiguration:
    """Read a version-1 ``collection.yaml`` file.

    Args:
        path: Collection configuration YAML path.

    Returns:
        The validated configuration for one destination collection.

    Raises:
        FileNotFoundError: If the configuration path does not exist.
        OSError: If the configuration cannot be read.
        ValueError: If the configuration is malformed or uses an unsupported
            schema.
        yaml.YAMLError: If the configuration is not valid YAML.
    """
    with path.open(encoding="utf-8") as stream:
        contents = yaml.safe_load(stream)
    if not isinstance(contents, dict):
        raise ValueError("Collection configuration must contain a YAML mapping.")
    if contents.get("schema_version") != _COLLECTION_SCHEMA_VERSION:
        raise ValueError(
            "Collection configuration must use schema_version "
            f"{_COLLECTION_SCHEMA_VERSION}."
        )

    collection_id = contents.get("id")
    importer = contents.get("importer")
    config_schema_version = contents.get("config_schema_version")
    if not isinstance(collection_id, str) or not collection_id:
        raise ValueError("Collection configuration id must be a non-empty string.")
    if not isinstance(importer, str) or not importer:
        raise ValueError("Collection configuration importer must be a non-empty string.")
    if isinstance(config_schema_version, bool) or not isinstance(config_schema_version, int):
        raise ValueError("Collection configuration config_schema_version must be an integer.")

    parameter_names: dict[str, tuple[str, ...]] = {}
    for field_name in ("required_parameters", "optional_parameters"):
        value = contents.get(field_name)
        if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
            raise ValueError(
                f"Collection configuration {field_name} must be a list of strings."
            )
        parameter_names[field_name] = tuple(value)

    return CollectionConfiguration(
        collection_id=collection_id,
        importer=importer,
        config_schema_version=config_schema_version,
        required_parameters=parameter_names["required_parameters"],
        optional_parameters=parameter_names["optional_parameters"],
    )
