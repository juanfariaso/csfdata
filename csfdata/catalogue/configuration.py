"""Canonical scientific configuration for one imported simulation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

import yaml

from csfdata.units import UnitConverter


ParameterProvenance: TypeAlias = Literal[
    "explicit", "inferred", "unknown", "not_applicable"
]
"""How confidently a configuration parameter is known for one simulation."""

ParameterScalar: TypeAlias = str | int | float | bool | None
"""Scalar values supported by the first canonical configuration schema."""

_CONFIGURATION_SCHEMA_VERSION = 1
_KNOWN_PARAMETER_PROVENANCE = {
    "explicit",
    "inferred",
    "unknown",
    "not_applicable",
}


@dataclass(frozen=True)
class ConfigurationParameter:
    """One named scientific parameter in a canonical simulation configuration.

    Args:
        name: Standard or code-specific parameter name.
        value: Scalar parameter value, or ``None`` when it is not known or does
            not apply.
        unit: Unit label, or ``None`` for dimensionless or non-numeric values.
        provenance: Whether the value is explicit, inferred, unknown, or not
            applicable.
        note: Optional concise explanation, especially useful for inferred
            values.

    Notes:
        This object represents one parameter, not a whole simulation. A known
        parameter has ``explicit`` or ``inferred`` provenance and a value.
        ``unknown`` and ``not_applicable`` parameters intentionally have no
        value so that missing information is never silently guessed.
    """

    name: str
    value: ParameterScalar
    unit: str | None
    provenance: ParameterProvenance
    note: str | None = None

    def __post_init__(self) -> None:
        """Validate parameter identity, value type, units, and provenance.

        Raises:
            ValueError: If fields are inconsistent with the configuration
                schema.
        """
        if not self.name:
            raise ValueError("Parameter name must not be empty.")
        if not isinstance(self.value, (str, int, float, bool, type(None))):
            raise ValueError(f"Parameter {self.name} must have a scalar value.")
        if self.unit is not None and (not isinstance(self.unit, str) or not self.unit):
            raise ValueError(f"Parameter {self.name} has an invalid unit.")
        if self.provenance not in _KNOWN_PARAMETER_PROVENANCE:
            raise ValueError(f"Parameter {self.name} has invalid provenance.")
        if self.provenance in {"explicit", "inferred"} and self.value is None:
            raise ValueError(f"Known parameter {self.name} must have a value.")
        if self.provenance in {"unknown", "not_applicable"} and self.value is not None:
            raise ValueError(f"Unknown or inapplicable parameter {self.name} must have no value.")
        if self.note is not None and (not isinstance(self.note, str) or not self.note):
            raise ValueError(f"Parameter {self.name} has an invalid note.")

    @property
    def is_known(self) -> bool:
        """Return whether this parameter has an explicit or inferred value.

        Returns:
            ``True`` for explicit or inferred parameters; otherwise, ``False``.
        """
        return self.provenance in {"explicit", "inferred"}


@dataclass(frozen=True)
class SimulationConfiguration:
    """Canonical scientific configuration for exactly one managed simulation.

    Args:
        parameters: Standard catalogue parameters shared across collections.
        code_parameters: Additional parameters whose meaning is specific to the
            source simulation code or collection.

    Notes:
        This object represents the top-level catalogue ``config.yaml`` for one
        simulation. It is separate from source files in ``raw/``, which remain
        unchanged. Standard parameters support later cross-collection queries;
        code parameters preserve useful context without becoming part of the
        shared vocabulary.
    """

    parameters: tuple[ConfigurationParameter, ...]
    code_parameters: tuple[ConfigurationParameter, ...] = ()

    def __post_init__(self) -> None:
        """Validate unique parameter names in the two configuration sections.

        Raises:
            ValueError: If a parameter name is duplicated or occurs in both
                standard and code-specific sections.
        """
        for section_name, section_parameters in (
            ("parameters", self.parameters),
            ("code_parameters", self.code_parameters),
        ):
            names = [parameter.name for parameter in section_parameters]
            if len(names) != len(set(names)):
                raise ValueError(
                    f"Simulation configuration {section_name} has duplicate names."
                )
        shared_names = {parameter.name for parameter in self.parameters} & {
            parameter.name for parameter in self.code_parameters
        }
        if shared_names:
            names = ", ".join(sorted(shared_names))
            raise ValueError(f"Parameters cannot be standard and code-specific: {names}.")

    def parameter(self, name: str) -> ConfigurationParameter | None:
        """Return one standard or code-specific parameter by name.

        Args:
            name: Parameter name to find.

        Returns:
            The matching parameter, or ``None`` when it is absent.
        """
        return next(
            (
                parameter
                for parameter in (*self.parameters, *self.code_parameters)
                if parameter.name == name
            ),
            None,
        )

    def missing_required_parameters(self, names: tuple[str, ...]) -> tuple[str, ...]:
        """Return required parameter names that are absent or not known.

        Args:
            names: Required standard parameter names from a collection.

        Returns:
            Required names that are not present with an explicit or inferred
            value in either parameter section.
        """
        return tuple(
            name
            for name in names
            if (parameter := self.parameter(name)) is None or not parameter.is_known
        )


def extract_parameters(
    path: Path,
    format: str = "yaml",
) -> tuple[ConfigurationParameter, ...]:
    """Extract all supported scalar parameters from one source configuration.

    Args:
        path: Source configuration file to read.
        format: Source configuration format. Only ``"yaml"`` is supported
            currently.

    Returns:
        Every supported configuration field as a canonical parameter, in the
        order declared by the source configuration.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        OSError: If the configuration file cannot be read.
        ValueError: If the format is unsupported, YAML does not contain a flat
            mapping, or a field cannot be represented by the configuration
            schema.
        yaml.YAMLError: If a YAML configuration is not valid YAML.

    Notes:
        This function extracts every available parameter. A collection later
        decides which extracted parameters are required for catalogue import.
        New source formats can be added here without changing individual
        simulation adapters.
    """
    if format != "yaml":
        raise ValueError(f"Unsupported configuration format: {format}.")
    with path.open(encoding="utf-8") as stream:
        contents = yaml.safe_load(stream)
    if not isinstance(contents, dict):
        raise ValueError("YAML configuration must contain a top-level mapping.")
    parameters: list[ConfigurationParameter] = []
    converter = UnitConverter()
    for name, value in contents.items():
        if not isinstance(name, str) or not name:
            raise ValueError("YAML configuration has an invalid parameter name.")
        if value is None:
            parameters.append(ConfigurationParameter(name, None, None, "unknown"))
        elif isinstance(value, str):
            fields = value.split()
            if len(fields) == 2:
                try:
                    float(fields[0])
                except ValueError:
                    parameters.append(ConfigurationParameter(name, value, None, "explicit"))
                else:
                    quantity = converter.parse_string(value)
                    parameters.append(
                        ConfigurationParameter(name, quantity.value, quantity.unit, "explicit")
                    )
            else:
                parameters.append(ConfigurationParameter(name, value, None, "explicit"))
        elif isinstance(value, (bool, int, float)):
            parameters.append(ConfigurationParameter(name, value, None, "explicit"))
        else:
            raise ValueError(
                f"YAML configuration parameter {name} is not a supported scalar."
            )
    return tuple(parameters)


def write_simulation_configuration(configuration: SimulationConfiguration, path: Path) -> None:
    """Write a canonical simulation configuration as versioned YAML.

    Args:
        configuration: Configuration to save as a simulation's top-level
            ``config.yaml``.
        path: Destination YAML path. Its parent directory must already exist.

    Raises:
        OSError: If the configuration cannot be written.
    """
    contents: dict[str, object] = {"schema_version": _CONFIGURATION_SCHEMA_VERSION}
    for section_name, parameters in (
        ("parameters", configuration.parameters),
        ("code_parameters", configuration.code_parameters),
    ):
        mapping: dict[str, dict[str, ParameterScalar | str]] = {}
        for parameter in parameters:
            value: dict[str, ParameterScalar | str] = {
                "value": parameter.value,
                "unit": parameter.unit,
                "provenance": parameter.provenance,
            }
            if parameter.note is not None:
                value["note"] = parameter.note
            mapping[parameter.name] = value
        contents[section_name] = mapping
    path.write_text(
        yaml.safe_dump(contents, allow_unicode=False, sort_keys=False),
        encoding="utf-8",
    )


def read_simulation_configuration(path: Path) -> SimulationConfiguration:
    """Read a version-1 canonical simulation ``config.yaml`` file.

    Args:
        path: Top-level catalogue configuration YAML path.

    Returns:
        The validated configuration for one simulation.

    Raises:
        FileNotFoundError: If the configuration does not exist.
        OSError: If the configuration cannot be read.
        ValueError: If the configuration is malformed or uses an unsupported
            schema.
        yaml.YAMLError: If the configuration is not valid YAML.
    """
    with path.open(encoding="utf-8") as stream:
        contents = yaml.safe_load(stream)
    if not isinstance(contents, dict):
        raise ValueError("Simulation configuration must contain a YAML mapping.")
    if contents.get("schema_version") != _CONFIGURATION_SCHEMA_VERSION:
        raise ValueError(
            "Simulation configuration must use schema_version "
            f"{_CONFIGURATION_SCHEMA_VERSION}."
        )

    sections: dict[str, tuple[ConfigurationParameter, ...]] = {}
    for section_name in ("parameters", "code_parameters"):
        section = contents.get(section_name)
        if not isinstance(section, dict):
            raise ValueError(f"Simulation configuration {section_name} must be a mapping.")

        parameters: list[ConfigurationParameter] = []
        for name, data in section.items():
            if not isinstance(name, str) or not name:
                raise ValueError(
                    f"Simulation configuration {section_name} has an invalid parameter name."
                )
            if not isinstance(data, dict):
                raise ValueError(f"Simulation configuration parameter {name} must be a mapping.")
            if "value" not in data or "provenance" not in data:
                raise ValueError(
                    f"Simulation configuration parameter {name} must define value and provenance."
                )
            provenance = data["provenance"]
            if not isinstance(provenance, str):
                raise ValueError(
                    f"Simulation configuration parameter {name} has invalid provenance."
                )
            parameters.append(
                ConfigurationParameter(
                    name,
                    data["value"],
                    data.get("unit"),
                    provenance,
                    data.get("note"),
                )
            )
        sections[section_name] = tuple(parameters)

    return SimulationConfiguration(
        parameters=sections["parameters"],
        code_parameters=sections["code_parameters"],
    )
