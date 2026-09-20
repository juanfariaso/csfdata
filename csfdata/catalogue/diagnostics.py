"""Published definitions for derived diagnostics in one catalogue collection.

The analysis add-on calculates and stores derived data. This module defines the
small, dependency-free contract that it publishes to a collection so core
catalogue tools can understand available diagnostics without importing the
analysis package.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml

from csfdata.catalogue.configuration import ParameterScalar

DiagnosticKind = Literal["time_series", "scalar"]
"""Storage category for one derived diagnostic."""

_DIAGNOSTICS_SCHEMA_VERSION = 1
# This file is the portable contract between the catalogue and analysis add-on.
# It intentionally describes results instead of containing their values.


@dataclass(frozen=True)
class ChoiceDefinition:
    """One published scientific choice and its default selection.

    Args:
        name: Stable machine-readable choice name, such as ``"center"``.
        description: Human-readable scientific meaning of the choice.
        values: Allowed stable values.
        default: Value used when no global or diagnostic-specific override is
            supplied.
    """

    name: str
    description: str
    values: tuple[str, ...]
    default: str

    def __post_init__(self) -> None:
        """Validate a published choice definition.

        Raises:
            ValueError: If any identifier is empty, values are duplicated, or
                the default is not permitted.
        """
        # Check the stable identity before validating the values it names.
        if not self.name:
            raise ValueError("Choice name must not be empty.")
        if not self.description:
            raise ValueError(f"Choice {self.name!r} description must not be empty.")
        if not self.values or any(not value for value in self.values):
            raise ValueError(f"Choice {self.name!r} must define non-empty values.")
        if len(set(self.values)) != len(self.values):
            raise ValueError(f"Choice {self.name!r} must not define duplicate values.")
        if self.default not in self.values:
            raise ValueError(f"Choice {self.name!r} default must be an allowed value.")


@dataclass(frozen=True)
class DiagnosticField:
    """One named value produced by a derived diagnostic.

    Args:
        name: Stable machine-readable output field name.
        description: Human-readable meaning of the output value.
        unit: Canonical unit label, or ``None`` when the value is dimensionless
            or textual.
    """

    name: str
    description: str
    unit: str | None = None

    def __post_init__(self) -> None:
        """Validate an output-field declaration.

        Raises:
            ValueError: If the name, description, or optional unit is invalid.
        """
        # Output fields are later used as stable queryable result names.
        if not self.name:
            raise ValueError("Diagnostic field name must not be empty.")
        if not self.description:
            raise ValueError(
                f"Diagnostic field {self.name!r} description must not be empty."
            )
        if self.unit is not None and not self.unit:
            raise ValueError(f"Diagnostic field {self.name!r} has an invalid unit.")


@dataclass(frozen=True)
class ScalarValue:
    """One scalar value stored in a simulation's scalar diagnostics.

    Args:
        name: Stable diagnostic output-field name.
        value: Queryable scalar value in the field's canonical unit.
        unit: Canonical unit label, or ``None`` for dimensionless or textual
            values.

    Notes:
        ``value`` and ``unit`` deliberately use the same representation as
        canonical configuration parameters. A diagnostic version and choices
        identify how the value was calculated, so configuration provenance is
        not repeated here.
    """

    name: str
    value: ParameterScalar
    unit: str | None

    def __post_init__(self) -> None:
        """Validate one scalar diagnostic value.

        Raises:
            ValueError: If the name, scalar value, or optional unit is invalid.
        """
        # Scalar values use the catalogue's shared scalar vocabulary so they
        # can be indexed and filtered exactly like configuration parameters.
        if not self.name:
            raise ValueError("Scalar value name must not be empty.")
        if not isinstance(self.value, (str, int, float, bool, type(None))):
            raise ValueError(f"Scalar value {self.name!r} must be a scalar.")
        if self.value is None:
            raise ValueError(f"Scalar value {self.name!r} must not be unknown.")
        if self.unit is not None and not self.unit:
            raise ValueError(f"Scalar value {self.name!r} has an invalid unit.")


@dataclass(frozen=True)
class ScalarDiagnosticResult:
    """One choice-specific scalar result for a diagnostic version.

    Args:
        diagnostic_name: Published diagnostic name.
        diagnostic_version: Published diagnostic version identifier.
        choices: Concrete choice selections affecting this result.
        values: Scalar diagnostic outputs.
    """

    diagnostic_name: str
    diagnostic_version: str
    choices: tuple[tuple[str, str], ...]
    values: tuple[ScalarValue, ...]

    def __post_init__(self) -> None:
        """Validate result identity, choice selections, and output names.

        Raises:
            ValueError: If required identities are empty or names are repeated.
        """
        # These identifiers select the declaration that gives this result its
        # scientific meaning and expected unit schema.
        if not self.diagnostic_name or not self.diagnostic_version:
            raise ValueError("Scalar diagnostic name and version must not be empty.")
        choice_names = [name for name, value in self.choices]
        if any(not name or not value for name, value in self.choices):
            raise ValueError("Scalar diagnostic choices must have non-empty names and values.")
        if len(choice_names) != len(set(choice_names)):
            raise ValueError("Scalar diagnostic choices must not contain duplicate names.")
        value_names = [value.name for value in self.values]
        if not value_names or len(value_names) != len(set(value_names)):
            raise ValueError("Scalar diagnostic values must be non-empty and have unique names.")

    def validate_against(self, diagnostics: CollectionDiagnostics) -> None:
        """Validate this result against its published collection definition.

        Args:
            diagnostics: Published choices and diagnostic schemas for the
                containing collection.

        Raises:
            ValueError: If the diagnostic, version, choices, fields, or units
                disagree with the published collection declaration.
        """
        # Find the exact definition first; result names alone are not enough
        # because different versions may have different fields or meanings.
        definition = next(
            (
                candidate
                for candidate in diagnostics.diagnostics
                if candidate.name == self.diagnostic_name
                and candidate.version == self.diagnostic_version
            ),
            None,
        )
        if definition is None or definition.kind != "scalar":
            raise ValueError(
                "Scalar result does not match a published scalar diagnostic: "
                f"{self.diagnostic_name} {self.diagnostic_version}."
            )
        choices = dict(self.choices)
        if set(choices) != set(definition.choices):
            raise ValueError("Scalar result choices do not match its diagnostic definition.")
        allowed_choices = {choice.name: choice for choice in diagnostics.choices}
        for name, value in choices.items():
            if value not in allowed_choices[name].values:
                raise ValueError(f"Scalar result has an invalid choice value: {name}={value}.")

        # Require every declared output so an incomplete fit cannot appear as a
        # scientifically complete result in later catalogue queries.
        fields = {field.name: field for field in definition.fields}
        if {value.name for value in self.values} != set(fields):
            raise ValueError("Scalar result values do not match its diagnostic definition.")
        for value in self.values:
            if value.unit != fields[value.name].unit:
                raise ValueError(f"Scalar value {value.name!r} has the wrong unit.")

    def uses_default_choices(self, diagnostics: CollectionDiagnostics) -> bool:
        """Return whether this result uses every published default choice.

        Args:
            diagnostics: Published choices for the containing collection.

        Returns:
            ``True`` when every choice selection equals its registered default.
        """
        defaults = {choice.name: choice.default for choice in diagnostics.choices}
        return all(defaults[name] == value for name, value in self.choices)


@dataclass(frozen=True)
class SimulationScalarDiagnostics:
    """All scalar diagnostic results for one simulation.

    Args:
        results: Choice-specific results from one or more diagnostics.
    """

    results: tuple[ScalarDiagnosticResult, ...]

    def __post_init__(self) -> None:
        """Validate that each diagnostic and choice combination occurs once.

        Raises:
            ValueError: If two results would occupy the same summary location.
        """
        # One diagnostic version can store several choice combinations, but a
        # duplicate combination would make later replacement ambiguous.
        keys = [
            (result.diagnostic_name, result.diagnostic_version, result.choices)
            for result in self.results
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("Simulation scalar diagnostics contain duplicate results.")


@dataclass(frozen=True)
class DiagnosticRequirement:
    """One completed diagnostic version required by another diagnostic.

    Args:
        name: Stable required diagnostic name.
        version: Required diagnostic version identifier.
    """

    name: str
    version: str

    def __post_init__(self) -> None:
        """Validate the required diagnostic identity.

        Raises:
            ValueError: If the diagnostic name or version is empty.
        """
        # A requirement must identify exactly one published diagnostic version.
        if not self.name or not self.version:
            raise ValueError("Diagnostic requirement name and version must not be empty.")


@dataclass(frozen=True)
class DiagnosticDefinition:
    """Published definition and storage location for one diagnostic version.

    Args:
        name: Stable diagnostic name, such as ``"lagrangian_radii"``.
        version: Stable diagnostic version identifier, such as ``"v1"``.
        kind: ``"time_series"`` for time-evolved data or ``"scalar"`` for
            simulation-level values.
        description: Human-readable scientific purpose of the diagnostic.
        relative_path: Result file location relative to a simulation root.
        fields: Values provided by the diagnostic.
        choices: Registered choice names that affect the result.
        requires: Completed diagnostic versions required before this diagnostic
            can be calculated.

    Notes:
        Time-series diagnostics are normally stored in HDF5. Scalar diagnostics
        may share one YAML file with other scalar results. ``relative_path``
        identifies that file; the diagnostic name and version identify its
        section within it.
    """

    name: str
    version: str
    kind: DiagnosticKind
    description: str
    relative_path: PurePosixPath
    fields: tuple[DiagnosticField, ...]
    choices: tuple[str, ...] = ()
    requires: tuple[DiagnosticRequirement, ...] = ()

    def __post_init__(self) -> None:
        """Validate a diagnostic definition independent of a collection.

        Raises:
            ValueError: If identifiers, storage path, fields, or choice names
                are invalid.
        """
        # Start with the stable name/version identity used in catalogue YAML.
        if not self.name or not self.version:
            raise ValueError("Diagnostic name and version must not be empty.")
        if self.kind not in {"time_series", "scalar"}:
            raise ValueError("Diagnostic kind must be 'time_series' or 'scalar'.")
        if not self.description:
            raise ValueError(f"Diagnostic {self.name!r} description must not be empty.")
        if (
            self.relative_path.is_absolute()
            or ".." in self.relative_path.parts
            or not self.relative_path.parts
            or self.relative_path.parts[0] != "derived"
        ):
            # Definitions must remain portable when a collection is copied.
            raise ValueError("Diagnostic paths must be safe paths below derived/.")
        # Field names identify values within one diagnostic result, so repeats
        # would make a stored result ambiguous.
        field_names = [field.name for field in self.fields]
        if not field_names or len(field_names) != len(set(field_names)):
            raise ValueError("Diagnostic fields must be non-empty and have unique names.")
        if any(not choice for choice in self.choices):
            raise ValueError("Diagnostic choices must not contain empty names.")
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("Diagnostic choices must not contain duplicates.")
        requirements = [(requirement.name, requirement.version) for requirement in self.requires]
        if len(requirements) != len(set(requirements)):
            raise ValueError("Diagnostic requirements must not contain duplicates.")


@dataclass(frozen=True)
class CollectionDiagnostics:
    """All published choices and diagnostic definitions for one collection.

    Args:
        choices: Available scientific choices, including defaults.
        diagnostics: Available derived diagnostic versions.

    Notes:
        This is the authoritative description of derived data available in a
        collection. Result values remain in each simulation's ``derived/``
        directory and are not duplicated here.
    """

    choices: tuple[ChoiceDefinition, ...]
    diagnostics: tuple[DiagnosticDefinition, ...]

    def __post_init__(self) -> None:
        """Validate unique names and references across collection definitions.

        Raises:
            ValueError: If choices or diagnostics are duplicated, or a
                diagnostic uses an unregistered choice.
        """
        # First establish the collection-wide choice vocabulary.
        choice_names = [choice.name for choice in self.choices]
        if len(choice_names) != len(set(choice_names)):
            raise ValueError("Collection diagnostics contain duplicate choice names.")
        # Then ensure a name/version pair identifies exactly one definition.
        diagnostic_keys = [
            (diagnostic.name, diagnostic.version) for diagnostic in self.diagnostics
        ]
        if len(diagnostic_keys) != len(set(diagnostic_keys)):
            raise ValueError("Collection diagnostics contain duplicate diagnostic versions.")
        available_choices = set(choice_names)
        available_diagnostics = set(diagnostic_keys)
        for diagnostic in self.diagnostics:
            # A diagnostic may only refer to choices published with this collection.
            unknown_choices = set(diagnostic.choices) - available_choices
            if unknown_choices:
                names = ", ".join(sorted(unknown_choices))
                raise ValueError(
                    f"Diagnostic {diagnostic.name!r} uses unregistered choices: {names}."
                )
            # Requirements must be published too, so runners can report a
            # missing prerequisite without guessing which version is needed.
            missing_requirements = {
                (requirement.name, requirement.version)
                for requirement in diagnostic.requires
            } - available_diagnostics
            if missing_requirements:
                names = ", ".join(
                    f"{name} {version}" for name, version in sorted(missing_requirements)
                )
                raise ValueError(
                    f"Diagnostic {diagnostic.name!r} uses unpublished requirements: {names}."
                )


def collection_diagnostics_path(collection_root: Path) -> Path:
    """Return the standard published-diagnostics path for one collection.

    Args:
        collection_root: Collection directory below ``collections/``.

    Returns:
        The collection's ``diagnostics.yaml`` path.
    """
    return collection_root / "diagnostics.yaml"


def simulation_scalar_diagnostics_path(simulation_root: Path) -> Path:
    """Return the standard scalar-diagnostics path for one simulation.

    Args:
        simulation_root: Imported simulation directory containing ``derived/``.

    Returns:
        The simulation's ``derived/scalar_diagnostics.yaml`` path.
    """
    return simulation_root / "derived" / "scalar_diagnostics.yaml"


def write_collection_diagnostics(
    diagnostics: CollectionDiagnostics,
    path: Path,
) -> None:
    """Write published diagnostic definitions as versioned YAML.

    Args:
        diagnostics: Validated collection diagnostic definitions to publish.
        path: Destination ``diagnostics.yaml`` path. Its parent must exist.

    Raises:
        OSError: If the definitions cannot be written.
    """
    # Write one small declaration file. The much larger numerical results stay
    # in each simulation and are only located by this metadata.
    contents = {
        "schema_version": _DIAGNOSTICS_SCHEMA_VERSION,
        # Choices are indexed by name so query tools can resolve defaults
        # without importing csfdata_analysis.
        "choices": {
            choice.name: {
                "description": choice.description,
                "values": list(choice.values),
                "default": choice.default,
            }
            for choice in diagnostics.choices
        },
        "diagnostics": {
            # The name/version nesting permits several compatible versions of
            # one diagnostic while preserving declaration order in YAML.
            name: {
                diagnostic.version: {
                    "kind": diagnostic.kind,
                    "description": diagnostic.description,
                    "path": diagnostic.relative_path.as_posix(),
                    "fields": {
                        field.name: {
                            "description": field.description,
                            "unit": field.unit,
                        }
                        for field in diagnostic.fields
                    },
                    "choices": list(diagnostic.choices),
                    "requires": [
                        {"name": requirement.name, "version": requirement.version}
                        for requirement in diagnostic.requires
                    ],
                }
                for diagnostic in diagnostics.diagnostics
                if diagnostic.name == name
            }
            for name in dict.fromkeys(diagnostic.name for diagnostic in diagnostics.diagnostics)
        },
    }
    # Preserve declaration order to keep the file convenient for human review.
    path.write_text(
        yaml.safe_dump(contents, allow_unicode=False, sort_keys=False),
        encoding="utf-8",
    )


def read_collection_diagnostics(path: Path) -> CollectionDiagnostics:
    """Read published diagnostic definitions from a collection YAML file.

    Args:
        path: Collection ``diagnostics.yaml`` path.

    Returns:
        Validated collection diagnostic definitions.

    Raises:
        FileNotFoundError: If the definitions file does not exist.
        OSError: If the definitions file cannot be read.
        ValueError: If the YAML does not follow schema version 1.
        yaml.YAMLError: If the file is not valid YAML.
    """
    # Load the complete declaration first, then validate its top-level schema
    # before turning any nested YAML mappings into typed objects.
    with path.open(encoding="utf-8") as stream:
        contents = yaml.safe_load(stream)
    if not isinstance(contents, dict):
        raise ValueError("Collection diagnostics must contain a YAML mapping.")
    if contents.get("schema_version") != _DIAGNOSTICS_SCHEMA_VERSION:
        raise ValueError(
            "Collection diagnostics must use schema_version "
            f"{_DIAGNOSTICS_SCHEMA_VERSION}."
        )
    choices_data = contents.get("choices")
    diagnostics_data = contents.get("diagnostics")
    if not isinstance(choices_data, dict) or not isinstance(diagnostics_data, dict):
        raise ValueError("Collection diagnostics must define choices and diagnostics mappings.")

    # Parse choices before diagnostics because diagnostics may reference them.
    choices: list[ChoiceDefinition] = []
    for name, data in choices_data.items():
        if not isinstance(name, str) or not isinstance(data, dict):
            raise ValueError("Collection diagnostics contains an invalid choice definition.")
        description = data.get("description")
        values = data.get("values")
        default = data.get("default")
        if (
            not isinstance(description, str)
            or not isinstance(values, list)
            or not all(isinstance(value, str) for value in values)
            or not isinstance(default, str)
        ):
            raise ValueError(f"Choice {name!r} has invalid fields.")
        choices.append(ChoiceDefinition(name, description, tuple(values), default))

    # Rebuild every diagnostic version from its nested name/version mapping.
    diagnostics: list[DiagnosticDefinition] = []
    for name, versions in diagnostics_data.items():
        if not isinstance(name, str) or not isinstance(versions, dict):
            raise ValueError("Collection diagnostics contains an invalid diagnostic mapping.")
        for version, data in versions.items():
            if not isinstance(version, str) or not isinstance(data, dict):
                raise ValueError(f"Diagnostic {name!r} has an invalid version definition.")
            fields_data = data.get("fields")
            choice_names = data.get("choices")
            requirements_data = data.get("requires", [])
            if (
                not isinstance(fields_data, dict)
                or not isinstance(choice_names, list)
                or not isinstance(requirements_data, list)
            ):
                raise ValueError(f"Diagnostic {name!r} has invalid fields, choices, or requirements.")
            # Parse the output schema before constructing the parent diagnostic.
            fields: list[DiagnosticField] = []
            for field_name, field_data in fields_data.items():
                if not isinstance(field_name, str) or not isinstance(field_data, dict):
                    raise ValueError(f"Diagnostic {name!r} has an invalid output field.")
                description = field_data.get("description")
                unit = field_data.get("unit")
                if not isinstance(description, str) or not isinstance(unit, (str, type(None))):
                    raise ValueError(f"Diagnostic field {field_name!r} has invalid fields.")
                fields.append(DiagnosticField(field_name, description, unit))
            kind = data.get("kind")
            description = data.get("description")
            relative_path = data.get("path")
            if (
                kind not in {"time_series", "scalar"}
                or not isinstance(description, str)
                or not isinstance(relative_path, str)
                or not all(isinstance(choice, str) for choice in choice_names)
            ):
                raise ValueError(f"Diagnostic {name!r} has invalid required fields.")
            requirements: list[DiagnosticRequirement] = []
            for requirement_data in requirements_data:
                if not isinstance(requirement_data, dict):
                    raise ValueError(f"Diagnostic {name!r} has an invalid requirement.")
                requirement_name = requirement_data.get("name")
                requirement_version = requirement_data.get("version")
                if not isinstance(requirement_name, str) or not isinstance(requirement_version, str):
                    raise ValueError(f"Diagnostic {name!r} has an invalid requirement.")
                requirements.append(DiagnosticRequirement(requirement_name, requirement_version))
            # Reconstruct immutable definitions so their normal validation is
            # shared by programmatic and YAML-loaded catalogue declarations.
            diagnostics.append(
                DiagnosticDefinition(
                    name,
                    version,
                    kind,
                    description,
                    PurePosixPath(relative_path),
                    tuple(fields),
                    tuple(choice_names),
                    tuple(requirements),
                )
            )
    # Final collection validation checks cross-references to the choices above.
    return CollectionDiagnostics(tuple(choices), tuple(diagnostics))


def write_simulation_scalar_diagnostics(
    scalar_diagnostics: SimulationScalarDiagnostics,
    diagnostics: CollectionDiagnostics,
    path: Path,
) -> None:
    """Write validated scalar diagnostic results as versioned YAML.

    Args:
        scalar_diagnostics: Per-simulation scalar results to save.
        diagnostics: Published collection definitions used for validation.
        path: Destination ``derived/scalar_diagnostics.yaml`` path. Its parent must exist.

    Raises:
        ValueError: If a result disagrees with the published diagnostic schema.
        OSError: If the scalar diagnostics cannot be written.
    """
    # Validate every result before replacing a file, preventing a partial YAML
    # record from becoming the source of truth for later indexing.
    for result in scalar_diagnostics.results:
        result.validate_against(diagnostics)

    contents = {
        "schema_version": 1,
        "diagnostics": {
            name: {
                version: [
                    {
                        "choices": dict(result.choices),
                        "values": {
                            value.name: {"value": value.value, "unit": value.unit}
                            for value in result.values
                        },
                    }
                    for result in scalar_diagnostics.results
                    if result.diagnostic_name == name
                    and result.diagnostic_version == version
                ]
                for version in dict.fromkeys(
                    result.diagnostic_version
                    for result in scalar_diagnostics.results
                    if result.diagnostic_name == name
                )
            }
            for name in dict.fromkeys(
                result.diagnostic_name for result in scalar_diagnostics.results
            )
        },
    }
    # Stable ordering keeps scalar-diagnostic diffs readable when a result is updated.
    path.write_text(
        yaml.safe_dump(contents, allow_unicode=False, sort_keys=False),
        encoding="utf-8",
    )


def read_simulation_scalar_diagnostics(
    path: Path,
    diagnostics: CollectionDiagnostics,
) -> SimulationScalarDiagnostics:
    """Read and validate scalar diagnostic results for one simulation.

    Args:
        path: Simulation ``derived/scalar_diagnostics.yaml`` path.
        diagnostics: Published collection definitions used for validation.

    Returns:
        The validated per-simulation scalar diagnostics.

    Raises:
        FileNotFoundError: If the scalar diagnostics do not exist.
        OSError: If the scalar diagnostics cannot be read.
        ValueError: If the YAML is malformed or disagrees with the collection
            diagnostic definitions.
        yaml.YAMLError: If the file is not valid YAML.
    """
    # Read the whole YAML document before reconstructing typed result records.
    with path.open(encoding="utf-8") as stream:
        contents = yaml.safe_load(stream)
    if not isinstance(contents, dict) or contents.get("schema_version") != 1:
        raise ValueError("Simulation scalar diagnostics must use schema_version 1.")
    diagnostics_data = contents.get("diagnostics")
    if not isinstance(diagnostics_data, dict):
        raise ValueError("Simulation scalar diagnostics must contain a diagnostics mapping.")

    results: list[ScalarDiagnosticResult] = []
    for diagnostic_name, versions in diagnostics_data.items():
        if not isinstance(diagnostic_name, str) or not isinstance(versions, dict):
            raise ValueError("Simulation scalar diagnostics contains an invalid diagnostic mapping.")
        for diagnostic_version, entries in versions.items():
            if not isinstance(diagnostic_version, str) or not isinstance(entries, list):
                raise ValueError("Simulation scalar diagnostics contains an invalid version mapping.")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("Scalar diagnostic result entries must be mappings.")
                choices = entry.get("choices")
                values = entry.get("values")
                if not isinstance(choices, dict) or not isinstance(values, dict):
                    raise ValueError("Scalar diagnostic results need choices and values mappings.")
                if not all(isinstance(name, str) and isinstance(value, str) for name, value in choices.items()):
                    raise ValueError("Scalar diagnostic choices must map strings to strings.")

                # Parse the familiar value/unit records before validating them
                # against the diagnostic field declarations.
                parsed_values: list[ScalarValue] = []
                for name, data in values.items():
                    if not isinstance(name, str) or not isinstance(data, dict):
                        raise ValueError("Scalar diagnostics contains an invalid value record.")
                    if "value" not in data or "unit" not in data:
                        raise ValueError(f"Scalar value {name!r} needs value and unit fields.")
                    unit = data["unit"]
                    if not isinstance(unit, (str, type(None))):
                        raise ValueError(f"Scalar value {name!r} has an invalid unit.")
                    parsed_values.append(ScalarValue(name, data["value"], unit))
                result = ScalarDiagnosticResult(
                    diagnostic_name,
                    diagnostic_version,
                    tuple(choices.items()),
                    tuple(parsed_values),
                )
                result.validate_against(diagnostics)
                results.append(result)
    return SimulationScalarDiagnostics(tuple(results))
