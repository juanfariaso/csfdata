import pytest

from csfdata.units import Quantity, UnitConverter


def test_parse_string_normalizes_known_aliases() -> None:
    converter = UnitConverter()

    assert converter.parse_string("10.0 parsec") == Quantity(10.0, "pc")
    assert converter.parse_string("5000 MSun") == Quantity(5000.0, "Msun")


def test_convert_time_units() -> None:
    assert UnitConverter().convert(1000.0, "kyr", "Myr") == 1.0


def test_converter_rejects_incompatible_units() -> None:
    with pytest.raises(ValueError, match="incompatible dimensions"):
        UnitConverter().convert(1.0, "Myr", "pc")
