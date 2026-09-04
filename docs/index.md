# Welcome to the Clustered Star Formation Database documentation


I will be updating this with documentation. For now is just a roadmap of the functions so I can keep track of what each function is for and how it works.

Most of the documentation should be inserted on the code itself, so keep that in mind when writing.

I am talking to you JP

## Canonical Catalogue Units

`csfdata` uses these canonical units for interpreted catalogue values:

| Quantity | Unit |
| --- | --- |
| Time | `Myr` |
| Length | `pc` |
| Mass | `M_sun` |
| Velocity | `km/s` |
| Surface density | `M_sun / pc^2` |
| Mass density | `M_sun / pc^3` |
| Number density | `cm^-3` |
| Temperature | `K` |
| Magnetic field | `microG` |
| Energy | `erg` |

Raw simulation configurations and outputs retain their original units. An
adapter converts a value only when its source unit and conversion are explicit;
otherwise, the value is recorded as unknown. Mass density and number density
remain distinct because converting between them requires an explicit mean
molecular-weight assumption.
