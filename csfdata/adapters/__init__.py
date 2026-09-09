"""
Class adapters for importing simulations. 
Each module is dedicated to a simulation code and should have a standard
format.\n
- These importers should be read only.
- Other modules will take care of the syncyng. The job of these modules is to
  translate them.


These adapters will also be used for diagnostics and verification. These
adapters should know how to do all operations in the simulation folders.
"""

from csfdata.adapters.dcaf import DcafAdapter

__all__ = ["DcafAdapter"]
