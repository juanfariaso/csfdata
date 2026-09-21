# Units

`csfdata` uses these canonical units for interpreted catalogue values:

| Quantity | Unit |
| --- | --- |
| Time | `Myr` |
| Length | `pc` |
| Mass | `Msun` |
| Velocity | `km/s` |
| Surface density | `Msun / pc^2` |
| Mass density | `Msun / pc^3` |
| Number density | `cm^-3` |
| Temperature | `K` |
| Magnetic field | `microG` |
| Energy | `erg` |

Raw simulation configurations and outputs retain their original units. An
adapter converts a value only when its source unit and conversion are explicit;
otherwise, the value is recorded as unknown. Mass density and number density
remain distinct because converting between them requires an explicit
mean-molecular-weight assumption.

## Basic Converter

[`UnitConverter`][csfdata.units.UnitConverter] is a deliberately small,
dependency-free helper for parsing configuration values such as `3.0 Myr`.
It is not a replacement for AMUSE or Astropy units, and it does not implement
compound units or scientific unit arithmetic.

Its initial supported dimensions are time, length, mass, and velocity. It
normalizes known D-CAF aliases, including `parsec` to `pc` and `MSun` to
`Msun`.

```python
from csfdata.units import UnitConverter

converter = UnitConverter()

radius = converter.parse_string("10.0 parsec")
print(radius.value, radius.unit)  # 10.0 pc

time = converter.convert(1000.0, "kyr", "Myr")
print(time)  # 1.0
```

Unsupported or incompatible units raise `ValueError` rather than being
silently guessed.
