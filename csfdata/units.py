"""Small dependency-free conversions for catalogue configuration quantities.

This module is not meant to replace AMUSE or Astropy units. It only normalizes
and converts the small, explicit set of units used by the catalogue
configuration schema, so that importing data does not require either scientific
runtime dependency.

Note that the catalogue assumes astrophysical units. This module is just for
adapters to use.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Quantity:
    """One numeric value expressed in a normalized catalogue unit.

    Args:
        value: Numeric quantity value in ``unit``.
        unit: Normalized catalogue unit label.

    Notes:
        This is a lightweight configuration value, not a general physical
        quantity implementation. Use AMUSE or Astropy for scientific unit
        arithmetic, compound units, and dimensional analysis.
    """

    value: float
    unit: str


class UnitConverter:
    """Normalize a small, explicit set of astrophysical catalogue units.

    Supported dimensions are time, length, mass, and velocity. The canonical
    units are ``Myr``, ``pc``, ``Msun``, and ``km/s`` respectively.

    Notes:
        This class exists only to keep catalogue configuration parsing
        self-consistent and dependency-free. It is not meant to replace AMUSE
        or Astropy unit handling. Unsupported, compound, or incompatible units
        raise ``ValueError`` instead of being guessed.
    """

    _UNIT_DEFINITIONS = {
        "yr": {"dimension": "time", "canonical_unit": "Myr", "factor": 1.0e-6},
        "kyr": {"dimension": "time", "canonical_unit": "Myr", "factor": 1.0e-3},
        "Myr": {"dimension": "time", "canonical_unit": "Myr", "factor": 1.0},
        "Gyr": {"dimension": "time", "canonical_unit": "Myr", "factor": 1.0e3},
        "pc": {"dimension": "length", "canonical_unit": "pc", "factor": 1.0},
        "parsec": {"dimension": "length", "canonical_unit": "pc", "factor": 1.0},
        "kpc": {"dimension": "length", "canonical_unit": "pc", "factor": 1.0e3},
        "Msun": {"dimension": "mass", "canonical_unit": "Msun", "factor": 1.0},
        "MSun": {"dimension": "mass", "canonical_unit": "Msun", "factor": 1.0},
        "km/s": {"dimension": "velocity", "canonical_unit": "km/s", "factor": 1.0},
    }

    def normalize_unit(self, unit: str) -> str:
        """Return the canonical catalogue unit for one supported unit label.

        Args:
            unit: Supported source unit or accepted alias.

        Returns:
            Canonical unit label for the unit's physical dimension.

        Raises:
            ValueError: If ``unit`` is unknown or empty.
        """
        if not isinstance(unit, str) or not unit:
            raise ValueError("Unit must be a non-empty string.")
        try:
            return str(self._UNIT_DEFINITIONS[unit]["canonical_unit"])
        except KeyError as error:
            raise ValueError(f"Unsupported catalogue unit: {unit}.") from error

    def parse_string(self, value: object) -> Quantity:
        """Parse a string such as ``"3.0 Myr"`` into a quantity.

        Args:
            value: String expected to contain a number and unit.

        Returns:
            Quantity normalized to the canonical unit for its dimension.

        Raises:
            ValueError: If the YAML value is not a two-token numeric quantity
                with one supported unit.
        """
        if not isinstance(value, str):
            raise ValueError("A YAML quantity must be a string such as '3.0 Myr'.")
        fields = value.split()
        if len(fields) != 2:
            raise ValueError("A YAML quantity must contain exactly a value and unit.")
        try:
            numeric_value = float(fields[0])
        except ValueError as error:
            raise ValueError("A YAML quantity must begin with a numeric value.") from error
        unit = fields[1]
        canonical_unit = self.normalize_unit(unit)
        return Quantity(
            value=self.convert(numeric_value, unit, canonical_unit),
            unit=canonical_unit,
        )

    def convert(self, value: float, source_unit: str, target_unit: str) -> float:
        """Convert one value between compatible supported units.

        Args:
            value: Numeric value in ``source_unit``.
            source_unit: Supported source unit or alias.
            target_unit: Supported target unit or alias.

        Returns:
            ``value`` expressed in the normalized form of ``target_unit``.

        Raises:
            ValueError: If either unit is unsupported or dimensions differ.
        """
        if not isinstance(source_unit, str) or not source_unit:
            raise ValueError("Unit must be a non-empty string.")
        if not isinstance(target_unit, str) or not target_unit:
            raise ValueError("Unit must be a non-empty string.")
        try:
            source = self._UNIT_DEFINITIONS[source_unit]
            target = self._UNIT_DEFINITIONS[target_unit]
        except KeyError as error:
            raise ValueError(f"Unsupported catalogue unit: {error.args[0]}.") from error
        if source["dimension"] != target["dimension"]:
            raise ValueError(
                f"Cannot convert {source_unit} to {target_unit}: incompatible dimensions."
            )
        canonical_value = float(value) * float(source["factor"])
        return canonical_value / float(target["factor"])
